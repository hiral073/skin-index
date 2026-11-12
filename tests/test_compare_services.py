from contextlib import closing

import pytest

from database.db import COMPARE_DROPDOWN_MAX, get_db, init_db
from database.services import (
    compare_products, get_product_detail, list_brands_in_group, list_groups,
    list_products_in_group,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def add(db_path, name, brand="Dew Labs", group="Moisturizers", price=20.0, size_text="100 mL",
        price_per_ml=0.2, category=None, ingredients=()):
    """Insert a product; ingredients are (name,) or (name, stated_percent) in label order."""
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category or group, price, size_text, price_per_ml, group),
        ).lastrowid
        for position, (ingredient, *percent) in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
                " VALUES (?, ?, ?, ?)", (pid, iid, position, percent[0] if percent else None),
            )
    return pid


def add_many(db_path, count, group, brand="Bulk", start=0):
    with closing(get_db(db_path)) as conn, conn:
        conn.executemany(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(f"Item {i:04d}", brand, group, 10.0, "50 mL", 0.2, group) for i in range(start, start + count)],
        )


# ---------------------------------------------------------------- compare_products

def pair(db_path, a_ingredients=(), b_ingredients=(), a_ppm=0.2, b_ppm=0.3):
    a = add(db_path, "Bravo Cream", price_per_ml=a_ppm, ingredients=a_ingredients)
    b = add(db_path, "Delta Balm", brand="Glow Co", price_per_ml=b_ppm, ingredients=b_ingredients)
    return a, b


def test_same_group_is_comparable_and_returns_both_products(db_path):
    a, b = pair(db_path, [("Water",)], [("Water",)])
    result = compare_products(a, b, db_path)
    assert result["status"] == "ok" and result["comparable"] is True
    assert (result["a_state"], result["b_state"]) == ("found", "found")
    assert result["a_group"] == result["b_group"] == "Moisturizers"
    assert result["a"]["name"] == "Bravo Cream" and result["b"]["brand"] == "Glow Co"
    assert result["a"]["ingredients"] == [{"name": "Water", "stated_percent": None}]


def test_cheaper_per_ml_percentage(db_path):
    a, b = pair(db_path, a_ppm=0.2, b_ppm=0.3)
    pm = compare_products(a, b, db_path)["price_per_ml"]
    assert pm["cheaper"] == "a" and pm["percent"] == pytest.approx(100 / 3)   # (0.3-0.2)/0.3
    assert (pm["a"], pm["b"]) == (0.2, 0.3)
    # swapping the sides swaps the winner, not the percentage
    pm = compare_products(b, a, db_path)["price_per_ml"]
    assert pm["cheaper"] == "b" and pm["percent"] == pytest.approx(100 / 3)


@pytest.mark.parametrize("a_ppm, b_ppm, cheaper, percent", [
    (1.0, 2.0, "a", 50.0),
    (0.5, 0.25, "b", 50.0),
    (0.054, 0.054, "equal", 0.0),
    (0.0, 0.5, "a", 100.0),
])
def test_price_per_ml_verdict_cases(db_path, a_ppm, b_ppm, cheaper, percent):
    a, b = pair(db_path, a_ppm=a_ppm, b_ppm=b_ppm)
    pm = compare_products(a, b, db_path)["price_per_ml"]
    assert pm["cheaper"] == cheaper and pm["percent"] == pytest.approx(percent)


@pytest.mark.parametrize("a_ppm, b_ppm", [(None, 0.3), (0.2, None), (None, None)])
def test_missing_price_per_ml_gives_no_verdict(db_path, a_ppm, b_ppm):
    a, b = pair(db_path, a_ppm=a_ppm, b_ppm=b_ppm)
    result = compare_products(a, b, db_path)
    assert result["comparable"] is True
    assert result["price_per_ml"]["cheaper"] is None and result["price_per_ml"]["percent"] is None


def test_shared_only_a_only_b_and_overlap(db_path):
    a, b = pair(
        db_path,
        [("Water",), ("Glycerin",), ("Squalane", 5.0)],
        [("Water",), ("Squalane", 3.0), ("Niacinamide",)],
    )
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == [
        {"name": "Water", "a_percent": None, "b_percent": None},
        {"name": "Squalane", "a_percent": 5.0, "b_percent": 3.0},      # both state a strength
    ]
    assert ing["only_a"] == ["Glycerin"] and ing["only_b"] == ["Niacinamide"]
    assert (ing["shared_count"], ing["only_a_count"], ing["only_b_count"], ing["total_count"]) == (2, 1, 1, 4)
    assert ing["overlap_percent"] == pytest.approx(50.0)               # 2 shared of 4 distinct


def test_shared_ingredient_keeps_one_sided_strengths_as_given(db_path):
    a, b = pair(db_path, [("Zinc Oxide", 12.0)], [("Zinc Oxide",)])
    shared = compare_products(a, b, db_path)["ingredients"]["shared"]
    assert shared == [{"name": "Zinc Oxide", "a_percent": 12.0, "b_percent": None}]


def test_ingredient_with_and_without_a_stated_percent_is_one_shared_ingredient(db_path):
    a, b = pair(db_path, [("Salicylic Acid", 2.0)], [("Salicylic Acid",)])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared_count"] == 1 and ing["only_a"] == [] and ing["only_b"] == []
    assert ing["overlap_percent"] == pytest.approx(100.0)


def test_identical_and_disjoint_ingredient_lists(db_path):
    a, b = pair(db_path, [("Water",), ("Glycerin",)], [("Water",), ("Glycerin",)])
    assert compare_products(a, b, db_path)["ingredients"]["overlap_percent"] == pytest.approx(100.0)
    c = add(db_path, "Other", ingredients=[("Squalane",)])
    d = add(db_path, "Another", ingredients=[("Ceramide NP",)])
    ing = compare_products(c, d, db_path)["ingredients"]
    assert ing["shared_count"] == 0 and ing["overlap_percent"] == 0.0 and ing["total_count"] == 2


def test_ingredients_are_none_when_either_product_has_none(db_path):
    a, b = pair(db_path, [("Water",)], [])
    result = compare_products(a, b, db_path)
    assert result["comparable"] is True and result["ingredients"] is None
    assert result["price_per_ml"]["cheaper"] == "a"


def test_different_groups_are_not_compared(db_path):
    a = add(db_path, "Bravo Cream", group="Moisturizers", ingredients=[("Water",)])
    b = add(db_path, "Alpha Serum", group="Face Serums", price_per_ml=0.05, ingredients=[("Water",)])
    result = compare_products(a, b, db_path)
    assert result["status"] == "different_groups" and result["comparable"] is False
    assert (result["a_group"], result["b_group"]) == ("Moisturizers", "Face Serums")
    assert result["price_per_ml"] is None and result["ingredients"] is None
    assert result["a"]["name"] == "Bravo Cream" and result["b"]["name"] == "Alpha Serum"


def test_a_product_without_a_group_is_not_compared(db_path):
    a = add(db_path, "Tiny Cream", group=None, category="Mini Size")
    b = add(db_path, "Bravo Cream")
    for x, y in ((a, b), (b, a), (a, a)):
        result = compare_products(x, y, db_path)
        assert result["comparable"] is False
        assert result["price_per_ml"] is None and result["ingredients"] is None
    assert compare_products(a, b, db_path)["status"] == "no_group"
    assert compare_products(a, b, db_path)["a_group"] is None


def test_two_products_without_a_group_do_not_count_as_the_same_group(db_path):
    a = add(db_path, "Tiny Cream", group=None, category="Mini Size")
    b = add(db_path, "Tiny Serum", group=None, category="Mini Size")
    assert compare_products(a, b, db_path)["status"] == "no_group"


def test_same_product_twice(db_path):
    a = add(db_path, "Bravo Cream")
    result = compare_products(a, a, db_path)
    assert result["status"] == "same_product" and result["comparable"] is False
    assert result["price_per_ml"] is None and result["ingredients"] is None


def test_unknown_and_unchosen_sides(db_path):
    a = add(db_path, "Bravo Cream")
    result = compare_products(a, 999, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("found", "unknown", "waiting")
    assert result["b"] is None and result["b_group"] is None
    result = compare_products(None, a, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("not chosen", "found", "waiting")
    result = compare_products(None, None, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("not chosen", "not chosen", "waiting")


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "abc", "1 OR 1=1", 2**63, 10**30])
def test_unusable_ids_count_as_unknown_not_a_crash(db_path, bad):
    a = add(db_path, "Bravo Cream")
    result = compare_products(a, bad, db_path)
    assert result["b_state"] == "unknown" and result["status"] == "waiting"
    assert compare_products(a, a, db_path)["status"] == "same_product"      # tables still fine


def test_compare_returns_plain_data_only(db_path):
    a, b = pair(db_path, [("Water",)], [("Water",)])
    result = compare_products(a, b, db_path)
    assert not any(isinstance(v, str) and "$" in v for v in result["a"].values() if v)
    assert set(result) == {"a", "b", "a_state", "b_state", "status", "comparable",
                           "a_group", "b_group", "price_per_ml", "ingredients"}


def test_get_product_detail_includes_the_compare_group(db_path):
    pid = add(db_path, "Bravo Cream", group="Face Serums")
    assert get_product_detail(pid, db_path)["compare_group"] == "Face Serums"


# ---------------------------------------------------------------- dropdown helpers

def test_list_groups_needs_two_products_skips_none_and_is_sorted(db_path):
    add(db_path, "A1", group="Moisturizers"), add(db_path, "A2", group="Moisturizers")
    add(db_path, "S1", group="face serums"), add(db_path, "S2", group="face serums")
    add(db_path, "L1", group="Sunscreen")                       # one product: not offered
    add(db_path, "M1", group=None, category="Mini Size")        # no group
    add(db_path, "M2", group=None, category="Mini Size")
    assert list_groups(db_path) == [
        {"name": "face serums", "products": 2}, {"name": "Moisturizers", "products": 2},
    ]


def test_list_groups_empty_database(db_path):
    assert list_groups(db_path) == []


def test_brands_are_filtered_by_group_counted_and_sorted(db_path):
    add(db_path, "A1", brand="zeta", group="Moisturizers")
    add(db_path, "A2", brand="Alpha", group="Moisturizers")
    add(db_path, "A3", brand="Alpha", group="Moisturizers")
    add(db_path, "S1", brand="Other Brand", group="Face Serums")
    assert list_brands_in_group("Moisturizers", db_path) == [
        {"brand": "Alpha", "products": 2}, {"brand": "zeta", "products": 1},
    ]
    assert list_brands_in_group("Nope", db_path) == []


def names(listing):
    return [p["name"] for p in listing["products"]]


def test_products_are_filtered_by_group_and_brand_and_sorted_by_name(db_path):
    add(db_path, "charlie", brand="Glow Co")
    add(db_path, "Bravo", brand="Dew Labs")
    add(db_path, "Alpha", brand="Glow Co")
    add(db_path, "Serum X", brand="Glow Co", group="Face Serums")
    listing = list_products_in_group("Moisturizers", db_path=db_path)
    assert names(listing) == ["Alpha", "Bravo", "charlie"]          # no serum, name order ignoring case
    assert listing["total"] == 3 and not listing["needs_brand"] and not listing["capped"]
    assert names(list_products_in_group("Moisturizers", brand="Glow Co", db_path=db_path)) == ["Alpha", "charlie"]
    assert names(list_products_in_group("Moisturizers", brand="Nobody", db_path=db_path)) == []
    first = listing["products"][0]
    assert set(first) == {"id", "name", "brand", "size_text", "price"}


def test_product_a_is_left_out_of_the_list_for_b(db_path):
    a = add(db_path, "Alpha")
    add(db_path, "Bravo")
    assert names(list_products_in_group("Moisturizers", exclude_id=a, db_path=db_path)) == ["Bravo"]


def test_search_inside_a_group_matches_name_or_brand_and_treats_wildcards_literally(db_path):
    add(db_path, "Hydra Gel", brand="Dew Labs")
    add(db_path, "Rich Cream", brand="Gel Works")
    add(db_path, "Plain Balm", brand="Glow Co")
    add(db_path, "50% Off Balm", brand="Glow Co")
    assert names(list_products_in_group("Moisturizers", q="gel", db_path=db_path)) == ["Hydra Gel", "Rich Cream"]
    assert names(list_products_in_group("Moisturizers", q="%", db_path=db_path)) == ["50% Off Balm"]
    assert names(list_products_in_group("Moisturizers", q="x'; DROP TABLE products; --", db_path=db_path)) == []
    assert len(list_products_in_group("Moisturizers", db_path=db_path)["products"]) == 4


def test_a_group_over_the_limit_needs_a_brand_first(db_path):
    add_many(db_path, COMPARE_DROPDOWN_MAX + 5, "Big", brand="Bulk")
    add(db_path, "Rare Find", brand="Small Brand", group="Big")
    no_brand = list_products_in_group("Big", db_path=db_path)
    assert no_brand["needs_brand"] is True and no_brand["products"] == []
    assert no_brand["total"] == COMPARE_DROPDOWN_MAX + 6
    assert no_brand == list_products_in_group("Big", q="item", db_path=db_path)   # search alone does not help
    with_brand = list_products_in_group("Big", brand="Small Brand", db_path=db_path)
    assert with_brand["needs_brand"] is False and names(with_brand) == ["Rare Find"]


def test_a_group_at_exactly_the_limit_lists_without_a_brand(db_path):
    add_many(db_path, COMPARE_DROPDOWN_MAX, "Edge")
    listing = list_products_in_group("Edge", db_path=db_path)
    assert listing["needs_brand"] is False and len(listing["products"]) == COMPARE_DROPDOWN_MAX
    assert listing["capped"] is False


def test_a_long_list_is_capped_even_with_a_brand(db_path):
    add_many(db_path, COMPARE_DROPDOWN_MAX + 20, "Big", brand="Bulk")
    listing = list_products_in_group("Big", brand="Bulk", db_path=db_path)
    assert len(listing["products"]) == COMPARE_DROPDOWN_MAX
    assert listing["total"] == COMPARE_DROPDOWN_MAX + 20 and listing["capped"] is True
    assert listing["products"][0]["name"] == "Item 0000"                 # sorted by name
    narrowed = list_products_in_group("Big", brand="Bulk", q="Item 03", db_path=db_path)
    assert narrowed["capped"] is False and narrowed["total"] == len(narrowed["products"]) > 0
