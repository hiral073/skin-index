import sqlite3
from contextlib import closing

import pytest
import requests

from database.db import get_db, init_db
from database.services import (
    RateInfo, get_product_detail, get_usd_inr_rate, inr_per_ml, inr_price,
    reset_rate_cooldown,
)

TODAY = "2026-11-11"


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def save_rate(db_path, rate, rate_date, fetched_on):
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES (?, 'USD', 'INR', ?, ?)",
            (rate_date, rate, fetched_on),
        )


def saved_rows(db_path):
    with closing(get_db(db_path)) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT rate_date, base, quote, rate, fetched_on FROM exchange_rates"
        )]


def test_rate_is_fetched_and_saved(db_path, rate_api):
    info = get_usd_inr_rate(db_path, today=TODAY)
    assert info == RateInfo(93.69, "2026-11-11", False)
    assert len(rate_api.calls) == 1
    assert saved_rows(db_path) == [("2026-11-11", "USD", "INR", 93.69, TODAY)]


def test_rate_saved_today_is_reused_without_a_second_call(db_path, rate_api):
    get_usd_inr_rate(db_path, today=TODAY)
    again = get_usd_inr_rate(db_path, today=TODAY)
    assert again == RateInfo(93.69, "2026-11-11", False)
    assert len(rate_api.calls) == 1


def test_weekend_rate_with_older_rate_date_is_not_refetched(db_path, rate_api):
    # Source publishes Friday's date on Saturday; we saved it today
    save_rate(db_path, 90.0, "2026-11-06", fetched_on=TODAY)
    info = get_usd_inr_rate(db_path, today=TODAY)
    assert info == RateInfo(90.0, "2026-11-06", False)
    assert rate_api.calls == []


def test_new_day_fetches_again_and_keeps_history(db_path, rate_api):
    save_rate(db_path, 90.0, "2026-11-10", fetched_on="2026-11-10")
    info = get_usd_inr_rate(db_path, today=TODAY)
    assert info.rate == 93.69 and info.stale is False
    assert len(rate_api.calls) == 1
    assert len(saved_rows(db_path)) == 2


def test_same_rate_date_is_updated_not_duplicated(db_path, rate_api):
    save_rate(db_path, 90.0, "2026-11-11", fetched_on="2026-11-11")
    get_usd_inr_rate(db_path, today="2026-11-12")
    assert saved_rows(db_path) == [("2026-11-11", "USD", "INR", 93.69, "2026-11-12")]


def test_stale_rate_is_used_when_the_api_fails(db_path, rate_api):
    save_rate(db_path, 90.0, "2026-11-10", fetched_on="2026-11-10")
    rate_api.error = requests.Timeout("timed out")
    info = get_usd_inr_rate(db_path, today=TODAY)
    assert info == RateInfo(90.0, "2026-11-10", True)
    assert len(rate_api.calls) == 1


def test_most_recent_rate_is_the_stale_one(db_path, rate_api):
    save_rate(db_path, 88.0, "2026-11-05", fetched_on="2026-11-05")
    save_rate(db_path, 90.0, "2026-11-10", fetched_on="2026-11-10")
    rate_api.error = requests.ConnectionError("down")
    assert get_usd_inr_rate(db_path, today=TODAY) == RateInfo(90.0, "2026-11-10", True)


def test_none_when_no_rate_was_ever_saved_and_api_fails(db_path, rate_api):
    rate_api.error = requests.ConnectionError("down")
    assert get_usd_inr_rate(db_path, today=TODAY) is None
    assert saved_rows(db_path) == []


def test_bad_api_reply_is_treated_as_failure(db_path, rate_api):
    rate_api.payload = {"base": "USD", "date": "2026-11-11", "rates": {"INR": 0}}
    assert get_usd_inr_rate(db_path, today=TODAY) is None
    assert saved_rows(db_path) == []


def test_failed_fetch_is_not_retried_straight_away(db_path, rate_api):
    rate_api.error = requests.Timeout("timed out")
    get_usd_inr_rate(db_path, today=TODAY)
    get_usd_inr_rate(db_path, today=TODAY)
    get_usd_inr_rate(db_path, today=TODAY)
    assert len(rate_api.calls) == 1


def test_fetch_is_retried_after_the_cooldown_is_reset(db_path, rate_api):
    rate_api.error = requests.Timeout("timed out")
    get_usd_inr_rate(db_path, today=TODAY)
    reset_rate_cooldown()
    rate_api.error = None
    assert get_usd_inr_rate(db_path, today=TODAY).rate == 93.69
    assert len(rate_api.calls) == 2


def test_database_without_exchange_rates_table_gets_it(tmp_path, rate_api):
    path = str(tmp_path / "old.db")
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")  # pre-Step-4 database
    assert get_usd_inr_rate(path, today=TODAY).rate == 93.69


def add_product_with_ingredients(db_path, ingredients, **fields):
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (fields.get("name", "Bravo Cream"), "Dew Labs", fields.get("category", "Moisturizers"),
             fields.get("price", 20.0), fields.get("size_text", "100 mL"),
             fields.get("price_per_ml", 0.2), fields.get("compare_group")),
        ).lastrowid
        for position, name, *percent in ingredients:   # (position, name[, stated_percent])
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (name,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (name,)).fetchone()[0]
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
                " VALUES (?, ?, ?, ?)", (pid, iid, position, percent[0] if percent else None),
            )
    return pid


def test_get_product_detail_returns_fields_and_ingredients_in_label_order(db_path):
    pid = add_product_with_ingredients(
        db_path, [(2, "Glycerin"), (1, "Water"), (3, "Squalane")], compare_group="Moisturizers"
    )
    assert get_product_detail(pid, db_path) == {
        "id": pid, "name": "Bravo Cream", "brand": "Dew Labs", "category": "Moisturizers",
        "compare_group": "Moisturizers",
        "size_text": "100 mL", "price": 20.0, "price_per_ml": 0.2,
        "loves_count": None, "rating": None, "reviews": None,
        "ingredients": [
            {"name": "Water", "stated_percent": None},
            {"name": "Glycerin", "stated_percent": None},
            {"name": "Squalane", "stated_percent": None},
        ],
    }


def test_get_product_detail_returns_stated_percent_per_ingredient(db_path):
    pid = add_product_with_ingredients(
        db_path, [(2, "Zinc Oxide", 12.025), (1, "Water"), (3, "Squalane")]
    )
    assert get_product_detail(pid, db_path)["ingredients"] == [
        {"name": "Water", "stated_percent": None},
        {"name": "Zinc Oxide", "stated_percent": 12.025},
        {"name": "Squalane", "stated_percent": None},
    ]


def test_get_product_detail_only_returns_that_products_ingredients(db_path):
    first = add_product_with_ingredients(db_path, [(1, "Water"), (2, "Glycerin")])
    second = add_product_with_ingredients(db_path, [(1, "Water")], name="Other")
    names = lambda pid: [i["name"] for i in get_product_detail(pid, db_path)["ingredients"]]  # noqa: E731
    assert names(first) == ["Water", "Glycerin"]
    assert names(second) == ["Water"]


def test_get_product_detail_keeps_missing_fields_as_none(db_path):
    pid = add_product_with_ingredients(
        db_path, [], category=None, price=None, size_text=None, price_per_ml=None
    )
    product = get_product_detail(pid, db_path)
    assert product["ingredients"] == []
    assert [product[k] for k in ("category", "price", "size_text", "price_per_ml")] == [None] * 4


@pytest.mark.parametrize("bad_id", [
    999, 0, -1, None, True, 1.5, 2**63, 10**30, "1", "1 OR 1=1", "1; DROP TABLE products",
])
def test_get_product_detail_unknown_id_is_none(db_path, bad_id):
    add_product_with_ingredients(db_path, [(1, "Water")])
    assert get_product_detail(bad_id, db_path) is None
    assert get_product_detail(1, db_path) is not None   # table still there


@pytest.mark.parametrize("price, rate, expected", [
    (30.0, 93.69, 2811),     # 2810.7 rounds up
    (20.0, 93.69, 1874),     # 1873.8
    (12.34, 93.69, 1156),    # 1156.1346 rounds down
    (5.0, 90.5, 453),        # 452.5: halves go up (round() would give 452)
    (5.0, 90.1, 451),        # 450.5
    (0.0, 93.69, 0),
    (120, 93, 11160),        # ints work too
])
def test_inr_price_rounds_to_whole_rupees_half_up(price, rate, expected):
    result = inr_price(price, rate)
    assert result == expected
    assert isinstance(result, int)


@pytest.mark.parametrize("price, rate", [(None, 93.69), (30.0, None), (None, None)])
def test_inr_price_none_when_an_input_is_missing(price, rate):
    assert inr_price(price, rate) is None


@pytest.mark.parametrize("per_ml, rate, expected", [
    (0.2, 93.69, 18.74),
    (1.6333, 93.69, 153.02),
    (0.0001, 93.69, 0.01),
    (0.0, 93.69, 0.0),
])
def test_inr_per_ml_math(per_ml, rate, expected):
    assert inr_per_ml(per_ml, rate) == pytest.approx(expected)


@pytest.mark.parametrize("per_ml, rate", [(None, 93.69), (0.2, None), (None, None)])
def test_inr_per_ml_none_when_an_input_is_missing(per_ml, rate):
    assert inr_per_ml(per_ml, rate) is None
