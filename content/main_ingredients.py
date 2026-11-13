"""The main ingredient groups the Compare page uses, and how a product is put in one.

A product belongs to a group when the group's ingredient is in its name, or among its first TOP_N
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
        "key": "vitamin-c", "label": "vitamin C", "science_term": "vitamin c",
        "name_patterns": [r"\bvitamin c\b", r"\bascorbic\b", r"\bascorbyl\b"],
        "ingredient_patterns": [r"\bascorbic acid\b", r"\bascorb(?:yl|ate)\b", r"\bvitamin c\b"],
    },
    {
        "key": "retinoids", "label": "retinol and other retinoids", "science_term": "retinol",
        "name_patterns": [r"\bretinol\b", r"\bretinoids?\b", r"\bretinal\b", r"\bretinaldehyde\b",
                          r"\btretinoin\b", r"\badapalene\b"],
        "ingredient_patterns": [r"\bretinol\b", r"\bretinoids?\b", r"\bretinal\b", r"\bretinaldehyde\b",
                                r"\bretinyl\b", r"\bretinoate\b", r"\btretinoin\b", r"\badapalene\b"],
    },
    {
        "key": "hyaluronic-acid", "label": "hyaluronic acid", "science_term": "hyaluronic acid",
        "name_patterns": [r"\bhyaluronic\b", r"\bhyaluronate\b"],
        "ingredient_patterns": [r"\bhyaluronic acid\b", r"\bhyaluronate\b", r"\bhyaluronan\b"],
    },
    {
        "key": "salicylic-acid", "label": "salicylic acid", "science_term": "salicylic acid",
        "name_patterns": [r"\bsalicylic\b"],
        "ingredient_patterns": [r"\bsalicylic acid\b"],
    },
    {
        "key": "peptides", "label": "peptides", "science_term": "peptides",
        "name_patterns": [r"peptide"],
        "ingredient_patterns": [r"peptide"],
    },
    {
        "key": "ceramides", "label": "ceramides", "science_term": "ceramides",
        "name_patterns": [r"\bceramides?\b"],
        "ingredient_patterns": [r"\bceramide"],
    },
    {
        "key": "aha", "label": "AHA (glycolic or lactic acid)", "science_term": "alpha hydroxy acid",
        "name_patterns": [r"\baha\b", r"\bglycolic\b", r"\blactic\b"],
        "ingredient_patterns": [r"\bglycolic acid\b", r"\blactic acid\b"],
    },
    {
        "key": "azelaic-acid", "label": "azelaic acid", "science_term": "azelaic acid",
        "name_patterns": [r"\bazelaic\b"],
        "ingredient_patterns": [r"\bazelaic acid\b"],
    },
]
