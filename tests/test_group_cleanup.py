from collections import Counter
import re
from contextlib import closing

import pandas as pd
import pytest

from content.compare_groups import GROUP_MERGES, HIDDEN_GROUPS
from database.db import get_db, init_db
from database.load_data import apply_group_cleanup, clean_products, load_products
from database.services import compare_products, get_insights, list_group_ingredients, list_groups

NIACINAMIDE = "['Water', 'Niacinamide']"
VITAMIN_C = "['Water', 'Ascorbic Acid']"

# (name, second level, third level, ingredients)
ROWS = [
    ("Shield A", "Sunscreen", "Face Sunscreen", NIACINAMIDE),
    ("Shield B", "Sunscreen", "Face Sunscreen", NIACINAMIDE),
    ("Shield C", "Sunscreen", "Face Sunscreen", VITAMIN_C),
    ("Shield D", "Sunscreen", "Face Sunscreen", NIACINAMIDE),
    ("Shield E", "Sunscreen", "Face Sunscreen", NIACINAMIDE),
    ("Body Mist SPF", "Sunscreen", "Body Sunscreen", NIACINAMIDE),
    ("Body Oil SPF", "Sunscreen", "Body Sunscreen", NIACINAMIDE),
    ("Shield Plain", "Sunscreen", None, NIACINAMIDE),
    ("Wash One", "Cleansers", "Face Wash & Cleansers", NIACINAMIDE),
    ("Wash No Level", "Cleansers", None, NIACINAMIDE),
    ("Balm One", "Cleansers", "Makeup Removers", NIACINAMIDE),
    ("Balm Two", "Cleansers", "Makeup Removers", NIACINAMIDE),
    ("Night Cream", "Moisturizers", "Night Creams", NIACINAMIDE),
    ("Day Cream", "Moisturizers", "Moisturizers", NIACINAMIDE),
    ("Eye Cream", "Eye Care", "Eye Creams & Treatments", NIACINAMIDE),
    ("Eye Mask", "Eye Care", "Eye Masks", NIACINAMIDE),
    ("Tan Face", "Self Tanners", "For Face", NIACINAMIDE),
    ("Tan Body", "Self Tanners", "For Body", NIACINAMIDE),
    ("BB One", "Moisturizers", "BB & CC Creams", NIACINAMIDE),
    ("BB Two", "Moisturizers", "BB & CC Creams", NIACINAMIDE),
    ("Serum One", "Treatments", "Face Serums", NIACINAMIDE),
    ("Serum Two", "Treatments", "Face Serums", NIACINAMIDE),
    ("Bath Soak", "Wellness", "Holistic Wellness", NIACINAMIDE),
    ("Whitening Pen", "High Tech Tools", "Teeth Whitening", NIACINAMIDE),
    ("Neck Roller", "High Tech Tools", "Anti-Aging", NIACINAMIDE),
    ("Mini Mask", "Shop by Concern", "Anti-Aging", NIACINAMIDE),
    ("Tiny Serum", "Mini Size", None, NIACINAMIDE),
]

EXPECTED_GROUPS = {
    "Sunscreen › Face": 5,
    "Sunscreen › Body": 2,
    "Sunscreen": 1,                  # no third level: no subcategory
    "Face Wash & Cleansers": 2,
    "Makeup Removers": 2,
    "Moisturizers": 1,
    "Night Creams": 1,               # stays a group of its own
    "Eye Creams & Treatments": 2,
    "Self Tanners › Face": 1,
    "Self Tanners › Body": 1,
    "BB & CC Creams": 2,
    "Face Serums": 2,
    None: 5,        # Bath Soak, Whitening Pen, Neck Roller, Mini Mask (hidden) and Tiny Serum (mini)
}


def frame(rows):
    cols = ["product_name", "brand_name", "primary_category", "secondary_category",
            "tertiary_category", "price_usd", "size", "ingredients"]
    df = pd.DataFrame(
        [(n, "Brand", "Skincare", s, t, 10.0, f"{i + 1} oz/ {30 + i} mL", ing)
         for i, (n, s, t, ing) in enumerate(rows)],
        columns=cols,
    )
    return df


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    products, _ = clean_products(frame(ROWS))
    load_products(products, path)
    return path


def ids(db_path):
    with closing(get_db(db_path)) as conn:
        return {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM products")}


# ------------------------------------------------------------------ the map

@pytest.mark.parametrize("old, new", [
    ("Face Sunscreen", "Sunscreen › Face"), ("Body Sunscreen", "Sunscreen › Body"), ("Sunscreen", "Sunscreen"),
    ("Cleansers", "Face Wash & Cleansers"), ("Night Creams", "Night Creams"),
    ("Eye Masks", "Eye Creams & Treatments"),
    ("For Face", "Self Tanners › Face"), ("For Body", "Self Tanners › Body"),
    ("Makeup Removers", "Makeup Removers"), ("BB & CC Creams", "BB & CC Creams"),   # kept apart
    ("Face Serums", "Face Serums"),
])
def test_apply_group_cleanup_merges_and_leaves_other_groups_alone(old, new):
    assert apply_group_cleanup(old, "third level") == (new, "third level")


@pytest.mark.parametrize("old", [
    "Shop by Concern › Anti-Aging", "High Tech Tools › Anti-Aging", "Holistic Wellness", "Teeth Whitening",
])
def test_apply_group_cleanup_hides_groups_that_are_not_product_types(old):
    assert apply_group_cleanup(old, "third level") == (None, None)


def test_a_product_with_no_group_stays_without_one():
    assert apply_group_cleanup(None, None) == (None, None)


def test_the_map_is_consistent():
    assert not set(GROUP_MERGES) & HIDDEN_GROUPS                 # a group is merged or hidden, not both
    assert not set(GROUP_MERGES.values()) & set(GROUP_MERGES)    # no chains: new names are final
    assert not set(GROUP_MERGES.values()) & HIDDEN_GROUPS
    assert "Makeup Removers" not in GROUP_MERGES and "BB & CC Creams" not in GROUP_MERGES


# ------------------------------------------------------------------ the loaded data

def test_merged_groups_have_the_right_counts_and_no_product_is_lost(db_path):
    with closing(get_db(db_path)) as conn:
        counts = {r[0]: r[1] for r in conn.execute("SELECT compare_group, COUNT(*) FROM products GROUP BY 1")}
    assert counts == EXPECTED_GROUPS
    assert sum(counts.values()) == len(ROWS)


def test_unmapped_products_keep_their_group_and_minis_still_have_none(db_path):
    with closing(get_db(db_path)) as conn:
        stored = {r["name"]: r["compare_group"] for r in conn.execute("SELECT name, compare_group FROM products")}
    assert stored["Serum One"] == "Face Serums"
    assert stored["Balm One"] == stored["Balm Two"] == "Makeup Removers"
    assert stored["BB One"] == "BB & CC Creams"
    assert stored["Tiny Serum"] is None
    assert [n for n, g in stored.items() if g is None] == [
        "Bath Soak", "Whitening Pen", "Neck Roller", "Mini Mask", "Tiny Serum",
    ]


def test_the_original_category_column_is_untouched(db_path):
    with closing(get_db(db_path)) as conn:
        stored = {r["name"]: r["category"] for r in conn.execute("SELECT name, category FROM products")}
    assert stored["Body Mist SPF"] == "Sunscreen" and stored["Shield A"] == "Sunscreen"
    assert stored["Wash No Level"] == "Cleansers"
    assert stored["Night Cream"] == "Moisturizers" and stored["Eye Mask"] == "Eye Care"
    assert stored["Tan Face"] == stored["Tan Body"] == "Self Tanners"
    assert stored["Neck Roller"] == "High Tech Tools" and stored["Bath Soak"] == "Wellness"
    assert stored["Tiny Serum"] == "Mini Size"


def test_reloading_gives_the_same_result_and_keeps_the_exchange_rates(db_path):
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                     " VALUES ('2026-11-12', 'USD', 'INR', 84.5, '2026-11-13')")
        before = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    products, _ = clean_products(frame(ROWS))
    load_products(products, db_path)
    with closing(get_db(db_path)) as conn:
        counts = {r[0]: r[1] for r in conn.execute("SELECT compare_group, COUNT(*) FROM products GROUP BY 1")}
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == before == len(ROWS)
        assert conn.execute("SELECT rate FROM exchange_rates").fetchall()[0][0] == 84.5
    assert counts == EXPECTED_GROUPS


def test_the_cleanup_drops_no_product_in_clean_products():
    products, drops = clean_products(frame(ROWS))
    assert len(products) == len(ROWS) and not drops.get("duplicate product")
    assert Counter(p["compare_group"] for p in products) == Counter(EXPECTED_GROUPS)
    assert Counter(p["raw_group"] for p in products)["Face Sunscreen"] == 5      # the old name stays on record


# ------------------------------------------------------------------ pages and services

def test_the_compare_picker_lists_the_new_groups_only(db_path):
    names = [g["name"] for g in list_groups(db_path)]          # two or more products each
    assert names == sorted(EXPECTED_GROUPS.keys() - {None, "Sunscreen", "Moisturizers", "Self Tanners › Face",
                                                    "Self Tanners › Body", "Night Creams"}, key=str.casefold)
    for old in ("Face Sunscreen", "Body Sunscreen", "Eye Masks", "For Face", "For Body",
                "Cleansers", "Holistic Wellness", "Teeth Whitening"):
        assert old not in names


def test_insights_selector_uses_the_new_groups_and_keeps_the_five_product_rule(db_path):
    selector = {g["name"]: g["products"] for g in get_insights(None, db_path)["selector_groups"]}
    assert selector == {"Sunscreen › Face": 5}      # only this subcategory reaches 5
    assert get_insights("Sunscreen › Face", db_path)["group_status"] == "ok"
    assert get_insights("Sunscreen", db_path)["group_status"] == "unavailable"     # the parent is not a group
    assert get_insights("Face Sunscreen", db_path)["group_status"] == "unavailable"
    assert get_insights("Makeup Removers", db_path)["group_status"] == "unavailable"   # 2 products


def test_products_in_the_same_cleaned_group_can_be_compared_through_a_shared_main_ingredient(db_path):
    p = ids(db_path)
    for a, b, group in [("Shield A", "Shield B", "Sunscreen › Face"),
                        ("Body Mist SPF", "Body Oil SPF", "Sunscreen › Body"),
                        ("Wash One", "Wash No Level", "Face Wash & Cleansers"),
                        ("Eye Cream", "Eye Mask", "Eye Creams & Treatments")]:
        result = compare_products(p[a], p[b], db_path)
        assert result["status"] == "ok" and result["comparable"], (a, b)
        assert result["a_group"] == result["b_group"] == group


def test_compare_still_needs_the_same_group_and_the_same_main_ingredient(db_path):
    p = ids(db_path)
    same_group_other_ingredient = compare_products(p["Shield A"], p["Shield C"], db_path)
    assert same_group_other_ingredient["status"] == "different_ingredients"
    assert not same_group_other_ingredient["comparable"]
    for a, b in [("Shield A", "Body Mist SPF"),          # subcategories of one group are not compared together
                 ("Tan Face", "Tan Body"), ("Night Cream", "Day Cream"), ("Shield A", "Shield Plain")]:
        result = compare_products(p[a], p[b], db_path)
        assert result["status"] == "different_groups" and not result["comparable"], (a, b)
    other_group = compare_products(p["Balm One"], p["Wash One"], db_path)          # kept apart
    assert other_group["status"] == "different_groups" and not other_group["comparable"]
    assert compare_products(p["BB One"], p["Day Cream"], db_path)["status"] == "different_groups"
    hidden = compare_products(p["Bath Soak"], p["Whitening Pen"], db_path)
    assert hidden["status"] == "no_group" and not hidden["comparable"]
    assert compare_products(p["Tiny Serum"], p["Serum One"], db_path)["status"] == "no_group"


def test_the_main_ingredient_choices_follow_the_new_group(db_path):
    shared = {g["key"]: g["products"] for g in list_group_ingredients("Sunscreen › Face", db_path)}
    assert shared == {"niacinamide": 4, "vitamin-c": 1}


# ------------------------------------------------------------------ the dropdowns (UI)

@pytest.fixture
def loaded(app):
    products, _ = clean_products(frame(ROWS))
    load_products(products, app.config["DATABASE"])
    return app


def option_values(html, select_id):
    block = html.split(f'id="{select_id}"', 1)[1].split("</select>", 1)[0]
    return block


def test_the_compare_category_dropdown_nests_subcategories_under_their_parent(loaded, client):
    html = client.get("/compare").get_data(as_text=True)
    block = option_values(html, "group")
    assert '<optgroup label="Sunscreen">' in block
    face = '<option value="Sunscreen › Face" >Face (5)</option>'
    body = '<option value="Sunscreen › Body" >Body (2)</option>'
    assert face in block and body in block
    assert block.index('<optgroup label="Sunscreen">') < block.index(face) < block.index("</optgroup>")
    assert '<option value="Face Wash &amp; Cleansers" >Face Wash &amp; Cleansers (2)</option>' in block
    assert "All Sunscreen" not in block                  # a comparison needs one subcategory


def test_the_compare_page_works_with_a_subcategory_chosen(loaded, client):
    html = client.get("/compare", query_string={"group": "Sunscreen › Face"}).get_data(as_text=True)
    assert '<option value="Sunscreen › Face" selected>Face (5)</option>' in html
    assert "niacinamide (4 products)" in html


def test_the_insights_selector_nests_subcategories_too(loaded, client):
    html = client.get("/insights", query_string={"group": "Sunscreen › Face"}).get_data(as_text=True)
    block = option_values(html, "group")
    assert '<optgroup label="Sunscreen">' in block
    assert '<option value="Sunscreen › Face" selected>Face (5)</option>' in block
    assert "Sunscreen › Face" in html.split("</select>", 1)[1]          # the headings name the full group


def test_the_products_dropdown_has_all_and_each_subcategory(loaded, client):
    html = client.get("/products").get_data(as_text=True)
    block = option_values(html.replace('aria-label="Category"', 'id="category" aria-label="Category"'), "category")
    section = block.split('<optgroup label="Sunscreen">', 1)[1].split("</optgroup>", 1)[0]
    assert re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)<', section) == [
        ("Sunscreen", "All Sunscreen"), ("Sunscreen › Body", "Body"), ("Sunscreen › Face", "Face"),
    ]
    assert '<optgroup label="Self Tanners">' in block
    assert '<option value="Night Creams" >Night Creams</option>' in block   # a separate group again


def test_the_products_filter_matches_a_parent_with_its_subcategories_and_a_subcategory_alone(loaded, client):
    def names(category):
        html = client.get("/products", query_string={"category": category}).get_data(as_text=True)
        return {n for n, *_ in ROWS if f">{n}</a>" in html}

    face = {"Shield A", "Shield B", "Shield C", "Shield D", "Shield E"}
    assert names("Sunscreen") == face | {"Body Mist SPF", "Body Oil SPF", "Shield Plain"}
    assert names("Sunscreen › Face") == face
    assert names("Sunscreen › Body") == {"Body Mist SPF", "Body Oil SPF"}
    assert names("Self Tanners") == {"Tan Face", "Tan Body"}
    assert names("Night Creams") == {"Night Cream"}
    assert names("Moisturizers") == {"Day Cream"}
    assert names("Sunscreen › Fa") == set() and names("Sun") == set()
    assert names("%") == set() and names("Sunscreen › %") == set()      # LIKE wildcards are plain text
