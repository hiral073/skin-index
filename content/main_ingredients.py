"""The main ingredient groups the Compare page uses, and how a product is put in one.

Each group matches one exact ingredient word or phrase, as whole words and ignoring capital
letters. Related forms and derivatives are not grouped with it: retinol and retinal are two groups,
vitamin C is only "ascorbic acid" (not ascorbyl or ascorbate names), "hyaluronic acid" does not
include sodium hyaluronate, and a longer name such as "Tripeptide-1" is not "peptide". A name that
contains the whole word does match ("Ceramide NP" contains the word "ceramide").

A product belongs to a group when the word or phrase is in its name, or among its first TOP_N
listed ingredients. A product can belong to more than one group. Ingredient order is a rough
guide: the data has no amounts, so membership only says the product lists the ingredient near the
top of its label or names it. It says nothing about what the ingredient does.

Each entry: key (the id used in links), label (shown on the page), name_patterns (regular
expressions matched, ignoring case, against the product name), ingredient_patterns (matched
against each ingredient name) and science_term (the search the Ingredient Science link makes).
"""

TOP_N = 10

MAIN_INGREDIENTS = [
    {
        "key": "niacinamide", "label": "niacinamide", "science_term": "niacinamide",
        "name_patterns": [r"\bniacinamide\b"],
        "ingredient_patterns": [r"\bniacinamide\b"],
    },
    {
        "key": "ascorbic-acid", "label": "ascorbic acid", "science_term": "ascorbic acid",
        "name_patterns": [r"\bascorbic acid\b"],
        "ingredient_patterns": [r"\bascorbic acid\b"],
    },
    {
        "key": "retinol", "label": "retinol", "science_term": "retinol",
        "name_patterns": [r"\bretinol\b"],
        "ingredient_patterns": [r"\bretinol\b"],
    },
    {
        "key": "retinal", "label": "retinal", "science_term": "retinal",
        "name_patterns": [r"\bretinal\b"],
        "ingredient_patterns": [r"\bretinal\b"],
    },
    {
        "key": "hyaluronic-acid", "label": "hyaluronic acid", "science_term": "hyaluronic acid",
        "name_patterns": [r"\bhyaluronic acid\b"],
        "ingredient_patterns": [r"\bhyaluronic acid\b"],
    },
    {
        "key": "salicylic-acid", "label": "salicylic acid", "science_term": "salicylic acid",
        "name_patterns": [r"\bsalicylic acid\b"],
        "ingredient_patterns": [r"\bsalicylic acid\b"],
    },
    {
        "key": "glycolic-acid", "label": "glycolic acid", "science_term": "glycolic acid",
        "name_patterns": [r"\bglycolic acid\b"],
        "ingredient_patterns": [r"\bglycolic acid\b"],
    },
    {
        "key": "lactic-acid", "label": "lactic acid", "science_term": "lactic acid",
        "name_patterns": [r"\blactic acid\b"],
        "ingredient_patterns": [r"\blactic acid\b"],
    },
    {
        "key": "azelaic-acid", "label": "azelaic acid", "science_term": "azelaic acid",
        "name_patterns": [r"\bazelaic acid\b"],
        "ingredient_patterns": [r"\bazelaic acid\b"],
    },
    {
        "key": "ceramide", "label": "ceramide", "science_term": "ceramides",
        "name_patterns": [r"\bceramides?\b"],
        "ingredient_patterns": [r"\bceramides?\b"],
    },
    {
        "key": "peptide", "label": "peptide", "science_term": "peptides",
        "name_patterns": [r"\bpeptides?\b"],
        "ingredient_patterns": [r"\bpeptides?\b"],
    },
]
