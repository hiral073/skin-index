"""Ingredient names are matched by their text only: trimming, capital letters and Water/Aqua/Eau (Step 12a was dropped)."""
from contextlib import closing

import pandas as pd
import pytest

from database.db import get_db, init_db
from database.load_data import clean_products, load_products
from database.services import compare_products


def load(db_path, lists):
    """Load one 'Face Serums' product per ingredient list (ids in the order given); returns the ids."""
    cols = ["product_name", "brand_name", "primary_category", "secondary_category",
            "tertiary_category", "price_usd", "size", "ingredients"]
    df = pd.DataFrame(
        [(f"Niacinamide Serum {i}", "B", "Skincare", "Treatments", "Face Serums", 10.0,
          f"{i + 1} oz/ {30 + i} mL", str([", ".join(ingredients)])) for i, ingredients in enumerate(lists)],
        columns=cols,
    )
    init_db(db_path)
    products, _ = clean_products(df)
    load_products(products, db_path)
    with closing(get_db(db_path)) as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM products ORDER BY id")]


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_a_different_case_and_stray_spaces_or_dots_are_the_same_ingredient(db_path):
    a, b = load(db_path, [["Niacinamide", "Glycerin", "Sodium  Benzoate"],
                          ["NIACINAMIDE ", "glycerin.", "sodium benzoate"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert (ing["shared_count"], ing["only_a_count"], ing["only_b_count"]) == (3, 0, 0)


@pytest.mark.parametrize("one, other", [
    ("Glycerin", "Glycerine"),                          # a close spelling
    ("Tocopherol Acetate", "Tocopheryl Acetate"),       # probably the same, still not merged
    ("Sodium Hyaluronate", "Hyaluronic Acid"),
    ("Retinol", "Retinal"),
    ("Glyceryl Stearate", "Glyceryl Stearate SE"),
    ("Caprylic/Capric Triglyceride", "Caprylic/Capric Triglycerides"),
    ("Phenoxyethanol", "Phenoxy Ethanol"),              # a missing space is not repaired
])
def test_similar_spellings_are_never_merged(db_path, one, other):
    a, b = load(db_path, [["Niacinamide", one], ["Niacinamide", other]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Niacinamide"]
    assert ing["only_a"] == [one] and ing["only_b"] == [other]


def test_only_the_exact_text_is_compared(db_path):
    a, b = load(db_path, [["Niacinamide", "Zinc PCA", "Citric Acid"], ["Niacinamide", "Zinc Pca", "Citric Acid 1"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Niacinamide", "Zinc PCA"]            # case only
    assert ing["only_a"] == ["Citric Acid"] and ing["only_b"] == ["Citric Acid 1"]


@pytest.mark.parametrize("written", ["Aqua", "AQUA", "Eau", "Water (Aqua)", "Aqua/Water/Eau", "water"])
def test_water_aqua_and_eau_count_as_the_same_ingredient(db_path, written):
    a, b = load(db_path, [["Water", "Niacinamide"], [written, "Niacinamide"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Water", "Niacinamide"] and not ing["only_a"] and not ing["only_b"]


@pytest.mark.parametrize("other", ["Purified Water", "Deionized Water", "Rose Water", "Aqua Complex"])
def test_no_other_water_name_is_matched(db_path, other):
    a, b = load(db_path, [["Water", "Niacinamide"], [other, "Niacinamide"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Niacinamide"] and ing["only_a"] == ["Water"] and ing["only_b"] == [other]


@pytest.mark.parametrize("written", ["Parfum", "PARFUM", "Fragrance", "Fragrance (Parfum)", "Parfum/Fragrance"])
def test_fragrance_and_parfum_count_as_the_same_ingredient(db_path, written):
    a, b = load(db_path, [["Fragrance", "Niacinamide"], [written, "Niacinamide"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Fragrance", "Niacinamide"] and not ing["only_a"] and not ing["only_b"]


@pytest.mark.parametrize("other", ["Natural Fragrance", "Fragrance Mix", "Perfume", "Fragrances"])
def test_no_other_fragrance_name_is_matched(db_path, other):
    a, b = load(db_path, [["Fragrance", "Niacinamide"], [other, "Niacinamide"]])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Niacinamide"] and ing["only_a"] == ["Fragrance"] and ing["only_b"] == [other]

