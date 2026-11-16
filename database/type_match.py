"""Reading a product type from a product name (Compare types).

A type is one whole word, matched ignoring capital letters. A hyphen, space or any other
non-letter, non-digit character splits words, so "Gel-Cream" contains "gel" and "cream". Nothing
else matches: no plural, no other spelling ("creme", "crème", "creamy") and no merging of names.
The phrases of `content.product_types.NOT_A_TYPE_PHRASES` ("oil-free", "oil-control") are cut out of
the name first, so they do not count as the word inside them.
"""
import re

from content import product_types as types_content

_PHRASES = re.compile(
    "|".join(rf"(?<![^\W_]){re.escape(p)}(?![^\W_])" for p in types_content.NOT_A_TYPE_PHRASES), re.IGNORECASE)


def name_has_word(name, word):
    """True when `word` is in `name` as a whole word, ignoring capital letters."""
    if not name or not word:
        return False
    name = _PHRASES.sub(" ", name)
    return re.search(rf"(?<![^\W_]){re.escape(word)}(?![^\W_])", name, re.IGNORECASE) is not None


def split_by_types(products, word_a, word_b):
    """Sort products (dicts with a "name") into (only A's word, only B's word, both words).

    A product with neither word is in none of the three. A product with both words is in the
    third list and so counts on neither side.
    """
    only_a, only_b, both = [], [], []
    for product in products:
        has_a = name_has_word(product["name"], word_a)
        has_b = name_has_word(product["name"], word_b)
        if has_a and has_b:
            both.append(product)
        elif has_a:
            only_a.append(product)
        elif has_b:
            only_b.append(product)
    return only_a, only_b, both
