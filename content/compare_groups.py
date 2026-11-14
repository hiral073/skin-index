"""Group cleanup: how the groups built from the category levels are merged or hidden.

The loader builds each product's comparison group from the CSV (third category level, else
second) and then applies this map, so a rebuilt database gives the same result. The original
category columns are never changed.

GROUP_MERGES: old group name -> new group name. A name not listed keeps its group. A new name
with GROUP_SEPARATOR in it is a subcategory ("Sunscreen › Face" is the Face subcategory of
Sunscreen). It is a group of its own for Compare and Insights; the Products filter also offers
"All Sunscreen" for the parent.
HIDDEN_GROUPS: old group names that are not product types, so their products get no group
(they are not compared and are not in the Compare picker or the Insights group selector).
The names here are the ones the loader builds before cleanup (a clashing third-level name has
its second level in front, for example "Shop by Concern › Anti-Aging").
"""

GROUP_SEPARATOR = " › "  # "Eye Care › Anti-Aging", "Sunscreen › Face"

GROUP_MERGES = {
    "Face Sunscreen": f"Sunscreen{GROUP_SEPARATOR}Face",
    "Body Sunscreen": f"Sunscreen{GROUP_SEPARATOR}Body",
    "Cleansers": "Face Wash & Cleansers",
    "Eye Masks": "Eye Creams & Treatments",
    "For Face": f"Self Tanners{GROUP_SEPARATOR}Face",
    "For Body": f"Self Tanners{GROUP_SEPARATOR}Body",
}

HIDDEN_GROUPS = {
    "Shop by Concern › Anti-Aging",
    "High Tech Tools › Anti-Aging",
    "Holistic Wellness",
    "Teeth Whitening",
}


def split_group(name):
    """(parent, subcategory or None): "Sunscreen › Face" gives ("Sunscreen", "Face")."""
    parent, _, sub = name.partition(GROUP_SEPARATOR)
    return parent, sub or None
