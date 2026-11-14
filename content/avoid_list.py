"""The fixed texts and limits of the avoid list (Step 12c).

The list lives only in the visitor's browser (a cookie the visitor's own action sets). The site
reads it with each request to filter and tag results, and never saves or logs it.

Never use safe, free of, clean, best, recommend, suitable, good for or anything that suggests
a product is fine: a product with no match only has nothing found in its listed ingredients.
"""

COOKIE_NAME = "avoid_list"   # a URL-encoded JSON list of the typed words
COOKIE_DAYS = 30             # how long the browser keeps it after the last change
MAX_TERMS = 20
MIN_TERM_LENGTH = 2
MAX_TERM_LENGTH = 40

FILTER_LABEL = "Ingredients to avoid"
CHECKED_AGAINST = "Checked against:"
STORE_NOTE = "Your list is stored in your browser. The site reads it to filter results but does not save it."
BASED_ON_NOTE = (
    "Based on the ingredient list as written by the brand. Lists can be incomplete. "
    "Check the product label."
)
HOW_IT_MATCHES = (
    "Each word or phrase is matched as whole words in the brand's ingredient list, ignoring capital letters. "
    "Fragrance and parfum count as the same word, and so do water, aqua and eau."
)
INPUT_LABEL = "Add an ingredient to avoid"
INPUT_ERROR = (
    "Use 2 to 40 letters, numbers, spaces and - ' . / ( ) + only. "
    "A word can be on the list once, and the list holds up to 20."
)
ADD_LABEL = "Add"
CLEAR_LABEL = "Clear my list"
REMOVE_LABEL = "Remove"
EMPTY_HINT = "Your list is empty. Type an ingredient and press Add."
HIDE_LABEL = "Hide products that list my avoided ingredients"
HIDE_NEEDS_LIST = "Add an ingredient to use this switch."
LISTS = "Lists:"
MATCHED = "matched:"
NOT_FOUND = "None found in the listed ingredients."
NO_INGREDIENTS = "Ingredient list not available, can't check"
DETAIL_TITLE = "Your avoid list"
EDIT_LINK = "Edit your avoid list"
COMPARE_ROW = "Your avoid list"
NO_JAVASCRIPT = "Adding and removing words needs JavaScript."


def hidden_text(count):
    return f"{count} product{'' if count == 1 else 's'} hidden because they list an ingredient on your list."
