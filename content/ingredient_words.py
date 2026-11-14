"""The only two synonym rules for ingredient names in the whole project.

Each group lists words that count as the same word. The first word is the name used for it.
Everything else about ingredient names is exact: the same words in the same order, ignoring
capital letters and spacing. The rules apply to the loader, to Compare and to the avoid list
(all through `database/ingredient_match.py`), so they cannot drift apart. Do not add a group
without the project owner agreeing: a wrong synonym merges different substances.
"""

SYNONYM_GROUPS = (
    ("water", "aqua", "eau"),
    ("fragrance", "parfum"),
)
