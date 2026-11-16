"""Fixed texts of the MCP server (`mcp_server/server.py`): the source named in every answer, the
tool descriptions' shared notes and the plain messages. Never use safe, free of, clean, best,
recommend, suitable, good for, treats, cures, proven or effective here."""

SOURCES = {
    "products": "Skin Index database: March 2023 Sephora US product snapshot. Prices are USD.",
    "insights": ("Skin Index database: March 2023 Sephora US product snapshot. Likes, ratings and reviews "
                 "are shopper engagement on one retailer's site, not sales."),
    "weather": "Open-Meteo.com (weather and UV), CAMS via Open-Meteo (air quality), GeoNames (places).",
    "studies": "PubMed (US National Library of Medicine).",
}

NOTES = {
    "insights": ("Older products have had more time to collect likes and reviews. Brands are always "
                 "counted over every product."),
    "compare": ("No verdict is made and no product is called better than another. Ingredient order is a "
                "rough guide and amounts are not in the data. Shared ingredients do not mean the "
                "formulas behave the same."),
    "weather": "Live conditions, general information only.",
    "studies": ("Listing of published papers. A study existing does not mean a product works. The kind "
                "of paper is taken from PubMed's own record."),
    "avoid_list": ("Based on the ingredient list as written by the brand. Lists can be incomplete. "
                   "Check the product label. No match only means nothing on the list was found. "
                   "The words are used for this one call and are not stored."),
    "ingredients": "Patch-test new products and see a dermatologist with any concern.",
    "compare_types": ("A type is a word in the product name (whole word, capital letters ignored), not a tested "
                      "formulation. Products whose names contain both words are left out of both sides. The two "
                      "types can have different numbers of products, so compare the shares and "
                      "averages, not the totals. Ratings come from one retailer's site as of March 2023. "
                      "General information from the sources named. Not medical advice."),
}

TYPE_MESSAGES = {
    "waiting": "Choose a group and two different types from valid_choices.",
    "unknown": "That group or type can't be compared here. valid_choices lists the groups and types that can.",
    "same_type": "Choose two different types from valid_choices.",
    "too_few": ("{label} has {n} {products} in {group}, fewer than the {min} needed, so these two types "
                "can't be compared here. valid_choices lists the pairs that can."),
}

COMPARE_MESSAGES = {
    "waiting": "A product id was not found, so there is nothing to compare.",
    "same_product": "Both ids are the same product, so there is nothing to compare.",
    "no_group": "A product has no comparison group, so they can't be compared fairly.",
    "different_groups": "Product A is in {a_group} and product B is in {b_group}, so they can't be compared fairly.",
    "ok": "Compared within {a_group}.",
}

MESSAGES = {
    "bad_id": "{name} must be a whole number above 0.",
    "bad_text": "{name} must be text.",
    "no_product": "No product has the id {id}.",
    "bad_ingredient": ("The ingredient word is not usable: use 2 to 40 letters or digits, "
                       "with no links or symbols."),
    "bad_words": "words must be a list of 1 to {max} ingredient words, each 2 to 40 characters.",
    "no_usable_words": "None of the words is usable: use 2 to 40 letters or digits, with no links or symbols.",
    "bad_city": ("Give a city name, or both latitude (-90 to 90) and longitude (-180 to 180). city, country and "
                 "region must each be 2 to 60 letters, digits, spaces, hyphens, apostrophes or commas."),
    "bad_ingredient_study": "ingredient must be a plain ingredient name, for example niacinamide.",
    "no_place": "No place was found for that name (with the country and region given, if any).",
    "weather_down": "The weather services could not be reached right now. Try again later.",
    "studies_down": "PubMed could not be reached and no saved results exist. Try again later.",
    "unknown_group": ("No group named \"{group}\" has enough products. Use list_groups for names; "
                      "the groups at least {min} products large are in `groups_available`."),
    "failed": "That request could not be completed. Check the inputs and try again.",
}
