import re
from contextlib import closing

import pandas as pd
import pytest

from database.db import get_db, init_db, seed_db
from database.load_data import (
    AMBIGUOUS, BAD_SIZE, DUPLICATE, EXTRACTED, GROUP_SEPARATOR, IGNORED_COLON,
    IGNORED_VALUE, LEADING, MERGED, MULTIPACK, NO_INGREDIENTS, NO_PRICE, NO_SIZE,
    NOT_SKINCARE, PAREN, PLAIN, SECOND_LEVEL, THIRD_LEVEL, TRAILING, WEIGHT_SIZE,
    StrengthEvent, StrengthReport, ambiguous_subcategories, clean_products, compare_group,
    load_products, main, parse_ingredients, parse_size_ml, parse_strength, pick_examples,
    split_ingredients, strengths_apply, table_counts,
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


@pytest.mark.parametrize("piece, name, percent, fmt", [
    ("Salicylic Acid 2.0%", "Salicylic Acid", 2.0, TRAILING),
    ("Salicylic Acid 2%", "Salicylic Acid", 2.0, TRAILING),
    ("L-Ascorbic Acid (Vitamin C) 15 %", "L-Ascorbic Acid (Vitamin C)", 15.0, TRAILING),
    ("Hamamelis Virginiana (Witch Hazel) Extract 1%", "Hamamelis Virginiana (Witch Hazel) Extract", 1.0, TRAILING),
    ("Ceramide NP .5%", "Ceramide NP", 0.5, TRAILING),
    ("Niacinamide 99.9%", "Niacinamide", 99.9, TRAILING),
    ("Zinc Oxide (12.025%)", "Zinc Oxide", 12.025, PAREN),
    ("Ceramide Np(0.2%)", "Ceramide Np", 0.2, PAREN),
    ("Zinc Oxide ( 6.5 % )", "Zinc Oxide", 6.5, PAREN),
    ("3% Procapil", "Procapil", 3.0, LEADING),
    ("10 % Glycolic Acid", "Glycolic Acid", 10.0, LEADING),
])
def test_parse_strength_reads_each_clear_format(piece, name, percent, fmt):
    assert parse_strength(piece) == (name, percent, EXTRACTED, fmt)


@pytest.mark.parametrize("piece", [
    "100% Natural Coconut Soy Wax", "100% Unrefined Marula Oil", "Parfum 100%",
    "0% Alcohol", "Aloe Vera 0%", "Zinc Oxide 150%",
])
def test_parse_strength_ignores_values_of_100_or_more_or_0(piece):
    result = parse_strength(piece)
    assert result.status == IGNORED_VALUE
    assert result.name == piece and result.percent is None   # name left exactly as it was


@pytest.mark.parametrize("piece", [
    "Alpha-Isomethyl Ionone : 0.0408%", "Benzyl Benzoate: 0.04548%", "Linalool :0.5%",
])
def test_parse_strength_ignores_colon_style_compounds(piece):
    result = parse_strength(piece)
    assert result.status == IGNORED_COLON
    assert result.name == piece and result.percent is None


@pytest.mark.parametrize("piece", [
    "Avobenzone 3% Sunscreen",                                   # a word after the %
    "Zinc Oxide 6.90%Water",                                     # glued to the next ingredient
    "Avobenzone 1.75% Homosalate 5% Octisalate 2% Octocrylene 5%",   # several in one piece
    "Salicylic Acid 2% (BHA)",                                   # % in the middle
    "Salicylic Acid (1.5%) Water (Aqua)",
    "Sucralose (less than 1%)",                                  # a limit, not a strength
    "Glycerin (only 0.005% Glycerin)",
    "Niacinamide5%",
    "3%",                                                        # no name at all
    "Octocrylene 7%: Sunscreens",
    "Zinc Oxide 13.20 - 14.00 %",                                # a range, not one strength
    "Zinc Oxide 13.20 to 14.00%",
    "Zinc Oxide 5 and 10%",
    "Phenoxyethanol. -Five Percent Benzoyl Peroxide: Helps diminish blemishes. Benzoyl Peroxide 5%",
    "Active Ingredients: Salicylic Acid 2%",                     # a heading run into the name
])
def test_parse_strength_leaves_ambiguous_text_unchanged(piece):
    result = parse_strength(piece)
    assert result.status == AMBIGUOUS
    assert result.name == piece and result.percent is None


def test_parse_strength_plain_piece():
    assert parse_strength("Glycerin") == ("Glycerin", None, PLAIN, None)


@pytest.mark.parametrize("primary, secondary, expected", [
    ("Skincare", "Treatments", True),
    ("Skincare", "Sunscreen", True),
    ("Skincare", None, True),
    ("Skincare", "Value & Gift Sets", False),
    ("Skincare", "Mini Size", False),
    ("Makeup", "Foundation", False),
    ("Fragrance", "Women", False),
])
def test_strengths_apply_only_to_regular_skincare(primary, secondary, expected):
    assert strengths_apply(primary, secondary) is expected


def test_parse_ingredients_extracts_cleans_and_aliases():
    raw = "['Water (Aqua) 70%, Salicylic Acid 2.0%, Zinc Oxide (12.025%), 3% Procapil, Glycerin']"
    items, _ = parse_ingredients(raw, extract_strength=True)
    assert items == [
        ("Water", 70.0), ("Salicylic Acid", 2.0), ("Zinc Oxide", 12.025),
        ("Procapil", 3.0), ("Glycerin", None),
    ]


def test_parse_ingredients_without_extraction_leaves_names_exactly():
    raw = "['Water, Salicylic Acid 2.0%, Zinc Oxide (12.025%), 3% Procapil']"
    items, events = parse_ingredients(raw, extract_strength=False)
    assert items == [
        ("Water", None), ("Salicylic Acid 2.0%", None), ("Zinc Oxide (12.025%)", None),
        ("3% Procapil", None),
    ]
    assert events == []


def test_parse_ingredients_ignored_and_ambiguous_names_stay_as_written():
    raw = "['100% Natural Wax, Alpha Ionone : 0.04%, Avobenzone 3% Sunscreen, Glycerin 5%']"
    items, events = parse_ingredients(raw, extract_strength=True)
    assert items == [
        ("100% Natural Wax", None), ("Alpha Ionone : 0.04%", None),
        ("Avobenzone 3% Sunscreen", None), ("Glycerin", 5.0),
    ]
    assert [e.status for e in events] == [IGNORED_VALUE, IGNORED_COLON, AMBIGUOUS, EXTRACTED]


def test_same_ingredient_with_and_without_percent_is_one_name():
    with_pct, _ = parse_ingredients("['Zinc Oxide 20%, Water']", extract_strength=True)
    without, _ = parse_ingredients("['Zinc Oxide, Water']", extract_strength=True)
    assert [n for n, _ in with_pct] == [n for n, _ in without] == ["Zinc Oxide", "Water"]


def test_duplicate_name_keeps_first_position_and_attaches_the_stated_percent():
    items, events = parse_ingredients(
        "['Zinc Oxide, Titanium Dioxide, Water, Zinc Oxide 15.5%']", extract_strength=True
    )
    assert items == [("Zinc Oxide", 15.5), ("Titanium Dioxide", None), ("Water", None)]
    assert [e.status for e in events] == [EXTRACTED, MERGED]


def test_duplicate_name_keeps_the_earlier_percent_and_drops_a_plain_repeat():
    items, events = parse_ingredients(
        "['Ferulic Acid 0.5%, Water, Ferulic Acid']", extract_strength=True
    )
    assert items == [("Ferulic Acid", 0.5), ("Water", None)]
    assert [e.status for e in events] == [EXTRACTED]


def test_duplicate_name_with_two_percents_keeps_the_first_and_reports_the_second():
    items, events = parse_ingredients("['Zinc Oxide 10%, Water, Zinc Oxide 15%']", extract_strength=True)
    assert items == [("Zinc Oxide", 10.0), ("Water", None)]
    assert events[-1].status == MERGED and events[-1].percent == 15.0


def strength_df():
    cols = ["product_name", "brand_name", "primary_category", "secondary_category",
            "price_usd", "size", "ingredients"]
    rows = [
        ("Acne Gel", "BrandA", "Skincare", "Treatments", 20.0, "1 oz/ 30 mL",
         "['Water, Salicylic Acid 2.0%, Zinc Oxide (12.025%), Avobenzone 3% Sunscreen']"),
        ("Gift Kit", "BrandA", "Skincare", "Value & Gift Sets", 40.0, "2 oz/ 60 mL",
         "['Water, Salicylic Acid 2.0%']"),
        ("Tiny Gel", "BrandA", "Skincare", "Mini Size", 8.0, "0.5 oz/ 15 mL",
         "['Water, Salicylic Acid 2.0%']"),
        ("Scented Candle", "BrandB", "Fragrance", "Candles", 30.0, "6 oz/ 177 mL",
         "['Wax, Cotton Wick 100%, Fragrance 5%']"),
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["tertiary_category"] = ["Face Serums", None, None, "Candles"]
    return df


def test_clean_products_extracts_only_for_regular_skincare():
    report = StrengthReport()
    products, drops = clean_products(strength_df(), report)
    by_name = {p["name"]: p for p in products}
    assert set(by_name) == {"Acne Gel", "Gift Kit", "Tiny Gel"}      # the candle is not Skincare
    assert by_name["Acne Gel"]["ingredients"] == [
        "Water", "Salicylic Acid", "Zinc Oxide", "Avobenzone 3% Sunscreen",
    ]
    assert by_name["Acne Gel"]["stated_percents"] == [None, 2.0, 12.025, None]
    # gift sets and mini sizes keep every name exactly as the CSV has it
    for name in ("Gift Kit", "Tiny Gel"):
        assert by_name[name]["ingredients"] == ["Water", "Salicylic Acid 2.0%"]
        assert by_name[name]["stated_percents"] == [None, None]
    assert drops[NOT_SKINCARE] == 1
    assert [e.status for _, _, e in report.rows] == [EXTRACTED, EXTRACTED, AMBIGUOUS]
    assert {p for p, _, _ in report.rows} == {"Acne Gel"}


def test_report_ignores_rows_dropped_as_duplicates():
    df = pd.concat([strength_df().iloc[[0]], strength_df().iloc[[0]]], ignore_index=True)
    report = StrengthReport()
    products, drops = clean_products(df, report)
    assert len(products) == 1 and drops[DUPLICATE] == 1
    assert len(report.with_status(EXTRACTED)) == 2          # counted once, not twice


def test_load_products_stores_stated_percent_and_shares_ingredient_rows(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    df = strength_df().iloc[[0]].copy()
    other = df.copy()
    other["product_name"] = "Other Gel"
    other["ingredients"] = "['Water, Zinc Oxide, Salicylic Acid']"      # same ingredients, no strengths
    products, _ = clean_products(pd.concat([df, other], ignore_index=True))
    load_products(products, db)
    with closing(get_db(db)) as conn:
        zinc = conn.execute("SELECT COUNT(*) FROM ingredients WHERE name = 'Zinc Oxide'").fetchone()[0]
        rows = conn.execute(
            "SELECT p.name, i.name AS ingredient, pi.stated_percent FROM product_ingredients pi"
            " JOIN products p ON p.id = pi.product_id JOIN ingredients i ON i.id = pi.ingredient_id"
            " WHERE i.name IN ('Zinc Oxide', 'Salicylic Acid') ORDER BY p.name, i.name"
        ).fetchall()
        text = conn.execute("SELECT ingredients_text FROM products WHERE name = 'Acne Gel'").fetchone()[0]
    assert zinc == 1       # one ingredient row, so compare-page overlap sees them as the same
    assert [tuple(r) for r in rows] == [
        ("Acne Gel", "Salicylic Acid", 2.0), ("Acne Gel", "Zinc Oxide", 12.025),
        ("Other Gel", "Salicylic Acid", None), ("Other Gel", "Zinc Oxide", None),
    ]
    assert text == "Water, Salicylic Acid, Zinc Oxide, Avobenzone 3% Sunscreen"


def test_load_products_accepts_products_without_stated_percents(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    load_products([{
        "name": "Hand Made", "brand": "B", "category": None, "price": 1.0, "size_text": "1 mL",
        "size_ml": 1.0, "price_per_ml": 1.0, "ingredients": ["Water", "Glycerin"],
    }], db)
    with closing(get_db(db)) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM product_ingredients WHERE stated_percent IS NULL"
        ).fetchone()[0] == 2


def test_pick_examples_is_varied_unique_and_capped():
    def ev(name, pct, fmt):
        return StrengthEvent(EXTRACTED, f"{name} {pct}%", name, pct, fmt)

    events = [ev(f"Ingredient {i:02d}", 1.0 + i, TRAILING) for i in range(60)]
    events += [ev("Zinc Oxide", 12.0, PAREN), ev("Procapil", 3.0, LEADING), ev("Ingredient 00", 9.0, TRAILING)]
    picked = pick_examples(events, n=30)
    assert len(picked) == 30
    assert len({e.name.lower() for e in picked}) == 30        # one example per ingredient name
    assert {PAREN, LEADING} <= {e.fmt for e in picked}


def test_pick_examples_shows_every_format_even_for_a_name_seen_in_another_format():
    def ev(name, pct, fmt):
        return StrengthEvent(EXTRACTED, f"{name} {pct}%", name, pct, fmt)

    events = [ev("Zinc Oxide", 2.34, TRAILING), ev("Zinc Oxide", 12.025, PAREN),
              ev("Retinol", 0.5, LEADING), ev("Salicylic Acid", 2.0, TRAILING)]
    assert {e.fmt for e in pick_examples(events)} == {TRAILING, PAREN, LEADING}


def test_pick_examples_fills_up_with_other_distinct_texts_when_names_repeat():
    events = [StrengthEvent(EXTRACTED, f"Zinc Oxide {i}%", "Zinc Oxide", float(i), TRAILING)
              for i in range(1, 41)]
    picked = pick_examples(events, n=30)
    assert len(picked) == 30 and len({e.original for e in picked}) == 30


def test_main_prints_the_strength_report(tmp_path, capsys):
    csv = tmp_path / "products.csv"
    strength_df().to_csv(csv, index=False)
    db = str(tmp_path / "test.db")
    init_db(db)
    seed_db(db)
    counts = main(str(csv), db)
    out = capsys.readouterr().out
    assert counts["products"] == 3
    assert "Stated strengths" in out
    assert re.search(r"products, before -> after\s+5 -> 3", out)       # 5 seeded, 3 loaded
    assert re.search(r"strengths stored \(stated_percent\)\s+2\n", out)
    assert "Salicylic Acid 2.0%  ->  Salicylic Acid + 2%" in out
    assert "Zinc Oxide (12.025%)  ->  Zinc Oxide + 12.025%" in out
    assert "Avobenzone 3% Sunscreen" in out            # listed as ambiguous
    assert "Ambiguous, left unchanged" in out


AA = GROUP_SEPARATOR


@pytest.mark.parametrize("secondary, tertiary, expected", [
    ("Treatments", "Face Serums", ("Face Serums", THIRD_LEVEL)),
    ("Moisturizers", "Moisturizers", ("Moisturizers", THIRD_LEVEL)),
    ("Lip Balms & Treatments", None, ("Lip Balms & Treatments", SECOND_LEVEL)),   # no third level
    ("Cleansers", float("nan"), ("Cleansers", SECOND_LEVEL)),
    ("Cleansers", "   ", ("Cleansers", SECOND_LEVEL)),                          # blank counts as empty
    ("Treatments", " Face Serums ", ("Face Serums", THIRD_LEVEL)),
    ("Mini Size", None, (None, None)),                                          # never grouped
    ("Mini Size", "Face Serums", (None, None)),
    ("Value & Gift Sets", "Skincare Sets", (None, None)),
    (None, None, (None, None)),
    (None, "Face Serums", ("Face Serums", THIRD_LEVEL)),
])
def test_compare_group_third_level_else_second_and_none_for_minis_and_gift_sets(secondary, tertiary, expected):
    assert compare_group(secondary, tertiary) == expected


def test_compare_group_adds_the_second_level_to_a_clashing_name():
    clashing = {"Anti-Aging"}
    assert compare_group("Eye Care", "Anti-Aging", clashing) == (f"Eye Care{AA}Anti-Aging", THIRD_LEVEL)
    assert compare_group("Eye Care", "Eye Masks", clashing) == ("Eye Masks", THIRD_LEVEL)
    assert AA == " › "


def group_df(rows):
    cols = ["product_name", "brand_name", "primary_category", "secondary_category",
            "tertiary_category", "price_usd", "size", "ingredients"]
    return pd.DataFrame(
        [(n, "B", "Skincare", s, t, 10.0, "1 oz/ 30 mL", "['Water']") for n, s, t in rows], columns=cols
    )


def test_ambiguous_subcategories_finds_names_under_several_second_levels():
    df = group_df([
        ("p1", "High Tech Tools", "Anti-Aging"), ("p2", "Shop by Concern", "Anti-Aging"),
        ("p3", "Eye Care", "Eye Masks"), ("p4", "Eye Care", "Eye Masks"),    # same pair twice: fine
        ("p5", "Cleansers", None),                                           # no third level
        ("p6", "Mini Size", "Eye Masks"),                                    # no group: ignored
        ("p7", "Value & Gift Sets", "Anti-Aging"),
    ])
    assert ambiguous_subcategories(df) == {"Anti-Aging"}


def test_ambiguous_subcategories_without_a_third_level_column():
    assert ambiguous_subcategories(group_df([("p", "Eye Care", None)]).drop(columns="tertiary_category")) == set()


def test_clean_products_sets_groups_levels_and_renames_clashes():
    df = group_df([
        ("Serum", "Treatments", "Face Serums"),
        ("Lip Balm", "Lip Balms & Treatments", None),
        ("Cream", "Moisturizers", "Moisturizers"),
        ("Cream No Level", "Moisturizers", None),
        ("Tiny Serum", "Mini Size", None),
        ("Gift Kit", "Value & Gift Sets", None),
        ("Device", "High Tech Tools", "Anti-Aging"),
        ("Concern", "Shop by Concern", "Anti-Aging"),
    ])
    df["size"] = [f"{i + 1} oz/ {30 + i} mL" for i in range(len(df))]       # keep them distinct
    products, _ = clean_products(df)
    got = {p["name"]: (p["compare_group"], p["group_level"]) for p in products}
    assert got == {
        "Serum": ("Face Serums", THIRD_LEVEL),
        "Lip Balm": ("Lip Balms & Treatments", SECOND_LEVEL),
        "Cream": ("Moisturizers", THIRD_LEVEL),
        "Cream No Level": ("Moisturizers", SECOND_LEVEL),   # same name, so the same group
        "Tiny Serum": (None, None),
        "Gift Kit": (None, None),
        "Device": (f"High Tech Tools{AA}Anti-Aging", THIRD_LEVEL),
        "Concern": (f"Shop by Concern{AA}Anti-Aging", THIRD_LEVEL),
    }


def test_clean_products_works_without_a_third_level_column():
    products, _ = clean_products(sample_df())            # this frame has no tertiary_category
    assert {p["compare_group"] for p in products} == {"Moisturizers"}
    assert {p["group_level"] for p in products} == {SECOND_LEVEL}


def test_load_products_stores_compare_group(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    products, _ = clean_products(group_df([
        ("Serum", "Treatments", "Face Serums"), ("Tiny", "Mini Size", None),
    ]).assign(size=["1 oz/ 30 mL", "2 oz/ 60 mL"]))
    load_products(products, db)
    with closing(get_db(db)) as conn:
        stored = {r["name"]: r["compare_group"] for r in conn.execute("SELECT name, compare_group FROM products")}
    assert stored == {"Serum": "Face Serums", "Tiny": None}


def test_main_prints_the_comparison_group_report(tmp_path, capsys):
    df = group_df([
        ("Serum", "Treatments", "Face Serums"), ("Lip Balm", "Lip Balms & Treatments", None),
        ("Tiny", "Mini Size", None), ("Device", "High Tech Tools", "Anti-Aging"),
        ("Concern", "Shop by Concern", "Anti-Aging"),
    ])
    df["size"] = [f"{i + 1} oz/ {30 + i} mL" for i in range(len(df))]
    csv = tmp_path / "products.csv"
    df.to_csv(csv, index=False)
    db = str(tmp_path / "test.db")
    main(str(csv), db)
    out = capsys.readouterr().out
    assert "Comparison groups" in out
    assert re.search(r"products with a group\s+4\n", out)
    assert re.search(r"fell back to the second level\s+1\n", out)
    assert "Lip Balms & Treatments: 1" in out
    assert re.search(r"products with no group\s+1\n", out)
    assert "Mini Size: 1" in out and "Value & Gift Sets: 0" in out      # both always listed
    assert f"High Tech Tools{AA}Anti-Aging (1)" in out and f"Shop by Concern{AA}Anti-Aging (1)" in out
    assert "groups with one product (hidden from the picker)" in out


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
