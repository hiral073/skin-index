import pandas as pd
import pytest

from database.db import init_db, seed_db
from database.load_data import (
    BAD_SIZE, DUPLICATE, MULTIPACK, NO_INGREDIENTS, NO_PRICE, NO_SIZE,
    NOT_SKINCARE, WEIGHT_SIZE, clean_products, load_products, parse_size_ml,
    split_ingredients, table_counts,
)


@pytest.mark.parametrize("text, expected", [
    ("0.5 oz/ 15 mL", 15.0),
    ("3.4 oz / 100 ml", 100.0),
    ("0.50 oz/ 15mL", 15.0),
    ("1.7 oz/ 50.28 mL", 50.28),
    ("1 oz", 29.57),
    (".5 oz", 14.79),
])
def test_parse_size_ml_readable(text, expected):
    assert parse_size_ml(text) == (pytest.approx(expected), None)


@pytest.mark.parametrize("text, reason", [
    (None, NO_SIZE),
    (float("nan"), NO_SIZE),
    ("5 oz/ 14 g", WEIGHT_SIZE),
    ("2 x 1.7 oz / 50 mL", MULTIPACK),
    ("60 Capsules", BAD_SIZE),
    ("1 Mask", BAD_SIZE),
    ("0 mL", BAD_SIZE),
])
def test_parse_size_ml_unreadable(text, reason):
    assert parse_size_ml(text) == (None, reason)


def test_split_ingredients_joins_wrapped_list_elements():
    raw = "['Water, Glycerin, Polyacrylate', 'Crosspolymer-6, Squalane.']"
    assert split_ingredients(raw) == [
        "Water", "Glycerin", "Polyacrylate Crosspolymer-6", "Squalane",
    ]


def test_split_ingredients_cleans_and_dedupes():
    raw = "['Glycerin,  Niacinamide**, , glycerin, Citric Acid.']"
    assert split_ingredients(raw) == ["Glycerin", "Niacinamide", "Citric Acid"]


@pytest.mark.parametrize("water", [
    "Aqua/Water/Eau", "Water/Aqua/Eau", "Water (Aqua)", "Aqua", "Eau", "water",
])
def test_split_ingredients_folds_water_variants(water):
    assert split_ingredients(f"['{water}, Glycerin']") == ["Water", "Glycerin"]


def test_split_ingredients_keeps_non_water_names():
    assert split_ingredients("['Rose Water, Aqua']") == ["Rose Water", "Water"]


def test_split_ingredients_empty_or_missing():
    assert split_ingredients(float("nan")) == []
    assert split_ingredients("[]") == []


def sample_df():
    cols = ["product_name", "brand_name", "primary_category", "secondary_category",
            "price_usd", "size", "ingredients"]
    rows = [
        ("Good Cream", "BrandA", "Skincare", "Moisturizers", 30.0, "1 oz/ 30 mL", "['Water, Glycerin']"),
        ("Good Cream", "BrandA", "Skincare", "Moisturizers", 30.0, "1 oz / 30 mL", "['Water, Glycerin']"),
        ("Good Cream", "BrandA", "Skincare", "Moisturizers", 50.0, "2 oz/ 60 mL", "['Water, Glycerin']"),
        ("Lipstick", "BrandB", "Makeup", "Lip", 20.0, "0.1 oz/ 3 mL", "['Wax']"),
        ("No Price", "BrandA", "Skincare", "Serums", None, "1 oz/ 30 mL", "['Water']"),
        ("No Size", "BrandA", "Skincare", "Serums", 10.0, None, "['Water']"),
        ("Mask", "BrandA", "Skincare", "Masks", 10.0, "1 Mask", "['Water']"),
        ("No Ings", "BrandA", "Skincare", "Serums", 10.0, "1 oz/ 30 mL", None),
    ]
    return pd.DataFrame(rows, columns=cols)


def test_clean_products_keeps_valid_and_counts_drops():
    products, drops = clean_products(sample_df())
    assert [(p["name"], p["size_ml"]) for p in products] == [
        ("Good Cream", 30.0), ("Good Cream", 60.0),
    ]
    assert products[0]["category"] == "Moisturizers"
    assert products[0]["price_per_ml"] == pytest.approx(1.0)
    assert dict(drops) == {
        NOT_SKINCARE: 1, NO_PRICE: 1, NO_SIZE: 1, BAD_SIZE: 1,
        NO_INGREDIENTS: 1, DUPLICATE: 1,
    }


def test_load_products_replaces_existing_rows(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    seed_db(db)
    products, _ = clean_products(sample_df())
    load_products(products, db)
    # 2 products; ingredients Water + Glycerin shared; 2 labels x 2 ingredients
    assert table_counts(db) == {
        "products": 2, "ingredients": 2, "product_ingredients": 4,
    }
