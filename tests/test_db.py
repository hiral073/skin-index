import sqlite3
from contextlib import closing

import pytest

from database.db import get_db, init_db, seed_db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def query(db_path, sql, params=()):
    with closing(get_db(db_path)) as conn:
        return conn.execute(sql, params).fetchall()


def test_init_db_creates_tables(db_path):
    init_db(db_path)
    rows = query(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    names = {row["name"] for row in rows}
    assert {"products", "ingredients", "product_ingredients", "exchange_rates"} <= names


def test_exchange_rates_survive_a_second_init_db(db_path):
    init_db(db_path)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES ('2026-11-11', 'USD', 'INR', 93.69, '2026-11-11')"
        )
    init_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM exchange_rates")[0][0] == 1


def test_exchange_rates_are_unique_per_pair_and_date(db_path):
    init_db(db_path)
    insert = (
        "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
        " VALUES ('2026-11-11', 'USD', 'INR', 93.69, '2026-11-11')"
    )
    with closing(get_db(db_path)) as conn:
        conn.execute(insert)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert)


def test_init_db_is_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)


def test_get_db_uses_row_factory_and_foreign_keys(db_path):
    with closing(get_db(db_path)) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_seed_db_inserts_five_products(db_path):
    init_db(db_path)
    seed_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM products")[0][0] == 5


def test_seed_db_twice_does_not_duplicate(db_path):
    init_db(db_path)
    seed_db(db_path)
    seed_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM products")[0][0] == 5


def test_seed_db_ingredients_are_unique_and_shared(db_path):
    init_db(db_path)
    seed_db(db_path)
    names = [r["name"] for r in query(db_path, "SELECT name FROM ingredients")]
    assert names
    assert len(names) == len(set(names))
    links = query(db_path, "SELECT COUNT(*) FROM product_ingredients")[0][0]
    assert links > len(names)  # at least one ingredient used by several products


def test_seed_db_positions_follow_label_order(db_path):
    init_db(db_path)
    seed_db(db_path)
    for product in query(db_path, "SELECT id FROM products"):
        positions = [
            r["position"]
            for r in query(
                db_path,
                "SELECT position FROM product_ingredients WHERE product_id = ?"
                " ORDER BY position",
                (product["id"],),
            )
        ]
        assert positions == list(range(1, len(positions) + 1))


def test_seed_db_price_per_ml(db_path):
    init_db(db_path)
    seed_db(db_path)
    for row in query(db_path, "SELECT price, size_ml, price_per_ml FROM products"):
        assert row["price_per_ml"] == pytest.approx(row["price"] / row["size_ml"], abs=1e-4)


def test_foreign_key_is_enforced(db_path):
    init_db(db_path)
    seed_db(db_path)
    with closing(get_db(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position)"
                " VALUES (999, 1, 1)"
            )
