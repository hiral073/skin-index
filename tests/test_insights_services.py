import sqlite3
from contextlib import closing

import pytest

from database.db import get_db, init_db
from database.services import INSIGHTS_CONFIG, get_insights, weighted_rating


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def add(db_path, name, brand="Dew Labs", group="Moisturizers", price=20.0, ppm=0.2,
        loves=100, rating=4.5, reviews=100, ingredients=()):
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group,"
            " loves_count, rating, reviews) VALUES (?, ?, ?, ?, '100 mL', ?, ?, ?, ?, ?)",
            (name, brand, group or "Mini Size", price, ppm, group, loves, rating, reviews),
        ).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return pid


def add_n(db_path, group, count, **fields):
    return [add(db_path, f"{group} {i:02d}", group=group, **fields) for i in range(count)]


def names(items, key="name"):
    return [i[key] for i in items]


def test_config_holds_every_threshold():
    assert INSIGHTS_CONFIG == {
        "min_group_products": 5, "top_n": 10,
        "well_reviewed_min_reviews": 50, "well_reviewed_min_rating": 4.0,
        "band_min_reviews": 10, "band_min_products": 9,
    }


# ---------------------------------------------------------------- weighted rating

def test_weighted_rating_is_sum_of_rating_times_reviews_over_sum_of_reviews():
    assert weighted_rating([(4.0, 100), (5.0, 300)]) == pytest.approx(4.75)      # not the plain mean 4.5
    assert weighted_rating([(3.0, 1), (5.0, 1)]) == pytest.approx(4.0)
    assert weighted_rating([(4.2, 50)]) == pytest.approx(4.2)


@pytest.mark.parametrize("pairs", [[], [(None, 100)], [(4.0, None)], [(4.0, 0)], [(None, None), (5.0, 0)]])
def test_weighted_rating_is_none_when_nothing_usable(pairs):
    assert weighted_rating(pairs) is None


def test_weighted_rating_skips_unusable_products_but_keeps_the_rest():
    assert weighted_rating([(4.0, 100), (None, 500), (5.0, None), (5.0, 0), (5.0, 300)]) == pytest.approx(4.75)


def test_weighted_rating_accepts_a_generator():
    assert weighted_rating((r, n) for r, n in [(4.0, 100), (5.0, 300)]) == pytest.approx(4.75)


# ---------------------------------------------------------------- brands

def test_brands_are_ranked_by_total_loves_not_by_product_count(db_path):
    for i in range(5):
        add(db_path, f"Many {i}", brand="Many Products", loves=100)            # 500 loves, 5 products
    add(db_path, "Single Hit", brand="One Product", loves=10_000)              # 10,000 loves, 1 product
    brands = get_insights(db_path=db_path)["brands"]
    assert [(b["brand"], b["loves"], b["products"]) for b in brands] == [
        ("One Product", 10_000, 1), ("Many Products", 500, 5),
    ]


def test_brand_rating_is_weighted_by_reviews(db_path):
    add(db_path, "a", brand="Glow Co", loves=10, rating=4.0, reviews=100)
    add(db_path, "b", brand="Glow Co", loves=10, rating=5.0, reviews=300)
    add(db_path, "c", brand="Glow Co", loves=10, rating=None, reviews=None)       # loves count, rating does not
    [brand] = get_insights(db_path=db_path)["brands"]
    assert brand["average_rating"] == pytest.approx(4.75)
    assert brand["rated_reviews"] == 400 and brand["loves"] == 30 and brand["products"] == 3


def test_brand_with_no_ratings_has_no_average(db_path):
    add(db_path, "a", brand="Quiet", loves=5, rating=None, reviews=None)
    [brand] = get_insights(db_path=db_path)["brands"]
    assert brand["average_rating"] is None and brand["rated_reviews"] == 0 and brand["loves"] == 5


def test_brands_without_any_loves_data_are_skipped_and_missing_loves_are_not_zero(db_path):
    add(db_path, "a", brand="Unknown", loves=None)
    add(db_path, "b", brand="Mixed", loves=None)
    add(db_path, "c", brand="Mixed", loves=7)
    brands = get_insights(db_path=db_path)["brands"]
    assert [(b["brand"], b["loves"], b["products"]) for b in brands] == [("Mixed", 7, 2)]


def test_brands_are_the_top_ten_with_ties_broken_by_name(db_path):
    for i in range(12):
        add(db_path, f"p{i}", brand=f"Brand {i:02d}", loves=100)
    brands = get_insights(db_path=db_path)["brands"]
    assert names(brands, "brand") == [f"Brand {i:02d}" for i in range(10)]


def test_brands_count_every_product_including_ones_with_no_group(db_path):
    add(db_path, "grouped", brand="B", group="Serums", loves=10)
    add(db_path, "mini", brand="B", group=None, loves=90)
    [brand] = get_insights(db_path=db_path)["brands"]
    assert brand["loves"] == 100 and brand["products"] == 2


def test_the_brand_ranking_is_overall_even_when_a_group_is_chosen(db_path):
    add_n(db_path, "Serums", 5, brand="Serum Brand", loves=10)
    add(db_path, "other", brand="Huge Brand", group="Creams", loves=999_999)
    assert get_insights("Serums", db_path)["brands"] == get_insights(db_path=db_path)["brands"]
    assert get_insights("Serums", db_path)["brands"][0]["brand"] == "Huge Brand"


# ---------------------------------------------------------------- most loved products

def test_most_loved_products_sorted_by_loves_with_ties_by_name(db_path):
    add(db_path, "Zeta", loves=500)
    add(db_path, "alpha", loves=500)
    add(db_path, "Top", loves=900)
    add(db_path, "Zero", loves=0)
    add(db_path, "Unknown", loves=None)
    loved = get_insights(db_path=db_path)["loved_products"]
    assert names(loved) == ["Top", "alpha", "Zeta", "Zero"]        # loves 0 counts; missing is skipped
    assert set(loved[0]) == {"id", "name", "brand", "price", "size_text", "loves_count", "rating", "reviews"}


def test_most_loved_products_is_the_top_ten(db_path):
    for i in range(12):
        add(db_path, f"p{i:02d}", loves=1000 - i)
    assert names(get_insights(db_path=db_path)["loved_products"]) == [f"p{i:02d}" for i in range(10)]


def test_most_loved_products_overall_includes_products_with_no_group(db_path):
    add(db_path, "Mini", group=None, loves=900)
    add(db_path, "Serum", group="Serums", loves=100)
    assert names(get_insights(db_path=db_path)["loved_products"]) == ["Mini", "Serum"]


def test_most_loved_products_within_a_group_are_that_groups_only(db_path):
    add_n(db_path, "Serums", 5, loves=10)
    add(db_path, "Cream Star", group="Creams", loves=900)
    add(db_path, "Mini Star", group=None, loves=800)
    loved = get_insights("Serums", db_path)["loved_products"]
    assert len(loved) == 5 and all(n.startswith("Serums") for n in names(loved))


def test_products_missing_rating_or_reviews_still_show_among_the_most_loved(db_path):
    add(db_path, "No ratings", loves=500, rating=None, reviews=None)
    [loved] = get_insights(db_path=db_path)["loved_products"]
    assert loved["rating"] is None and loved["reviews"] is None and loved["loves_count"] == 500


# ---------------------------------------------------------------- selector and groups

def test_selector_lists_groups_with_five_or_more_products_by_name(db_path):
    add_n(db_path, "Serums", 5)
    add_n(db_path, "apples", 6, ppm=None, loves=None, rating=None, reviews=None)   # counted even with no data
    add_n(db_path, "Four", 4)
    add(db_path, "mini", group=None)
    data = get_insights(db_path=db_path)
    assert data["selector_groups"] == [{"name": "apples", "products": 6}, {"name": "Serums", "products": 5}]
    assert data["overview"] == {"products": 5 + 6 + 4 + 1, "brands": 1, "groups": 3, "ungrouped_products": 1}


def test_a_valid_group_sets_the_scope(db_path):
    add_n(db_path, "Serums", 5)
    data = get_insights("Serums", db_path)
    assert (data["group_status"], data["scope_group"], data["requested_group"]) == ("ok", "Serums", "Serums")
    assert data["well_reviewed"] is not None and data["price_bands"] is not None


@pytest.mark.parametrize("group", ["Nope", "", "serums", "Four", "x'; DROP TABLE products; --", "%", "' OR 1=1 --"])
def test_an_unknown_invalid_or_too_small_group_falls_back_to_the_overall_view(db_path, group):
    add_n(db_path, "Serums", 5, loves=10)
    add_n(db_path, "Four", 4, loves=99)
    data = get_insights(group, db_path)
    assert data["group_status"] == "unavailable" and data["scope_group"] is None
    assert data["well_reviewed"] is None and data["price_bands"] is None          # group-only sections
    assert len(data["loved_products"]) == 9 and data["overview"]["products"] == 9  # overall data
    assert get_insights(db_path=db_path)["overview"]["products"] == 9              # table intact


def test_no_group_asked_for_has_status_none_and_no_group_sections(db_path):
    add_n(db_path, "Serums", 5)
    data = get_insights(db_path=db_path)
    assert data["group_status"] == "none" and data["scope_group"] is None
    assert data["well_reviewed"] is None and data["price_bands"] is None


def test_groupless_products_never_appear_in_group_sections(db_path):
    add_n(db_path, "Serums", 5, rating=4.5, reviews=100, ppm=1.0)
    add(db_path, "Mini", group=None, rating=5.0, reviews=500, ppm=0.01, loves=10**6)
    data = get_insights("Serums", db_path)
    assert "Mini" not in names(data["well_reviewed"]["products"])
    assert "Mini" not in names(data["loved_products"])
    assert data["price_bands"]["eligible_products"] == 5          # the five serums; the mini is not counted


# ---------------------------------------------------------------- well reviewed, lower price per ml

def well(db_path, group="Serums"):
    return get_insights(group, db_path)["well_reviewed"]


def test_the_review_and_rating_thresholds_at_their_boundaries(db_path):
    add_n(db_path, "Filler", 0)
    add(db_path, "ok exactly", group="Serums", reviews=50, rating=4.0, ppm=1.0)
    add(db_path, "49 reviews", group="Serums", reviews=49, rating=4.9, ppm=0.1)
    add(db_path, "rating 3.9", group="Serums", reviews=500, rating=3.9, ppm=0.2)
    add(db_path, "rating 3.99", group="Serums", reviews=500, rating=3.99, ppm=0.3)
    add(db_path, "many and high", group="Serums", reviews=5000, rating=5.0, ppm=2.0)
    result = well(db_path)
    assert names(result["products"]) == ["ok exactly", "many and high"]
    assert result["qualifying_products"] == 2


def test_well_reviewed_products_are_sorted_by_price_per_ml_ascending(db_path):
    for name, ppm in [("c", 0.30), ("a", 0.10), ("b", 0.20), ("tie z", 0.25), ("Tie a", 0.25)]:
        add(db_path, name, group="Serums", ppm=ppm, reviews=80, rating=4.4)
    products = well(db_path)["products"]
    assert names(products) == ["a", "b", "Tie a", "tie z", "c"]
    assert [p["price_per_ml"] for p in products] == [0.10, 0.20, 0.25, 0.25, 0.30]
    assert set(products[0]) == {"id", "name", "brand", "price", "price_per_ml", "rating", "reviews"}


def test_well_reviewed_skips_products_missing_price_per_ml_rating_or_reviews(db_path):
    add(db_path, "no ppm", group="Serums", ppm=None, reviews=80, rating=4.5)
    add(db_path, "no rating", group="Serums", rating=None, reviews=80)
    add(db_path, "no reviews", group="Serums", rating=4.5, reviews=None)
    add(db_path, "fine", group="Serums", reviews=80, rating=4.5)
    add(db_path, "too few reviews", group="Serums", reviews=5, rating=4.5)       # fifth product: the group is offered
    result = well(db_path)
    assert names(result["products"]) == ["fine"] and result["qualifying_products"] == 1


def test_well_reviewed_list_is_ten_long_but_counts_all_that_qualify(db_path):
    for i in range(12):
        add(db_path, f"p{i:02d}", group="Serums", ppm=0.1 + i / 100, reviews=60, rating=4.2)
    result = well(db_path)
    assert len(result["products"]) == 10 and result["qualifying_products"] == 12
    assert names(result["products"])[0] == "p00" and names(result["products"])[-1] == "p09"


def test_well_reviewed_with_nobody_qualifying(db_path):
    add_n(db_path, "Serums", 5, reviews=5, rating=4.9)
    assert well(db_path) == {"qualifying_products": 0, "products": []}


# ---------------------------------------------------------------- price bands

def band_products(db_path, group, count, reviews=100, rating=None):
    """count products, price per ml 1..count, rating 3.0 + 0.1 * index unless given."""
    ids = []
    for i in range(count):
        ids.append(add(db_path, f"{group} {i:02d}", group=group, ppm=float(i + 1), reviews=reviews,
                       rating=(3.0 + i / 10) if rating is None else rating, loves=i))
    return ids


def bands(db_path, group="Serums"):
    return get_insights(group, db_path)["price_bands"]


def test_nine_products_make_three_bands_of_three(db_path):
    band_products(db_path, "Serums", 9)
    result = bands(db_path)
    assert result["enough"] and result["eligible_products"] == 9
    assert [(b["label"], b["products"]) for b in result["bands"]] == [("lower", 3), ("middle", 3), ("higher", 3)]
    # ratings 3.0 3.1 3.2 | 3.3 3.4 3.5 | 3.6 3.7 3.8 with equal reviews: the plain mean of each band
    assert [b["average_rating"] for b in result["bands"]] == pytest.approx([3.1, 3.4, 3.7])
    assert [b["reviews"] for b in result["bands"]] == [300, 300, 300]


@pytest.mark.parametrize("count, sizes", [(9, [3, 3, 3]), (10, [4, 3, 3]), (11, [4, 4, 3]), (12, [4, 4, 4]), (31, [11, 10, 10])])
def test_bands_are_as_equal_as_possible_with_the_extra_going_to_the_lower_bands(db_path, count, sizes):
    band_products(db_path, "Serums", count)
    assert [b["products"] for b in bands(db_path)["bands"]] == sizes


def test_fewer_than_nine_eligible_products_is_not_enough_data(db_path):
    band_products(db_path, "Serums", 8)
    assert bands(db_path) == {"enough": False, "eligible_products": 8, "bands": []}


def test_each_band_rating_is_weighted_by_reviews(db_path):
    # lower band: (5.0, 10 reviews) and (3.0, 90 reviews) and (4.0, 100) -> (50 + 270 + 400) / 200 = 3.6
    specs = [(1, 5.0, 10), (2, 3.0, 90), (3, 4.0, 100)] + [(i, 4.0, 20) for i in range(4, 10)]
    for ppm, rating, reviews in specs:
        add(db_path, f"p{ppm}", group="Serums", ppm=float(ppm), rating=rating, reviews=reviews)
    lower = bands(db_path)["bands"][0]
    assert lower["average_rating"] == pytest.approx(3.6) and lower["reviews"] == 200


def test_bands_follow_price_per_ml_order_not_insertion_order(db_path):
    for ppm in [9, 1, 8, 2, 7, 3, 6, 4, 5]:
        add(db_path, f"p{ppm}", group="Serums", ppm=float(ppm), rating=3.0 + ppm / 10, reviews=100)
    assert [b["average_rating"] for b in bands(db_path)["bands"]] == pytest.approx([3.2, 3.5, 3.8])   # ppm 1-3, 4-6, 7-9


def test_equal_prices_are_ordered_by_id_so_bands_stay_equal_in_size(db_path):
    for i in range(9):
        add(db_path, f"p{i}", group="Serums", ppm=1.0, rating=3.0 + i / 10, reviews=100)
    result = bands(db_path)
    assert [b["products"] for b in result["bands"]] == [3, 3, 3]
    assert [b["average_rating"] for b in result["bands"]] == pytest.approx([3.1, 3.4, 3.7])   # insertion (id) order


def test_only_products_with_enough_reviews_a_rating_and_a_price_per_ml_count_for_bands(db_path):
    band_products(db_path, "Serums", 9, reviews=10)                                  # exactly 10: counts
    add(db_path, "9 reviews", group="Serums", ppm=0.5, rating=5.0, reviews=9)
    add(db_path, "no rating", group="Serums", ppm=0.5, rating=None, reviews=500)
    add(db_path, "no reviews", group="Serums", ppm=0.5, rating=5.0, reviews=None)
    add(db_path, "no ppm", group="Serums", ppm=None, rating=5.0, reviews=500)
    result = bands(db_path)
    assert result["eligible_products"] == 9 and [b["products"] for b in result["bands"]] == [3, 3, 3]


def test_nine_reviews_is_not_enough_for_the_bands(db_path):
    band_products(db_path, "Serums", 9, reviews=9)
    assert bands(db_path)["enough"] is False


# ---------------------------------------------------------------- ingredients

def test_ingredient_shares_are_percentages_of_products_with_a_list(db_path):
    for i in range(4):
        add(db_path, f"p{i}", ingredients=["Water", "Glycerin"] + (["Squalane"] if i == 0 else []))
    add(db_path, "p4", ingredients=["Water"])
    add(db_path, "no list", ingredients=[])
    ing = get_insights(db_path=db_path)["ingredients"]
    assert ing["products"] == 5
    assert ing["top"] == [
        {"name": "Glycerin", "products": 4, "share_percent": pytest.approx(80.0)},
        {"name": "Squalane", "products": 1, "share_percent": pytest.approx(20.0)},
    ]


def test_water_is_reported_separately_matched_whole_and_ignoring_case(db_path):
    add(db_path, "a", ingredients=["water", "Rose Water"])
    add(db_path, "b", ingredients=["Water", "Purified Water", "Rose Water"])
    ing = get_insights(db_path=db_path)["ingredients"]
    assert ing["water"] == {"products": 2, "share_percent": pytest.approx(100.0)}
    assert [(i["name"], i["products"]) for i in ing["top"]] == [("Rose Water", 2), ("Purified Water", 1)]


def test_the_ingredient_ranking_is_the_top_ten_with_ties_by_name(db_path):
    add(db_path, "p", ingredients=[f"Ingredient {c}" for c in "LKJIHGFEDCBA"])
    top = get_insights(db_path=db_path)["ingredients"]["top"]
    assert names(top) == [f"Ingredient {c}" for c in "ABCDEFGHIJ"]


def test_a_groups_ingredients_come_from_that_group_only(db_path):
    add_n(db_path, "Serums", 5, ingredients=["Water", "Glycerin"])
    add_n(db_path, "Creams", 5, ingredients=["Water", "Niacinamide"])
    add(db_path, "mini", group=None, ingredients=["Water", "Squalane"])
    ing = get_insights("Serums", db_path)["ingredients"]
    assert ing["products"] == 5 and names(ing["top"]) == ["Glycerin"]
    assert ing["water"] == {"products": 5, "share_percent": pytest.approx(100.0)}
    assert get_insights(db_path=db_path)["ingredients"]["products"] == 11


# ---------------------------------------------------------------- empty, tiny, missing data

def test_an_empty_database_gives_complete_empty_data(db_path):
    data = get_insights(db_path=db_path)
    assert data["overview"] == {"products": 0, "brands": 0, "groups": 0, "ungrouped_products": 0}
    assert data["brands"] == [] and data["loved_products"] == [] and data["selector_groups"] == []
    assert data["ingredients"]["top"] == [] and data["ingredients"]["water"] == {"products": 0, "share_percent": None}
    assert data["well_reviewed"] is None and data["price_bands"] is None
    assert get_insights("Serums", db_path)["group_status"] == "unavailable"


def test_a_database_with_one_product_does_not_crash(db_path):
    add(db_path, "Only", ingredients=["Water"])
    data = get_insights(db_path=db_path)
    assert data["overview"]["products"] == 1 and len(data["brands"]) == 1 and len(data["loved_products"]) == 1
    assert data["selector_groups"] == []


def test_products_with_no_popularity_data_at_all_do_not_crash_anything(db_path):
    add_n(db_path, "Serums", 12, loves=None, rating=None, reviews=None, ppm=None)
    for group in (None, "Serums"):
        data = get_insights(group, db_path)
        assert data["brands"] == [] and data["loved_products"] == []
    data = get_insights("Serums", db_path)
    assert data["well_reviewed"] == {"qualifying_products": 0, "products": []}
    assert data["price_bands"] == {"enough": False, "eligible_products": 0, "bands": []}


def test_an_older_database_without_the_new_columns_still_works(tmp_path):
    path = str(tmp_path / "old.db")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,"
                     " category TEXT, price REAL, size_text TEXT, size_ml REAL, price_per_ml REAL,"
                     " ingredients_text TEXT)")
        conn.execute("INSERT INTO products (name, brand, price, price_per_ml) VALUES ('Old', 'B', 10, 0.1)")
    data = get_insights(db_path=path)
    assert data["overview"]["products"] == 1 and data["brands"] == [] and data["loved_products"] == []


def test_the_data_is_plain_numbers_and_names(db_path):
    add_n(db_path, "Serums", 12, ppm=1.0, ingredients=["Water", "Glycerin"])
    data = get_insights("Serums", db_path)

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                yield from walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                yield from walk(v)
        else:
            yield value

    assert all(v is None or isinstance(v, (int, float, str)) for v in walk(data))
    assert not any(isinstance(v, str) and ("$" in v or "₹" in v or "<" in v) for v in walk(data))
