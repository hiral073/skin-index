"""How ingredient names and typed words are matched. Pure functions, no database.

One place for the two synonym rules (water/aqua/eau and fragrance/parfum, see
`content/ingredient_words.py`). The loader, Compare and the avoid list all use it.
"""
import re
from functools import lru_cache

from content.ingredient_words import SYNONYM_GROUPS

_WORDS = re.compile(r"[^\W_]+")          # runs of letters and digits
_SPLIT_WORDS = re.compile(r"([^\W_]+)")  # the same, keeping what is between them


def _group_of(word):
    word = word.lower()
    return next((group for group in SYNONYM_GROUPS if word in group), None)


def synonym_name(name):
    """"Water" or "Fragrance" when every word of `name` belongs to the same synonym group, else None.

    "Water (Aqua)" and "Aqua/Water/Eau" give "Water"; "Parfum" and "Fragrance (Parfum)" give
    "Fragrance"; "Purified Water" and "Fragrance Mix" give None (another word is in the name).
    """
    words = _WORDS.findall(name.lower()) if isinstance(name, str) else []
    if not words:
        return None
    for group in SYNONYM_GROUPS:
        if set(words) <= set(group):
            return group[0].capitalize()
    return None


def ingredient_key(name):
    """What makes two ingredient names the same ingredient: their text without capital letters or
    extra spaces, with a synonym-only name (see `synonym_name`) reduced to its group's name."""
    synonym = synonym_name(name)
    return synonym.lower() if synonym else " ".join(name.lower().split())


@lru_cache(maxsize=512)
def term_regex(term):
    """A regular expression that finds `term` as whole words in an ingredient name, ignoring case.

    A word of the term that is in a synonym group matches any word of that group ("aqua" finds
    "Water"). Spaces in the term match any run of spaces. Nothing else is matched: no part of a
    longer word, no plural, no similar spelling.
    """
    pieces = []
    for part in _SPLIT_WORDS.split(term.lower()):
        if _WORDS.fullmatch(part):
            group = _group_of(part)
            pieces.append(
                "(?:" + "|".join(re.escape(word) for word in group) + ")" if group else re.escape(part)
            )
        else:  # what lies between the words: spaces match any run of spaces, the rest is literal
            pieces.append("".join(r"\s+" if ch.isspace() else re.escape(ch) for ch in re.sub(r"\s+", " ", part)))
    return re.compile(r"(?<!\w)" + "".join(pieces) + r"(?!\w)", re.IGNORECASE)


def term_matches(term, name):
    """True when the typed `term` is found, as whole words, in the ingredient `name`."""
    return term_regex(term).search(name) is not None
