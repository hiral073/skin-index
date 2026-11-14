import re

import pytest

from content import main_ingredients as content
from database.services import MAIN_INGREDIENT_LABELS, main_ingredients_of

BANNED = ["safe", "best for", "treats", "cures", "proven", "effective", "better", "best", "dupe"]


def test_the_eleven_main_ingredient_groups_are_pinned():
    assert [e["key"] for e in content.MAIN_INGREDIENTS] == [
        "niacinamide", "ascorbic-acid", "retinol", "retinal", "hyaluronic-acid", "salicylic-acid",
        "glycolic-acid", "lactic-acid", "azelaic-acid", "ceramide", "peptide",
    ]
    assert [e["label"] for e in content.MAIN_INGREDIENTS] == [
        "niacinamide", "ascorbic acid", "retinol", "retinal", "hyaluronic acid", "salicylic acid",
        "glycolic acid", "lactic acid", "azelaic acid", "ceramide", "peptide",
    ]
    assert content.TOP_N == 10
    assert list(MAIN_INGREDIENT_LABELS) == [e["key"] for e in content.MAIN_INGREDIENTS]


def test_each_group_matches_one_exact_word_or_phrase_only():
    for entry in content.MAIN_INGREDIENTS:
        assert len(entry["name_patterns"]) == 1 and len(entry["ingredient_patterns"]) == 1, entry["key"]
        assert entry["name_patterns"] == entry["ingredient_patterns"]
        pattern = entry["ingredient_patterns"][0]
        assert pattern.startswith(r"\b") and pattern.endswith(r"\b"), pattern     # whole words only
        assert "|" not in pattern and ".*" not in pattern, pattern                # no alternatives or wildcards


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
    ("Serum", ["Water", "Ascorbic Acid"], ["ascorbic-acid"]),
    ("Serum", ["L-Ascorbic Acid"], ["ascorbic-acid"]),                        # the whole phrase is in the name
    ("Ascorbic Acid Serum", ["Water"], ["ascorbic-acid"]),
    ("Serum", ["Retinol"], ["retinol"]),
    ("Retinol Night Cream", ["Water"], ["retinol"]),
    ("Serum", ["Retinal"], ["retinal"]),
    ("Serum", ["Hyaluronic Acid"], ["hyaluronic-acid"]),
    ("Serum", ["Hydrolyzed Hyaluronic Acid"], ["hyaluronic-acid"]),
    ("Serum", ["Salicylic Acid"], ["salicylic-acid"]),
    ("Serum", ["Glycolic Acid"], ["glycolic-acid"]),
    ("Serum", ["Lactic Acid"], ["lactic-acid"]),
    ("Serum", ["Azelaic Acid"], ["azelaic-acid"]),
    ("Serum", ["Ceramide NP"], ["ceramide"]),                                 # the whole word "ceramide"
    ("Serum", ["Ceramide 3"], ["ceramide"]),
    ("Serum", ["Ceramides"], ["ceramide"]),                                   # the plural
    ("Ceramide Cream", ["Water"], ["ceramide"]),
    ("Serum", ["Peptide Complex"], ["peptide"]),
    ("Serum", ["Peptides"], ["peptide"]),
    ("Peptide Cream", ["Water"], ["peptide"]),
    ("Serum", ["Water", "Glycerin"], []),
    ("Serum", [], []),
    ("", None, []),
])
def test_membership_rules(name, ingredients, expected):
    assert main_ingredients_of(name, ingredients) == expected


@pytest.mark.parametrize("ingredient", [
    # forms and derivatives are not grouped with the ingredient
    "Retinaldehyde", "Retinyl Palmitate", "Hydroxypinacolone Retinoate", "Retinoid",
    "Sodium Hyaluronate", "Hyaluronan", "Hyaluronidase",
    "Magnesium Ascorbyl Phosphate", "Ascorbyl Glucoside", "Tetrahexyldecyl Ascorbate", "Sodium Ascorbate",
    "Ascorbic", "Salicylate", "Sodium Lactate", "Lactic", "Glycolic", "Azelaic", "Niacin",
    # longer names that only contain the letters
    "Copper Tripeptide-1", "Palmitoyl Tripeptide-1", "Acetyl Hexapeptide-8", "Dipeptide Diaminobutyroyl",
])
def test_forms_derivatives_and_longer_names_are_not_matched(ingredient):
    assert main_ingredients_of("Serum", [ingredient]) == [], ingredient


def test_retinol_and_retinal_are_separate_groups():
    assert main_ingredients_of("Serum", ["Retinol"]) == ["retinol"]
    assert main_ingredients_of("Serum", ["Retinal"]) == ["retinal"]
    assert main_ingredients_of("Serum", ["Retinol", "Retinal"]) == ["retinol", "retinal"]


def test_glycolic_and_lactic_acid_are_separate_groups():
    assert main_ingredients_of("Serum", ["Glycolic Acid"]) == ["glycolic-acid"]
    assert main_ingredients_of("Serum", ["Lactic Acid"]) == ["lactic-acid"]
    assert main_ingredients_of("AHA Peel", ["Water"]) == []                  # "AHA" is not an ingredient word


def test_a_product_can_be_in_several_groups_in_the_order_of_the_content_file():
    assert main_ingredients_of("Serum", ["Ceramide NP", "Niacinamide", "Glycolic Acid"]) == [
        "niacinamide", "glycolic-acid", "ceramide",
    ]


def test_only_the_first_ten_listed_ingredients_count():
    nine = [f"Filler {i}" for i in range(9)]
    assert main_ingredients_of("Serum", nine + ["Niacinamide"]) == ["niacinamide"]            # 10th place counts
    assert main_ingredients_of("Serum", nine + ["Water", "Niacinamide"]) == []                # 11th place does not
