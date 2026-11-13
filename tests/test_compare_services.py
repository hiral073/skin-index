from contextlib import closing

import pytest

from database.db import get_db, init_db
from database.services import (
    compare_products, get_product_detail, list_group_ingredients, list_groups, list_products_in_group,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def add(db_path, name, brand="Dew Labs", group="Face Serums", price=20.0, size_text="100 mL",
        price_per_ml=0.2, category=None, ingredients=(), loves=None, rating=None, reviews=None):
    """Insert a product; ingredients are (name,) or (name, stated_percent) in label order."""
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group,"
            " loves_count, rating, reviews) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category or group, price, size_text, price_per_ml, group, loves, rating, reviews),
        ).lastrowid
        for position, (ingredient, *percent) in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
                " VALUES (?, ?, ?, ?)", (pid, iid, position, percent[0] if percent else None),
            )
    return pid


# ---------------------------------------------------------------- compare_products

def pair(db_path, a_ingredients, b_ingredients, a_name="Bravo Serum", b_name="Delta Serum"):
    a = add(db_path, a_name, ingredients=a_ingredients)
    b = add(db_path, b_name, brand="Glow Co", ingredients=b_ingredients)
    return a, b


def test_same_group_and_main_ingredient_is_comparable_and_returns_both_products(db_path):
    a, b = pair(db_path, [("Water",), ("Niacinamide",)], [("Niacinamide",)])
    result = compare_products(a, b, db_path)
    assert result["status"] == "ok" and result["comparable"] is True
    assert (result["a_state"], result["b_state"]) == ("found", "found")
    assert result["a_group"] == result["b_group"] == "Face Serums"
    assert result["a_main"] == result["b_main"] == result["shared_main"] == ["niacinamide"]
    assert result["a"]["name"] == "Bravo Serum" and result["b"]["brand"] == "Glow Co"
    assert result["a"]["ingredients"] == [
        {"name": "Water", "stated_percent": None}, {"name": "Niacinamide", "stated_percent": None},
    ]


def test_a_niacinamide_serum_cannot_be_compared_with_a_vitamin_c_serum(db_path):
    a, b = pair(db_path, [("Water",), ("Niacinamide",)], [("Water",), ("Ascorbic Acid",)])
    result = compare_products(a, b, db_path)
    assert result["status"] == "different_ingredients" and result["comparable"] is False
    assert result["a_group"] == result["b_group"] == "Face Serums"          # same category, still refused
    assert (result["a_main"], result["b_main"], result["shared_main"]) == (["niacinamide"], ["vitamin-c"], [])
    assert result["ingredients"] is None


def test_a_product_in_several_main_groups_is_comparable_through_a_shared_one(db_path):
    a, b = pair(db_path, [("Niacinamide",), ("Sodium Hyaluronate",)], [("Water",), ("Sodium Hyaluronate",)])
    result = compare_products(a, b, db_path)
    assert result["a_main"] == ["niacinamide", "hyaluronic-acid"] and result["b_main"] == ["hyaluronic-acid"]
    assert result["shared_main"] == ["hyaluronic-acid"] and result["comparable"] is True


def test_a_product_in_no_main_group_is_not_compared(db_path):
    a, b = pair(db_path, [("Water",), ("Glycerin",)], [("Niacinamide",)])
    for x, y in ((a, b), (b, a)):
        result = compare_products(x, y, db_path)
        assert result["status"] == "no_main_ingredient" and result["comparable"] is False
        assert result["ingredients"] is None
    assert compare_products(a, b, db_path)["a_main"] == []


def test_the_main_ingredient_counts_when_it_is_in_the_name_not_the_ingredients(db_path):
    a = add(db_path, "Niacinamide 10% Serum", ingredients=[("Water",)])
    b = add(db_path, "Other", ingredients=[("Water",), ("Niacinamide",)])
    assert compare_products(a, b, db_path)["comparable"] is True


def test_a_main_ingredient_below_the_first_ten_does_not_count(db_path):
    filler = [(f"Filler {i}",) for i in range(10)]
    a = add(db_path, "Deep", ingredients=filler + [("Niacinamide",)])
    b = add(db_path, "Shallow", ingredients=[("Niacinamide",)])
    assert compare_products(a, b, db_path)["status"] == "no_main_ingredient"


def test_shared_only_a_and_only_b_ingredient_lists(db_path):
    a, b = pair(
        db_path,
        [("Water",), ("Glycerin",), ("Niacinamide", 5.0), ("Squalane",)],
        [("Squalane",), ("Water",), ("Niacinamide", 3.0), ("Panthenol",)],
    )
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Water", "Niacinamide", "Squalane"]            # in A's label order
    assert ing["only_a"] == ["Glycerin"] and ing["only_b"] == ["Panthenol"]
    assert (ing["shared_count"], ing["only_a_count"], ing["only_b_count"]) == (3, 1, 1)


def test_an_ingredient_with_and_without_a_stated_percent_is_one_shared_ingredient(db_path):
    a, b = pair(db_path, [("Niacinamide", 2.0)], [("Niacinamide",)])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Niacinamide"] and ing["only_a"] == [] and ing["only_b"] == []


def test_ingredients_are_none_when_a_product_lists_none_but_is_named_for_the_main_ingredient(db_path):
    a = add(db_path, "Niacinamide Serum", ingredients=[])
    b = add(db_path, "Other", ingredients=[("Niacinamide",)])
    result = compare_products(a, b, db_path)
    assert result["comparable"] is True and result["ingredients"] is None


def test_the_result_has_no_verdict_and_no_overlap(db_path):
    a, b = pair(db_path, [("Niacinamide",)], [("Niacinamide",)])
    result = compare_products(a, b, db_path)
    assert set(result) == {"a", "b", "a_state", "b_state", "status", "comparable", "a_group", "b_group",
                           "a_main", "b_main", "shared_main", "ingredients"}
    assert set(result["ingredients"]) == {"shared", "only_a", "only_b", "shared_count", "only_a_count",
                                          "only_b_count"}


def test_the_product_carries_likes_rating_and_reviews(db_path):
    a = add(db_path, "Bravo Serum", loves=1200, rating=4.5, reviews=300, ingredients=[("Niacinamide",)])
    b = add(db_path, "Delta Serum", ingredients=[("Niacinamide",)])
    result = compare_products(a, b, db_path)
    assert (result["a"]["loves_count"], result["a"]["rating"], result["a"]["reviews"]) == (1200, 4.5, 300)
    assert (result["b"]["loves_count"], result["b"]["rating"], result["b"]["reviews"]) == (None, None, None)


def test_different_groups_are_not_compared_even_with_the_same_main_ingredient(db_path):
    a = add(db_path, "Bravo Cream", group="Moisturizers", ingredients=[("Niacinamide",)])
    b = add(db_path, "Alpha Serum", group="Face Serums", ingredients=[("Niacinamide",)])
    result = compare_products(a, b, db_path)
    assert result["status"] == "different_groups" and result["comparable"] is False
    assert (result["a_group"], result["b_group"]) == ("Moisturizers", "Face Serums")
    assert result["ingredients"] is None and result["a"]["name"] == "Bravo Cream"


def test_a_product_without_a_group_is_not_compared(db_path):
    a = add(db_path, "Tiny Serum", group=None, category="Mini Size", ingredients=[("Niacinamide",)])
    b = add(db_path, "Bravo Serum", ingredients=[("Niacinamide",)])
    for x, y in ((a, b), (b, a), (a, a)):
        result = compare_products(x, y, db_path)
        assert result["comparable"] is False and result["ingredients"] is None
    assert compare_products(a, b, db_path)["status"] == "no_group"
    assert compare_products(a, b, db_path)["a_group"] is None


def test_two_products_without_a_group_do_not_count_as_the_same_group(db_path):
    a = add(db_path, "Tiny One", group=None, category="Mini Size")
    b = add(db_path, "Tiny Two", group=None, category="Mini Size")
    assert compare_products(a, b, db_path)["status"] == "no_group"


def test_same_product_twice(db_path):
    a = add(db_path, "Bravo Serum", ingredients=[("Niacinamide",)])
    result = compare_products(a, a, db_path)
    assert result["status"] == "same_product" and result["comparable"] is False
    assert result["ingredients"] is None


def test_unknown_and_unchosen_sides(db_path):
    a = add(db_path, "Bravo Serum")
    result = compare_products(a, 999, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("found", "unknown", "waiting")
    assert result["b"] is None and result["b_group"] is None and result["b_main"] == []
    result = compare_products(None, a, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("not chosen", "found", "waiting")
    result = compare_products(None, None, db_path)
    assert (result["a_state"], result["b_state"], result["status"]) == ("not chosen", "not chosen", "waiting")


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "abc", "1 OR 1=1", 2**63, 10**30])
def test_unusable_ids_count_as_unknown_not_a_crash(db_path, bad):
    a = add(db_path, "Bravo Serum")
    result = compare_products(a, bad, db_path)
    assert result["b_state"] == "unknown" and result["status"] == "waiting"
    assert compare_products(a, a, db_path)["status"] == "same_product"      # tables still fine


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


def test_the_main_ingredients_of_a_group_are_counted_in_the_order_of_the_content_file(db_path):
    add(db_path, "N1", ingredients=[("Niacinamide",)])
    add(db_path, "N2", ingredients=[("Water",), ("Niacinamide",)])
    add(db_path, "V1", ingredients=[("Ascorbyl Glucoside",)])
    add(db_path, "P1", ingredients=[("Water",)])                                  # in no main group
    add(db_path, "Other group", group="Moisturizers", ingredients=[("Ceramide NP",)])
    assert list_group_ingredients("Face Serums", db_path) == [
        {"key": "niacinamide", "label": "niacinamide", "products": 2},
        {"key": "vitamin-c", "label": "vitamin C", "products": 1},                # one product: too few
    ]
    assert list_group_ingredients("Nope", db_path) == []


def names(items):
    return [p["name"] for p in items]


def test_products_are_limited_to_the_group_and_main_ingredient_and_sorted_by_name(db_path):
    add(db_path, "charlie", ingredients=[("Niacinamide",)])
    add(db_path, "Bravo", ingredients=[("Water",), ("Niacinamide",)])
    add(db_path, "Alpha", ingredients=[("Water",)], brand="X")                   # name: no main ingredient
    add(db_path, "Zulu Vitamin C Serum", ingredients=[("Water",)])
    add(db_path, "Cream", group="Moisturizers", ingredients=[("Niacinamide",)])  # other group
    listing = list_products_in_group("Face Serums", "niacinamide", db_path=db_path)
    assert names(listing) == ["Bravo", "charlie"]
    assert set(listing[0]) == {"id", "name", "brand", "size_text", "price"}
    assert names(list_products_in_group("Face Serums", "vitamin-c", db_path=db_path)) == ["Zulu Vitamin C Serum"]
    assert list_products_in_group("Face Serums", "no-such-key", db_path=db_path) == []


def test_product_a_is_left_out_of_the_list_for_b(db_path):
    a = add(db_path, "Alpha", ingredients=[("Niacinamide",)])
    add(db_path, "Bravo", ingredients=[("Niacinamide",)])
    assert names(list_products_in_group("Face Serums", "niacinamide", exclude_id=a, db_path=db_path)) == ["Bravo"]


def test_a_malicious_group_or_ingredient_is_only_data(db_path):
    add(db_path, "Alpha", ingredients=[("Niacinamide",)])
    assert list_products_in_group("x'; DROP TABLE products; --", "niacinamide", db_path=db_path) == []
    assert list_group_ingredients("x'; DROP TABLE products; --", db_path) == []
    assert len(list_products_in_group("Face Serums", "niacinamide", db_path=db_path)) == 1
