"""Compare product types: the words that count as a type, the rule that reads a type from a product
name, and every fixed text of the page.

A type is one whole word in the product name, matched ignoring capital letters ("Cream", "cream").
A hyphen splits words, so "Gel-Cream" contains both "gel" and "cream". No related spelling is
matched or merged: "creme", "crème" and "creamy" are not "cream", and the phrases in
`NOT_A_TYPE_PHRASES` ("oil-free", "oil-control") do not count as the word "oil". A product whose
name contains the words of both compared types is left out of both sides and is counted in the
left-out line. These are words brands put in names, not tested formulations.

The list of types of a category is built from the data: every word of `TYPE_WORDS` that a category's
product names contain, and a pair is offered only when each side has at least `min_products`
products once the products with both words are left out.

The format lines ("what the word usually means") are our own short wording about texture only,
each taken from one named source that was read before it was written. Only cream and gel in
Moisturizers have one (the source is about moisturizers); every other type shows data only. Never
use safe, best, recommended, treats, cures, proven, effective, "for your skin", "good for" or
"suitable" here, and never name a skin type. One narrow exception to the claims rules, by decision
of the project owner: these lines may repeat what the named source says about texture.
`tests/test_compare_types.py` pins every text and checks it.
"""

TYPES_CONFIG = {
    "min_products": 15,   # each type needs at least this many products (after the left-out ones)
    "top_n": 10,          # length of the common-ingredient list
}

# The words that can be a type, in the order they are listed. Only words for a form or texture;
# no word for a purpose or an ingredient.
TYPE_WORDS = ["cream", "gel", "lotion", "oil", "balm", "foam", "serum", "mask", "mist", "spray",
              "stick", "powder", "butter", "milk", "essence"]

# Phrases cut out of a name before it is read, so they do not count as the word inside them.
NOT_A_TYPE_PHRASES = ["oil-free", "oil free", "oil-control", "oil control"]

AAD_EMOLLIENTS = {
    "name": "American Academy of Dermatology: Emollient options",
    "url": "https://www.aad.org/public/everyday-care/skin-care-basics/dry/pick-moisturizer",
}

# (group, word) -> our line with its named source
FORMAT_LINES = {
    ("Moisturizers", "cream"): {
        "text": "Thicker than a lotion or a gel, with a higher oil content.",
        "source": AAD_EMOLLIENTS, "checked": "2026-11-16"},
    ("Moisturizers", "gel"): {
        "text": "Often water-based, and tends to feel lighter on the skin than a lotion.",
        "source": AAD_EMOLLIENTS, "checked": "2026-11-16"},
}

TITLE = "Compare"
CATEGORY_LABEL = "1. Category"
CHOOSE_CATEGORY = "Choose a category"
MODE_QUESTION = "What do you want to compare?"
MODES = {
    "products": {"title": "Two specific products",
                 "example": "For example, two serums from different brands."},
    "types": {"title": "Two product types",
              "example": "For example, cream vs gel moisturizers."},
}
PICK_A = "2. Type A"
PICK_B = "3. Type B"
CHOOSE_TYPE = "Choose a type"
INTRO_START = "Choose a category to begin."
INTRO_CHOOSE = "Now choose what to compare in this category."
INTRO_TYPES = ("A type is a word in the product name, for example “cream” or “gel”. "
               "Only types with enough products are listed.")
NO_TYPES_FOR_CATEGORY = ("{group} has no pair of types with at least {min} products each, so it isn't "
                         "offered here. Two product types can be compared in: {options}.")
NO_TYPES_AT_ALL = "No category has a pair of types with enough products yet."
UNUSABLE_CHOICE = ("That choice can't be compared here. Two product types can be compared in: {options}. "
                   "Two specific products can be compared in any category with 2 or more products.")
WAITING = "Choose two types to see them side by side."

# fixed lines of the page; {n} is filled in
LEFT_OUT = "Products whose names contain both words are left out of this comparison, {n} {products}."
DIFFERENT_SIZES = ("The two types have different numbers of products, so compare the shares and "
                   "averages, not the totals.")
SEE_ALL = "See all {n} {products}"
TYPE_CHIP = "Type: {label}"

READING_NOTE = ("A product is in a type when its name contains that word as a whole word, ignoring capital "
                "letters. These are words brands put in names, not tested formulations. "
                "“Creme”, “crème” and “creamy” are not counted as “cream”, and “oil-free” and "
                "“oil-control” are not counted as “oil”.")
SOURCE_LINE_LABEL = "Source"
FORMAT_LABEL = "What the word usually means"
NO_FORMAT_LINE = "Data only: no source has been read for this word yet."
ENGAGEMENT_NOTE = ("Ratings come from one retailer's site as of March 2023. They show shopper activity, "
                   "not quality. The average rating is weighted by the number of reviews.")
INGREDIENT_NOTE = ("Ingredient names are counted as the brand wrote them. Only Water, Aqua and Eau count as "
                   "one ingredient, and so do Fragrance and Parfum. Water is shown apart because it is in "
                   "almost every product.")
PATCH_NOTE = "Patch-test new products and see a dermatologist with any concern."
SOURCES_NOTE = "General information from the sources named. Not medical advice."
