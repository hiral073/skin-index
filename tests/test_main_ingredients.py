import re

import pytest

from content import main_ingredients as content
from database.services import MAIN_INGREDIENT_LABELS, main_ingredients_of

BANNED = ["safe", "best for", "treats", "cures", "proven", "effective", "better", "best", "dupe"]


def test_the_nine_main_ingredient_groups_are_pinned():
    assert [e["key"] for e in content.MAIN_INGREDIENTS] == [
        "niacinamide", "vitamin-c", "retinoids", "hyaluronic-acid", "salicylic-acid", "peptides",
        "ceramides", "aha", "azelaic-acid",
    ]
    assert content.TOP_N == 10
    assert list(MAIN_INGREDIENT_LABELS) == [e["key"] for e in content.MAIN_INGREDIENTS]


def test_every_entry_has_what_the_page_and_the_science_link_need():
    for entry in content.MAIN_INGREDIENTS:
        assert set(entry) == {"key", "label", "science_term", "name_patterns", "ingredient_patterns"}
        assert re.fullmatch(r"[a-z-]+", entry["key"]) and entry["label"] and entry["science_term"]
        for pattern in entry["name_patterns"] + entry["ingredient_patterns"]:
            re.compile(pattern)


def test_the_labels_use_none_of_the_banned_words():
    for entry in content.MAIN_INGREDIENTS:
        for word in BANNED:
            assert word not in entry["label"].lower() and word not in entry["science_term"].lower()


@pytest.mark.parametrize("name, ingredients, expected", [
    ("Serum", ["Water", "Niacinamide"], ["niacinamide"]),
    ("Serum", ["Water", "NIACINAMIDE"], ["niacinamide"]),                    # case does not matter
    ("Niacinamide Booster", ["Water"], ["niacinamide"]),                      # in the name
    ("Serum", ["Water", "Ascorbic Acid"], ["vitamin-c"]),
    ("Serum", ["3-O-Ethyl Ascorbic Acid"], ["vitamin-c"]),
    ("Serum", ["Magnesium Ascorbyl Phosphate"], ["vitamin-c"]),
    ("Serum", ["Tetrahexyldecyl Ascorbate"], ["vitamin-c"]),
    ("Vitamin C Serum", ["Water"], ["vitamin-c"]),
    ("Serum", ["Retinol"], ["retinoids"]),
    ("Serum", ["Retinaldehyde"], ["retinoids"]),
    ("Serum", ["Retinyl Palmitate"], ["retinoids"]),
    ("Serum", ["Hydroxypinacolone Retinoate"], ["retinoids"]),
    ("Retinoid Night Cream", ["Water"], ["retinoids"]),
    ("Serum", ["Sodium Hyaluronate"], ["hyaluronic-acid"]),
    ("Serum", ["Hyaluronic Acid"], ["hyaluronic-acid"]),
    ("Serum", ["Salicylic Acid"], ["salicylic-acid"]),
    ("Serum", ["Copper Tripeptide-1"], ["peptides"]),
    ("Serum", ["Acetyl Hexapeptide-8"], ["peptides"]),
    ("Peptide Cream", ["Water"], ["peptides"]),
    ("Serum", ["Ceramide NP"], ["ceramides"]),
    ("Serum", ["Ceramide 3"], ["ceramides"]),
    ("Serum", ["Glycolic Acid"], ["aha"]),
    ("Serum", ["Lactic Acid"], ["aha"]),
    ("AHA Peel", ["Water"], ["aha"]),
    ("Serum", ["Azelaic Acid"], ["azelaic-acid"]),
    ("Serum", ["Water", "Glycerin"], []),
    ("Serum", [], []),
    ("", None, []),
])
def test_membership_rules(name, ingredients, expected):
    assert main_ingredients_of(name, ingredients) == expected


def test_a_product_can_be_in_several_groups_in_the_order_of_the_content_file():
    assert main_ingredients_of("Serum", ["Ceramide NP", "Niacinamide", "Glycolic Acid"]) == [
        "niacinamide", "ceramides", "aha",
    ]


def test_only_the_first_ten_listed_ingredients_count():
    nine = [f"Filler {i}" for i in range(9)]
    assert main_ingredients_of("Serum", nine + ["Niacinamide"]) == ["niacinamide"]            # 10th place counts
    assert main_ingredients_of("Serum", nine + ["Water", "Niacinamide"]) == []                # 11th place does not


def test_related_but_different_names_do_not_match():
    for name in ("Salicylate", "Niacin", "Sodium Lactate", "Hyaluronidase", "Retina Extract", "Azelaic", "Ascorbic"):
        assert main_ingredients_of("Serum", [name]) == [], name
