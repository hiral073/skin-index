"""Skin Index MCP server (Step 11): read-only tools over the same service functions as the pages.

Run it over stdio (the transport Claude Code uses):

    python mcp_server/server.py

Nothing here has logic of its own: each tool checks its inputs, calls one service function and
names its source. The product database is opened read-only. `find_studies` is the one tool that
saves anything: PubMed's paper lists go into the `pubmed_searches` cache table of the database
file, as on the Ingredient Science page. There are no write tools, no skin-type or suitability
tool and no recommendations. Never print to stdout here: stdout carries the protocol.
"""
import functools
import os
import sys

# `python mcp_server/server.py` puts only this folder on sys.path; the project root is needed too
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Annotated  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402

from content import avoid_list as avoid_content  # noqa: E402
from content import mcp_text as text  # noqa: E402
from database import services  # noqa: E402
from database.db import DB_PATH, read_only_uri  # noqa: E402

mcp = FastMCP(
    "skin-index",
    instructions=(
        "Read-only tools over the Skin Index data: a March 2023 Sephora US product snapshot plus "
        "live UV, humidity and air quality, and PubMed paper lists. The tools list facts and "
        "numbers only. They never rank products, never say what suits a skin type, and finding "
        "no match never means a product is fine."
    ),
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
READ_ONLY_LIVE = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

BRIEF_FIELDS = ("id", "name", "brand", "compare_group", "size_text", "price")


class _Problem(Exception):
    """A message for the person asking; shown as the tool's error."""


def _product_db():
    """The product database, opened read-only. SKIN_INDEX_DB overrides the default file."""
    path = os.environ.get("SKIN_INDEX_DB") or DB_PATH
    if not os.path.exists(path):
        raise _Problem("The product database was not found. Run `python -m database.load_data` first.")
    return read_only_uri(path)


def _cache_db():
    """The same file as a normal path, for the one tool that saves a PubMed result."""
    return os.environ.get("SKIN_INDEX_DB") or DB_PATH


def _id(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 2**63:
        raise _Problem(text.MESSAGES["bad_id"].format(name=name))
    return value


def _optional_text(value, name):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _Problem(text.MESSAGES["bad_text"].format(name=name))
    return value.strip()


def _answer(source, data, note=None):
    answer = {"source": text.SOURCES[source], "data": data}
    if note:
        answer["note"] = note
    return answer


def _tool(description, annotations=READ_ONLY):
    """Register a tool: inputs problems and failures become a plain {"error": ...} answer."""
    def register(function):
        @functools.wraps(function)
        def guarded(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except _Problem as problem:
                return {"error": str(problem)}
            except Exception:  # never show a traceback or an internal detail to the caller
                return {"error": text.MESSAGES["failed"]}
        mcp.tool(description=description, annotations=annotations)(guarded)
        return guarded
    return register


@_tool(
    "List products by text in the name or brand, by comparison group (a parent such as Sunscreen also "
    "matches its subgroups) and by an ingredient word that appears as a whole word in the brand's own "
    "ingredient list. All filters are optional; at most 25 products come back, sorted by name, with USD "
    "prices and the number of matches. Use list_groups for group names. Lists products only: no ranking."
)
def search_products(
    query: Annotated[str, Field(description="Text in the product name or brand, e.g. 'cleanser'. Empty means any.")] = "",
    group: Annotated[str, Field(description="Exact comparison group name from list_groups, e.g. 'Face Serums'.")] = "",
    ingredient: Annotated[str, Field(description="One ingredient word or phrase, e.g. 'niacinamide'. Whole words only.")] = "",
    limit: Annotated[int, Field(description="How many products to return, 1 to 25.")] = 10,
):
    query, group = _optional_text(query, "query"), _optional_text(group, "group")
    ingredient = _optional_text(ingredient, "ingredient")
    result = services.search_products(query, group, ingredient, limit, db_path=_product_db())
    if result["status"] == "invalid_ingredient":
        raise _Problem(text.MESSAGES["bad_ingredient"])
    return _answer("products", {"total_matches": result["total"], "shown": len(result["products"]),
                                "products": result["products"]})


@_tool(
    "One product's facts: name, brand, category, comparison group, size, USD price and price per ml, likes, "
    "rating and reviews from the retailer's site (March 2023), and its ingredients in label order, each "
    "with the strength only when the brand printed one. Missing values come back as null (not available)."
)
def get_product_detail(
    product_id: Annotated[int, Field(description="The product id, from search_products.")],
):
    product = services.get_product_detail(_id(product_id, "product_id"), db_path=_product_db())
    if product is None:
        raise _Problem(text.MESSAGES["no_product"].format(id=product_id))
    return _answer("products", product, text.NOTES["ingredients"])


@_tool(
    "Put two products side by side: both products' numbers and the ingredients both have, only in A and "
    "only in B. Any two products in the same comparison group can be compared; otherwise the answer says why "
    "not. The main ingredient groups each product is in are listed as information only. No verdict, no "
    "winner, no overlap score."
)
def compare_products(
    product_a_id: Annotated[int, Field(description="Id of the first product.")],
    product_b_id: Annotated[int, Field(description="Id of the second product.")],
):
    a_id, b_id = _id(product_a_id, "product_a_id"), _id(product_b_id, "product_b_id")
    result = services.compare_products(a_id, b_id, db_path=_product_db())
    for side, product_id in (("a", a_id), ("b", b_id)):
        if result[f"{side}_state"] == "unknown":
            raise _Problem(text.MESSAGES["no_product"].format(id=product_id))

    labels = services.MAIN_INGREDIENT_LABELS
    names = lambda keys: ", ".join(labels[k] for k in keys) or "none"  # noqa: E731
    status = result["status"]
    message = text.COMPARE_MESSAGES[status].format(
        a_group=result["a_group"], b_group=result["b_group"],
        a_main=names(result["a_main"]), b_main=names(result["b_main"]), shared=names(result["shared_main"]),
    )
    # a pair that cannot be compared shows no per-ml, likes, ratings or reviews, as the page does
    fields = BRIEF_FIELDS + (("price_per_ml", "loves_count", "rating", "reviews") if result["comparable"] else ())
    data = {
        "status": status, "comparable": result["comparable"], "message": message,
        "a": {**{k: result["a"][k] for k in fields}, "main_ingredient_groups": [labels[k] for k in result["a_main"]]},
        "b": {**{k: result["b"][k] for k in fields}, "main_ingredient_groups": [labels[k] for k in result["b_main"]]},
    }
    if result["comparable"]:
        data["shared_main_ingredient_groups"] = [labels[k] for k in result["shared_main"]]
        data["ingredients"] = result["ingredients"]
    return _answer("products", data, text.NOTES["compare"])


@_tool(
    "Shopper engagement from one retailer's site (likes, ratings, reviews; not sales): the most liked brands "
    "(always over every product) and the most liked products, overall or within one group with at least 5 "
    "products. Numbers only, no judgement of quality."
)
def get_insights(
    group: Annotated[str, Field(description="A group name from list_groups to focus the products on. Empty means overall.")] = "",
):
    group = _optional_text(group, "group")
    result = services.get_insights(group or None, db_path=_product_db())
    if result["group_status"] == "unavailable":
        raise _Problem(text.MESSAGES["unknown_group"].format(
            group=group, min=services.INSIGHTS_CONFIG["min_group_products"]) + " " + ", ".join(
            g["name"] for g in result["selector_groups"]))
    data = {"group": result["scope_group"], "most_liked_brands": result["brands"],
            "most_liked_products": result["loved_products"]}
    return _answer("insights", data, text.NOTES["insights"])


@_tool(
    "The comparison groups that have at least 2 products, each with its product count. Use a name here as "
    "the group in search_products or get_insights."
)
def list_groups():
    return _answer("products", {"groups": services.list_groups(_product_db())})


@_tool(
    "Today's UV index (now and the day's peak), humidity, temperature and US air quality index for one "
    "place, as information only. Give a city name, or latitude and longitude (both), or both. With "
    "coordinates, those exact coordinates are used. With only a city name, the first match of the place "
    "search is used; add country and/or region (e.g. 'India', 'Maharashtra') to narrow the match. The answer "
    "always says which place was used (name, region, country, coordinates, in `place` and `place_used`) and "
    "names up to 2 other matches in `other_matches`. Conditions come back in the same call. Live data; "
    "values that are missing come back as not available.",
    READ_ONLY_LIVE,
)
def get_weather(
    city: Annotated[str, Field(description="A city name, e.g. 'Pune' or 'Lisbon'. Optional when latitude and longitude are given.")] = "",
    country: Annotated[str, Field(description="Optional country name to narrow a city name, e.g. 'India'.")] = "",
    region: Annotated[str, Field(description="Optional region or state name to narrow a city name, e.g. 'Maharashtra'.")] = "",
    latitude: Annotated[float | None, Field(description="Optional latitude, -90 to 90. Use together with longitude; the place search is then skipped.")] = None,
    longitude: Annotated[float | None, Field(description="Optional longitude, -180 to 180. Use together with latitude.")] = None,
):
    for value in (city, country, region):
        if not isinstance(value, str):
            raise _Problem(text.MESSAGES["bad_city"])
    result = services.get_weather_report(city, country, region, latitude, longitude)
    status = result["status"]
    if status == "invalid":
        raise _Problem(text.MESSAGES["bad_city"])
    if status == "no_match":
        raise _Problem(text.MESSAGES["no_place"])
    if status == "unavailable":
        raise _Problem(text.MESSAGES["weather_down"])
    return _answer("weather", result, text.NOTES["weather"])


@_tool(
    "A list of published PubMed papers (up to 10: title, journal, year, kind of paper, link) for the search "
    "'<ingredient> AND skin'. It lists papers only: it says nothing about whether an ingredient works. "
    "Results are saved for 24 hours.",
    READ_ONLY_LIVE,
)
def find_studies(
    ingredient: Annotated[str, Field(description="An ingredient name, e.g. 'niacinamide'.")],
    reviews_only: Annotated[bool, Field(description="True keeps only overview papers and combined analyses.")] = False,
):
    if not isinstance(ingredient, str):
        raise _Problem(text.MESSAGES["bad_ingredient_study"])
    result = services.search_research(ingredient, bool(reviews_only), db_path=_cache_db())
    if result["status"] == "invalid":
        raise _Problem(text.MESSAGES["bad_ingredient_study"])
    if result["status"] == "unavailable":
        raise _Problem(text.MESSAGES["studies_down"])
    data = {"query": result["query"], "reviews_only": result["reviews_only"], "papers": result["papers"],
            "result_origin": result["source"], "fetched_at": result["fetched_at"]}
    return _answer("studies", data, text.NOTES["studies"])


@_tool(
    "Check one product's ingredient list for words you want to avoid. Each word or phrase is matched as "
    "whole words in the brand's own ingredient text, ignoring capital letters; fragrance/parfum and "
    "water/aqua/eau are the only synonyms. Returns which words were found and in which ingredient names. "
    "Not found only means nothing on the list matched. The words are used for this call and never stored."
)
def check_avoid_list(
    product_id: Annotated[int, Field(description="The product id, from search_products.")],
    words: Annotated[list[str], Field(description="Ingredient words to look for, 1 to 20, e.g. ['fragrance', 'alcohol'].")],
):
    product_id = _id(product_id, "product_id")
    if not isinstance(words, list) or not 0 < len(words) <= avoid_content.MAX_TERMS:
        raise _Problem(text.MESSAGES["bad_words"].format(max=avoid_content.MAX_TERMS))
    terms = services.clean_avoid_terms(words)
    if not terms:
        raise _Problem(text.MESSAGES["no_usable_words"])
    result = services.check_product_avoid_list(terms, product_id, db_path=_product_db())
    if result is None:
        raise _Problem(text.MESSAGES["no_product"].format(id=product_id))
    result["message"] = {"not_found": avoid_content.NOT_FOUND,
                         "no_ingredients": avoid_content.NO_INGREDIENTS}.get(result["status"])
    return _answer("products", result, text.NOTES["avoid_list"] + " " + text.NOTES["ingredients"])


@_tool(
    "Two product types of one group side by side, from the same numbers as the Compare page. A type is a "
    "whole word in the product name (for example 'cream' or 'gel'); products whose names contain both words "
    "are left out of both sides and counted in `left_out`. Each side has its product count, USD price min, "
    "median and max, the review-weighted average rating, the most common ingredients (Water apart) and, for "
    "the few types with a named source, a short line on what the word usually means. Each type needs at least "
    "the minimum number of products. With no input, or with a group or type that can't be compared, the "
    "answer is a plain status and `valid_choices`, the groups and type pairs that can be compared. No "
    "verdict is made."
)
def compare_types(
    group: Annotated[str, Field(description="Group name, e.g. 'Moisturizers'.")] = "",
    type_a: Annotated[str, Field(description="First type word, e.g. 'cream'.")] = "",
    type_b: Annotated[str, Field(description="Second type word, e.g. 'gel'.")] = "",
):
    group, type_a, type_b = (_optional_text(v, n) for v, n in ((group, "group"), (type_a, "type_a"), (type_b, "type_b")))
    type_a, type_b = type_a.lower(), type_b.lower()
    db = _product_db()
    listing = services.list_format_types(db_path=db)
    result = services.compare_types(group, type_a, type_b, db_path=db)
    status = result["status"]
    if status != "ok":
        data = {"status": status, "minimum_products": listing["min_products"],
                "valid_choices": [{"group": g["name"], "types": [t["key"] for t in g["types"]],
                                   "pairs": g["pairs"]} for g in listing["groups"]]}
        if status == "too_few":
            short = min((result["a"], result["b"]), key=lambda s: s["products"])
            data["message"] = text.TYPE_MESSAGES["too_few"].format(
                label=short["label"], n=short["products"], products="product" if short["products"] == 1 else "products",
                group=result["group"], min=result["min_products"])
            data["a"] = {"type": result["a"]["key"], "products": result["a"]["products"]}
            data["b"] = {"type": result["b"]["key"], "products": result["b"]["products"]}
            data["left_out"] = result["left_out"]["products"]
        else:
            data["message"] = text.TYPE_MESSAGES[status]
        return _answer("products", data, text.NOTES["compare_types"])
    data = {"status": "ok", "group": result["group"], "minimum_products": result["min_products"],
            "left_out": {"products": result["left_out"]["products"], "words": result["left_out"]["words"]}}
    for side in ("a", "b"):
        s = result[side]
        data[side] = {
            "type": s["key"], "word": s["word"], "products": s["products"],
            "price_usd": s["price"] and {k: s["price"][k] for k in ("min", "median", "max")},
            "average_rating": s["rating"] and round(s["rating"], 2),
            "rated_products": s["rated_products"],
            "most_common_ingredients": s["ingredients"]["top"],
            "water": s["ingredients"]["water"],
            "products_with_ingredient_list": s["ingredients"]["products"],
            "format_line": s["format_line"] and {k: s["format_line"][k] for k in ("text", "source_name", "source_url")},
        }
    return _answer("products", data, text.NOTES["compare_types"] + " " + text.NOTES["ingredients"])


if __name__ == "__main__":
    mcp.run(transport="stdio")
