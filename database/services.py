import json
import math
import re
import time
from collections import namedtuple
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from content import science as science_content
from content import ingredient_cards as cards_content
from content import main_ingredients as main_ingredients_content
from content import science as science_content
from database.db import get_db, init_db
from live.currency import CurrencyError, fetch_usd_inr
from live.pubmed import PubmedError, count_pubmed, search_pubmed, topic_query
from live.weather import WeatherError, fetch_air_quality, fetch_forecast, search_places

# stale is True when the rate is older than today's and today's fetch failed
RateInfo = namedtuple("RateInfo", ["rate", "rate_date", "stale"])

# After a failed fetch, do not try again for a while: otherwise an API outage
# would cost every page load a full request timeout.
RETRY_AFTER_FAILURE_SECONDS = 15 * 60
_last_failure = None  # time.monotonic() of the last failed fetch


def reset_rate_cooldown():
    global _last_failure
    _last_failure = None


def get_usd_inr_rate(db_path=None, today=None):
    """Return a RateInfo for 1 USD in INR, or None if no rate was ever saved.

    A rate already fetched today is returned without any network call. Otherwise
    the rate is fetched and saved; if that fails, the newest saved rate comes back
    marked stale. A rate is never made up.
    """
    global _last_failure
    today = today or date.today().isoformat()
    init_db(db_path)  # databases created before exchange_rates existed get the table
    with closing(get_db(db_path)) as conn:
        saved = conn.execute(
            "SELECT rate, rate_date, fetched_on FROM exchange_rates"
            " WHERE base = 'USD' AND quote = 'INR'"
            " ORDER BY rate_date DESC, fetched_on DESC LIMIT 1"
        ).fetchone()
        if saved and saved["fetched_on"] == today:
            return RateInfo(saved["rate"], saved["rate_date"], False)

        cooling_down = (
            _last_failure is not None
            and time.monotonic() - _last_failure < RETRY_AFTER_FAILURE_SECONDS
        )
        if not cooling_down:
            try:
                rate, rate_date = fetch_usd_inr()
            except CurrencyError:
                _last_failure = time.monotonic()
            else:
                _last_failure = None
                with conn:
                    conn.execute(
                        "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                        " VALUES (?, 'USD', 'INR', ?, ?)"
                        " ON CONFLICT (base, quote, rate_date)"
                        " DO UPDATE SET rate = excluded.rate, fetched_on = excluded.fetched_on",
                        (rate_date, rate, today),
                    )
                return RateInfo(rate, rate_date, False)

        if saved:
            return RateInfo(saved["rate"], saved["rate_date"], True)
        return None


def get_product_detail(product_id, db_path=None):
    """One product as a dict with its ingredients in label order, or None if unknown.

    `ingredients` is a list of {"name", "stated_percent"}; stated_percent is the
    number the brand printed, or None when it printed none. Fields that are
    missing in the database come back as None, and `ingredients` is an empty list
    when the product has none.
    """
    init_db(db_path)  # databases from before compare_group existed get the column
    with closing(get_db(db_path)) as conn:
        loaded = _load_product(conn, product_id)
    if loaded is None:
        return None
    product, ingredients = loaded
    return {
        **product,
        "ingredients": [
            {"name": row["name"], "stated_percent": row["stated_percent"]} for row in ingredients
        ],
    }


def _load_product(conn, product_id):
    """(product row as a dict, ingredient rows with ids in label order), or None if unknown."""
    if isinstance(product_id, bool) or not isinstance(product_id, int) or not 0 < product_id < 2**63:
        return None  # not a usable id (SQLite would raise on integers beyond 64 bits)
    product = conn.execute(
        "SELECT id, name, brand, category, compare_group, size_text, price, price_per_ml,"
        " loves_count, rating, reviews FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        return None
    ingredients = conn.execute(
        "SELECT i.id AS ingredient_id, i.name, pi.stated_percent FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id"
        " WHERE pi.product_id = ? ORDER BY pi.position",
        (product_id,),
    ).fetchall()
    return dict(product), [dict(row) for row in ingredients]


def escape_like(text):
    """Make %, _ and \\ in user text match literally inside LIKE ... ESCAPE '\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ------------------------------------------------------------------ #
# Compare: groups, main ingredients, dropdown lists and the comparison #
# ------------------------------------------------------------------ #

def _compile(patterns):
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


_MAIN_PATTERNS = [
    (entry["key"], _compile(entry["name_patterns"]), _compile(entry["ingredient_patterns"]))
    for entry in main_ingredients_content.MAIN_INGREDIENTS
]
MAIN_INGREDIENT_LABELS = {entry["key"]: entry["label"] for entry in main_ingredients_content.MAIN_INGREDIENTS}


def main_ingredients_of(product_name, ingredient_names):
    """The main ingredient groups (keys, in the order of the content file) a product belongs to.

    A product belongs to a group when the group's ingredient is in its name or among its first
    TOP_N listed ingredients (`ingredient_names` in label order). It can belong to several.
    """
    top = list(ingredient_names or [])[:main_ingredients_content.TOP_N]
    name = product_name or ""
    return [
        key for key, name_patterns, ingredient_patterns in _MAIN_PATTERNS
        if any(p.search(name) for p in name_patterns)
        or any(p.search(i) for p in ingredient_patterns for i in top)
    ]


def _group_products(conn, group):
    """Every product in a comparison group with its main ingredient groups: [{..., "main"}]."""
    products = [dict(row) for row in conn.execute(
        "SELECT id, name, brand, size_text, price FROM products WHERE compare_group = ?"
        " ORDER BY name COLLATE NOCASE, brand COLLATE NOCASE, id",
        (group,),
    )]
    top_ingredients = {}
    for row in conn.execute(
        "SELECT product_id, name FROM ("
        " SELECT pi.product_id, i.name, ROW_NUMBER() OVER (PARTITION BY pi.product_id ORDER BY pi.position) AS n"
        " FROM product_ingredients pi JOIN ingredients i ON i.id = pi.ingredient_id"
        " JOIN products p ON p.id = pi.product_id WHERE p.compare_group = ?"
        ") WHERE n <= ? ORDER BY product_id, n",
        (group, main_ingredients_content.TOP_N),
    ):
        top_ingredients.setdefault(row["product_id"], []).append(row["name"])
    for product in products:
        product["main"] = main_ingredients_of(product["name"], top_ingredients.get(product["id"], []))
    return products


def list_groups(db_path=None):
    """Comparison groups that have at least two products, by name: [{"name", "products"}]."""
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        rows = conn.execute(
            "SELECT compare_group AS name, COUNT(*) AS products FROM products"
            " WHERE compare_group IS NOT NULL GROUP BY compare_group HAVING COUNT(*) >= 2"
            " ORDER BY compare_group COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def list_group_ingredients(group, db_path=None):
    """The main ingredient groups with at least one product in a comparison group, in the order of
    the content file: [{"key", "label", "products"}]. A count under 2 means nothing to compare."""
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        products = _group_products(conn, group)
    counts = {key: sum(key in p["main"] for p in products) for key in MAIN_INGREDIENT_LABELS}
    return [
        {"key": key, "label": label, "products": counts[key]}
        for key, label in MAIN_INGREDIENT_LABELS.items() if counts[key]
    ]


def list_products_in_group(group, ingredient, exclude_id=None, db_path=None):
    """Products of a comparison group that belong to one main ingredient group, for a dropdown.

    Returns [{"id", "name", "brand", "size_text", "price"}] sorted by name; `ingredient` is a key
    of the content file (an unknown key lists nothing); `exclude_id` leaves one product out.
    """
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        products = _group_products(conn, group)
    return [
        {k: p[k] for k in ("id", "name", "brand", "size_text", "price")}
        for p in products if ingredient in p["main"] and p["id"] != exclude_id
    ]


def compare_products(a_id, b_id, db_path=None):
    """Compare two products; plain data only (no formatting, no currency).

    Returns {"a", "b", "a_state", "b_state", "status", "comparable", "a_group", "b_group",
    "a_main", "b_main", "shared_main", "ingredients"}.
    - a, b: the product as in get_product_detail, or None.
    - a_state, b_state: "not chosen" (id None), "unknown" (no such product) or "found".
    - a_main, b_main: the main ingredient groups (keys) each found product belongs to (else []);
      shared_main: the ones both belong to, in the order of the content file.
    - status: "waiting" (a side is not found), "same_product", "no_group" (a product has no
      comparison group), "different_groups", "no_main_ingredient" (a product belongs to no main
      ingredient group), "different_ingredients" (no main ingredient group in common) or "ok".
      comparable is True only for "ok": the same comparison group and a main ingredient group in common.
    - ingredients (comparable, both with ingredients, else None): {"shared", "only_a", "only_b"}
      as ingredient names in label order (shared in A's order), plus the three counts.
    No verdict is made: the data has no amounts and no product is called better than another.
    """
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        loaded = {"a": _load_product(conn, a_id), "b": _load_product(conn, b_id)}

    def state(side, product_id):
        if product_id is None:
            return "not chosen"
        return "found" if loaded[side] is not None else "unknown"

    states = {"a": state("a", a_id), "b": state("b", b_id)}
    products, rows, main = {}, {}, {}
    for side in ("a", "b"):
        if loaded[side] is None:
            products[side], rows[side], main[side] = None, [], []
        else:
            product, ingredient_rows = loaded[side]
            rows[side] = ingredient_rows
            main[side] = main_ingredients_of(product["name"], [r["name"] for r in ingredient_rows])
            products[side] = {
                **product,
                "ingredients": [
                    {"name": r["name"], "stated_percent": r["stated_percent"]} for r in ingredient_rows
                ],
            }
    a, b = products["a"], products["b"]
    shared_main = [key for key in main["a"] if key in main["b"]]
    result = {
        "a": a, "b": b, "a_state": states["a"], "b_state": states["b"],
        "a_group": a and a["compare_group"], "b_group": b and b["compare_group"],
        "a_main": main["a"], "b_main": main["b"], "shared_main": shared_main,
        "status": None, "comparable": False, "ingredients": None,
    }
    if a is None or b is None:
        result["status"] = "waiting"
    elif a["id"] == b["id"]:
        result["status"] = "same_product"
    elif a["compare_group"] is None or b["compare_group"] is None:
        result["status"] = "no_group"
    elif a["compare_group"] != b["compare_group"]:
        result["status"] = "different_groups"
    elif not main["a"] or not main["b"]:
        result["status"] = "no_main_ingredient"
    elif not shared_main:
        result["status"] = "different_ingredients"
    else:
        result["status"] = "ok"
        result["comparable"] = True
        result["ingredients"] = _compare_ingredients(rows["a"], rows["b"])
    return result


def _compare_ingredients(a_rows, b_rows):
    if not a_rows or not b_rows:
        return None
    a_ids = {r["ingredient_id"] for r in a_rows}
    b_ids = {r["ingredient_id"] for r in b_rows}
    shared = [r["name"] for r in a_rows if r["ingredient_id"] in b_ids]
    only_a = [r["name"] for r in a_rows if r["ingredient_id"] not in b_ids]
    only_b = [r["name"] for r in b_rows if r["ingredient_id"] not in a_ids]
    return {
        "shared": shared, "only_a": only_a, "only_b": only_b,
        "shared_count": len(shared), "only_a_count": len(only_a), "only_b_count": len(only_b),
    }


# ------------------------------------------------------------------ #
# Insights                                                            #
# ------------------------------------------------------------------ #

# Every threshold the Insights page uses, in one place; the page states them
INSIGHTS_CONFIG = {
    "min_group_products": 5,          # a group needs this many products to be offered
    "top_n": 10,                      # length of the brand, product, well-reviewed and ingredient lists
    "well_reviewed_min_reviews": 50,  # well-reviewed list: at least this many reviews...
    "well_reviewed_min_rating": 4.0,  # ...and a rating of at least this
    "band_min_reviews": 10,           # price bands: a product needs this many reviews to count
    "band_min_products": 9,           # price bands: a group needs this many such products (3 per band)
}
BAND_LABELS = ("lower", "middle", "higher")


def weighted_rating(pairs):
    """Review-weighted average rating: sum(rating * reviews) / sum(reviews).

    `pairs` are (rating, reviews). A product missing either value, or with no reviews,
    is skipped; None when nothing is left.
    """
    usable = [(rating, reviews) for rating, reviews in pairs if rating is not None and reviews]
    total = sum(reviews for _, reviews in usable)
    return sum(rating * reviews for rating, reviews in usable) / total if total else None


def _ingredient_summary(conn, group=None):
    """Top ingredients by share of products, with Water counted apart from the ranking.

    Counts products in the group (all products when group is None) that have an
    ingredient list; share_percent is the share of those products.
    """
    scope = {"group": group}
    total = conn.execute(
        "SELECT COUNT(DISTINCT pi.product_id) FROM product_ingredients pi"
        " JOIN products p ON p.id = pi.product_id"
        " WHERE (:group IS NULL OR p.compare_group = :group)",
        scope,
    ).fetchone()[0]
    ranked = conn.execute(
        "SELECT i.name, COUNT(DISTINCT pi.product_id) AS products FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id JOIN products p ON p.id = pi.product_id"
        " WHERE (:group IS NULL OR p.compare_group = :group) AND LOWER(i.name) != 'water'"
        " GROUP BY i.id ORDER BY products DESC, i.name COLLATE NOCASE LIMIT :limit",
        {**scope, "limit": INSIGHTS_CONFIG["top_n"]},
    ).fetchall()
    water = conn.execute(
        "SELECT COUNT(DISTINCT pi.product_id) FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id JOIN products p ON p.id = pi.product_id"
        " WHERE (:group IS NULL OR p.compare_group = :group) AND LOWER(i.name) = 'water'",
        scope,
    ).fetchone()[0]

    def share(count):
        return count / total * 100 if total else None

    return {
        "products": total,
        "top": [{"name": r["name"], "products": r["products"], "share_percent": share(r["products"])}
                for r in ranked],
        "water": {"products": water, "share_percent": share(water)},
    }


def _price_bands(products):
    """Three equal-size bands (lower, middle, higher price per ml) with their weighted rating.

    `products` already have a price per ml, a rating and enough reviews. With a remainder
    the lower bands get the extra product first; equal prices are ordered by id.
    """
    config = INSIGHTS_CONFIG
    ordered = sorted(products, key=lambda p: (p["price_per_ml"], p["id"]))
    if len(ordered) < config["band_min_products"]:
        return {"enough": False, "eligible_products": len(ordered), "bands": []}
    base, extra = divmod(len(ordered), 3)
    bands, start = [], 0
    for index, label in enumerate(BAND_LABELS):
        size = base + (1 if index < extra else 0)
        chunk = ordered[start:start + size]
        start += size
        bands.append({
            "label": label, "products": len(chunk),
            "reviews": sum(p["reviews"] for p in chunk),
            "average_rating": weighted_rating((p["rating"], p["reviews"]) for p in chunk),
        })
    return {"enough": True, "eligible_products": len(ordered), "bands": bands}


def get_insights(group=None, db_path=None):
    """Numbers for the Insights page; plain data only (no formatting, HTML or currency).

    Popularity is shopper engagement from one retailer's site (likes, ratings, reviews),
    not sales. Prices are USD. Ties are broken by name. A product missing a value a
    section needs is skipped by that section, never counted as zero.

    Returns {"config", "requested_group", "group_status", "scope_group", "overview",
    "selector_groups", "brands", "loved_products", "well_reviewed", "price_bands",
    "ingredients"}:
    - config: INSIGHTS_CONFIG (the thresholds used).
    - group_status: "none" (no group asked for), "ok", or "unavailable" (unknown group,
      or fewer products than the minimum); scope_group is the group when "ok", else None.
    - overview: {"products", "brands", "groups", "ungrouped_products"} over all products.
    - selector_groups: [{"name", "products"}] by name, groups with enough products.
    - brands (always overall): top brands by total likes, [{"brand", "loves", "products",
      "average_rating", "rated_reviews"}]; average_rating is review-weighted.
    - loved_products: top products by likes, overall or within the group: [{"id", "name",
      "brand", "price", "size_text", "loves_count", "rating", "reviews"}].
    - well_reviewed (group only, else None): {"qualifying_products", "products": [{"id",
      "name", "brand", "price", "price_per_ml", "rating", "reviews"}]}, products with
      enough reviews and a high enough rating, lowest price per ml first.
    - price_bands (group only, else None): {"enough", "eligible_products", "bands": [{"label",
      "products", "reviews", "average_rating"}]} for products with a price per ml and
      enough reviews.
    - ingredients: {"products", "top": [{"name", "products", "share_percent"}], "water":
      {"products", "share_percent"}}, overall or within the group.
    """
    config = INSIGHTS_CONFIG
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, brand, price, size_text, price_per_ml, compare_group,"
            " loves_count, rating, reviews FROM products"
        )]
        group_sizes = {}
        for row in rows:
            if row["compare_group"] is not None:
                group_sizes[row["compare_group"]] = group_sizes.get(row["compare_group"], 0) + 1
        selector = sorted(
            ({"name": name, "products": n} for name, n in group_sizes.items()
             if n >= config["min_group_products"]),
            key=lambda g: g["name"].casefold(),
        )
        status = "none"
        if group is not None:
            status = "ok" if any(g["name"] == group for g in selector) else "unavailable"
        scope_group = group if status == "ok" else None
        scope = [r for r in rows if r["compare_group"] == scope_group] if scope_group else rows
        ingredients = _ingredient_summary(conn, scope_group)

    # brands, always over every product
    by_brand = {}
    for row in rows:
        by_brand.setdefault(row["brand"], []).append(row)
    brands = []
    for brand, items in by_brand.items():
        loves = [r["loves_count"] for r in items if r["loves_count"] is not None]
        if not loves:
            continue
        brands.append({
            "brand": brand, "loves": sum(loves), "products": len(items),
            "average_rating": weighted_rating((r["rating"], r["reviews"]) for r in items),
            "rated_reviews": sum(r["reviews"] for r in items if r["rating"] is not None and r["reviews"]),
        })
    brands.sort(key=lambda b: (-b["loves"], b["brand"].casefold()))

    loved = sorted((r for r in scope if r["loves_count"] is not None),
                   key=lambda r: (-r["loves_count"], r["name"].casefold(), r["id"]))
    loved_products = [
        {key: r[key] for key in ("id", "name", "brand", "price", "size_text", "loves_count", "rating", "reviews")}
        for r in loved[:config["top_n"]]
    ]

    well_reviewed = price_bands = None
    if scope_group:
        qualifying = sorted(
            (r for r in scope if r["price_per_ml"] is not None and r["rating"] is not None
             and r["reviews"] is not None
             and r["reviews"] >= config["well_reviewed_min_reviews"]
             and r["rating"] >= config["well_reviewed_min_rating"]),
            key=lambda r: (r["price_per_ml"], r["name"].casefold(), r["id"]),
        )
        well_reviewed = {
            "qualifying_products": len(qualifying),
            "products": [
                {key: r[key] for key in ("id", "name", "brand", "price", "price_per_ml", "rating", "reviews")}
                for r in qualifying[:config["top_n"]]
            ],
        }
        price_bands = _price_bands([
            r for r in scope if r["price_per_ml"] is not None and r["rating"] is not None
            and r["reviews"] is not None and r["reviews"] >= config["band_min_reviews"]
        ])

    return {
        "config": dict(config),
        "requested_group": group,
        "group_status": status,
        "scope_group": scope_group,
        "overview": {
            "products": len(rows),
            "brands": len(by_brand),
            "groups": len(group_sizes),
            "ungrouped_products": sum(1 for r in rows if r["compare_group"] is None),
        },
        "selector_groups": selector,
        "brands": brands[:config["top_n"]],
        "loved_products": loved_products,
        "well_reviewed": well_reviewed,
        "price_bands": price_bands,
        "ingredients": ingredients,
    }


# ------------------------------------------------------------------ #
# Today: live conditions for a city                                   #
# ------------------------------------------------------------------ #

# Every threshold and category label the Today page uses. UV and AQI are rounded half up to
# whole numbers before they are put in a category (public UV index values are whole numbers).
TODAY_CONFIG = {
    "default_place": {"name": "Pune", "region": "Maharashtra", "country": "India",
                      "latitude": 18.51957, "longitude": 73.85535},
    "uv_categories": [(2, "Low"), (5, "Moderate"), (7, "High"), (10, "Very high"), (None, "Extreme")],
    "aqi_categories": [
        (50, "Good"), (100, "Moderate"), (150, "Unhealthy for sensitive groups"),
        (200, "Unhealthy"), (300, "Very unhealthy"), (None, "Hazardous"),
    ],
    "sun_protection_from_uv": 3,     # UV at which an hour joins the timeline, the extra steps start and the sunscreen link shows
    "very_high_from_uv": 8,          # the stronger extra steps start here
    "very_low_below_uv": 1,          # below this peak UV (whole number) the UV card only says UV is very low
    "advisory_above_aqi": 100,       # "check local health advisories" above Moderate
    "cool_at_or_below_c": 15,        # cool-or-dry tips: temperature at or below this (Celsius)...
    "dry_at_or_below_percent": 35,   # ...or relative humidity at or below this
    "hot_at_or_above_c": 30,         # hot-and-humid tips: temperature at or above this...
    "humid_at_or_above_percent": 60, # ...and relative humidity at or above this
    "max_city_length": 60,
    "max_label_length": 100,
}


def whole_number(value):
    """A number rounded half up to a whole int (2.5 -> 3)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def category_for(value, categories):
    """The label for a whole-number value; categories are (highest value in it or None, label)."""
    for highest, label in categories:
        if highest is None or value <= highest:
            return label


def clean_place_text(text, max_length, allow_parentheses=False):
    """A city (or place label) as plain text, or None if it is unusable.

    Spaces are collapsed. Only letters, digits, spaces, hyphens, apostrophes, commas and full
    stops are kept (plus brackets for a label); anything that could be a link, markup or a
    path ("/", ":", "<", "%", "http", "www", "a.b") is refused.
    """
    if not isinstance(text, str):
        return None
    text = re.sub(r"\s+", " ", text).strip()
    if not 2 <= len(text) <= max_length:
        return None
    allowed = r"[\w .,'’()\-]+" if allow_parentheses else r"[\w .,'’\-]+"  # includes the curly apostrophe
    if not re.fullmatch(allowed, text) or "_" in text or not any(c.isalnum() for c in text):
        return None
    if re.search(r"\w\.\w", text) or text.casefold().startswith(("www", "http")):
        return None
    return text


def parse_coordinates(latitude, longitude):
    """(latitude, longitude) as floats, or None unless both are finite and in range."""
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            return None
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _hour_label(moment):
    return moment.strftime("%H:%M")


def uv_timeline(hourly):
    """The hours today with a UV index of 3 or higher, and the peak hour.

    `hourly` is [{"time", "uv"}], each value the average of the hour ending at "time", so each
    entry covers the hour before its time. Values are put in whole numbers (half up) before they
    are compared with the threshold, and touching hours are joined into one range.
    Returns {"available", "reaches", "ranges": [{"from", "to"}], "peak": {"from", "to", "uv"} or None}.
    """
    if not hourly:
        return {"available": False, "reaches": False, "ranges": [], "peak": None}
    advised_from = TODAY_CONFIG["sun_protection_from_uv"]
    spans = []
    for entry in hourly:
        end = datetime.strptime(entry["time"], "%Y-%m-%dT%H:%M")
        spans.append((end - timedelta(hours=1), end, whole_number(entry["uv"]), entry["uv"]))
    ranges = []
    for start, end, uv, _raw in spans:
        if uv < advised_from:
            continue
        if ranges and ranges[-1][1] == start:
            ranges[-1][1] = end
        else:
            ranges.append([start, end])
    start, end, uv, _raw = max(spans, key=lambda s: (s[3], -s[0].timestamp()))   # the first of equal highest hours
    return {
        "available": True,
        "reaches": bool(ranges),
        "ranges": [{"from": _hour_label(a), "to": _hour_label(b)} for a, b in ranges],
        "peak": {"from": _hour_label(start), "to": _hour_label(end), "uv": uv},
    }


def get_today_conditions(city=None, latitude=None, longitude=None, label=None):
    """Live conditions for a place, as plain data (numbers, category names, flags; no HTML, no texts).

    The place is, in order: coordinates (with an optional label), a city name looked up with
    the geocoding service, or the default place. The values are information only; no value is
    ever made up, so anything the services could not give is None and listed in "missing".

    Returns {"status", "query", "place", "choices", "local_time", "uv", "humidity",
    "temperature_c", "aqi", "timeline", "guidance", "tips", "missing"}:
    - status: "ok" (some or all conditions found), "choose" (several places match; see choices),
      "no_match", "invalid" (unusable city text or coordinates) or "unavailable" (a service
      could not be reached and nothing could be shown).
    - place / choices: {"name", "region", "country", "latitude", "longitude"}; choices has up to 5.
    - uv: {"now", "now_category", "max", "max_category"} in whole numbers, or None.
    - aqi: {"value", "category", "pm2_5"} or None. humidity is a percent, temperature_c is Celsius.
    - timeline: uv_timeline() of today's hourly UV.
    - guidance: {"uv_card", "extra_steps", "show_sunscreen_link", "check_advisories"}. All the UV
      fields depend on today's peak UV (UV now if there is no peak), as a whole number: uv_card is
      "full" (3 or higher), "low" (1 to 2), "very_low" (below 1) or None when no UV is known;
      extra_steps is "none" (0 to 2), "moderate_to_high" (3 to 7), "very_high" (8 and up) or None;
      the sunscreen link shows at 3 or higher. check_advisories is True when the AQI is above Moderate.
    - tips: {"groups": [] or ["cool_dry"] or ["hot_humid"] when the weather fits,
      "headline": None, "cool_dry", "cool", "dry" or "hot_humid"}. cool_dry applies at the cool
      temperature cutoff or lower, or the dry humidity cutoff or lower; hot_humid needs both the
      hot and the humid cutoff. An unknown temperature or humidity never triggers a group.
    - missing: parts that could not be found: "conditions", "uv", "humidity", "temperature", "air_quality".
    """
    config = TODAY_CONFIG
    result = {
        "status": None, "query": None, "place": None, "choices": [], "local_time": None, "uv": None,
        "humidity": None, "temperature_c": None, "aqi": None,
        "timeline": {"available": False, "reaches": False, "ranges": [], "peak": None},
        "guidance": {"uv_card": None, "extra_steps": None, "show_sunscreen_link": False, "check_advisories": False},
        "tips": {"groups": [], "headline": None},
        "missing": [],
    }

    if latitude is not None or longitude is not None:
        coordinates = parse_coordinates(latitude, longitude)
        if coordinates is None:
            result["status"] = "invalid"
            return result
        name = clean_place_text(label, config["max_label_length"], allow_parentheses=True) or "Selected place"
        place = {"name": name, "region": None, "country": None,
                 "latitude": coordinates[0], "longitude": coordinates[1]}
    elif city is not None and str(city).strip():
        query = clean_place_text(city, config["max_city_length"])
        result["query"] = query
        if query is None:
            result["status"] = "invalid"
            return result
        try:
            places = search_places(query)
        except WeatherError:
            result["status"] = "unavailable"
            return result
        if not places:
            result["status"] = "no_match"
            return result
        if len(places) > 1:
            result["status"], result["choices"] = "choose", places
            return result
        place = places[0]
    else:
        place = dict(config["default_place"])
    result["place"] = place

    forecast = air = None
    try:
        forecast = fetch_forecast(place["latitude"], place["longitude"])
    except WeatherError:
        result["missing"].append("conditions")
    try:
        air = fetch_air_quality(place["latitude"], place["longitude"])
    except WeatherError:
        result["missing"].append("air_quality")
    if forecast is None and air is None:
        result["status"] = "unavailable"
        return result
    result["status"] = "ok"
    result["local_time"] = (forecast or {}).get("time") or (air or {}).get("time")

    guidance = result["guidance"]
    if forecast is not None:
        now = None if forecast["uv_now"] is None else whole_number(forecast["uv_now"])
        peak = None if forecast["uv_max"] is None else whole_number(forecast["uv_max"])
        if now is None and peak is None:
            result["missing"].append("uv")
        else:
            result["uv"] = {
                "now": now, "now_category": None if now is None else category_for(now, config["uv_categories"]),
                "max": peak, "max_category": None if peak is None else category_for(peak, config["uv_categories"]),
            }
            level = peak if peak is not None else now         # today's peak UV decides the extra steps
            if level >= config["very_high_from_uv"]:
                guidance["extra_steps"] = "very_high"
            elif level >= config["sun_protection_from_uv"]:
                guidance["extra_steps"] = "moderate_to_high"
            else:
                guidance["extra_steps"] = "none"
            guidance["show_sunscreen_link"] = level >= config["sun_protection_from_uv"]
            guidance["uv_card"] = ("full" if level >= config["sun_protection_from_uv"]
                                   else "low" if level >= config["very_low_below_uv"] else "very_low")
        result["timeline"] = uv_timeline(forecast.get("uv_hourly"))
        result["humidity"] = forecast["humidity"]
        result["temperature_c"] = forecast["temperature_c"]
        if forecast["humidity"] is None:
            result["missing"].append("humidity")
        if forecast["temperature_c"] is None:
            result["missing"].append("temperature")

    temperature, humidity = result["temperature_c"], result["humidity"]
    cool = temperature is not None and temperature <= config["cool_at_or_below_c"]
    dry = humidity is not None and humidity <= config["dry_at_or_below_percent"]
    hot_humid = (temperature is not None and humidity is not None
                 and temperature >= config["hot_at_or_above_c"] and humidity >= config["humid_at_or_above_percent"])
    tips = result["tips"]
    if cool or dry:
        tips["groups"].append("cool_dry")
        tips["headline"] = "cool_dry" if cool and dry else "cool" if cool else "dry"
    elif hot_humid:
        tips["groups"].append("hot_humid")
        tips["headline"] = "hot_humid"

    if air is not None:
        if air["us_aqi"] is not None:
            value = whole_number(air["us_aqi"])
            result["aqi"] = {"value": value, "category": category_for(value, config["aqi_categories"]),
                             "pm2_5": air["pm2_5"]}
            guidance["check_advisories"] = value > config["advisory_above_aqi"]
        else:
            result["missing"].append("air_quality")
    return result


# ------------------------------------------------------------------ #
# Ingredient Science: published papers from PubMed                    #
# ------------------------------------------------------------------ #

RESEARCH_CONFIG = {
    "cache_hours": 24,       # a saved search is reused this long, with no call to PubMed
    "prune_days": 30,        # saved searches older than this are deleted
    "max_rows": 1000,        # at most this many saved searches are kept (oldest go first)
    "max_term_length": 60,
    "max_count_rows": 5000,  # at most this many saved paper counts are kept (oldest go first)
    "max_count_failures": 2,  # the At a glance box stops after this many failed counts in a row
}


def clean_search_text(text):
    """An ingredient search as lower-case plain text, or None if it is unusable.

    The same rules as a city name (letters, digits, spaces, hyphens, apostrophes, commas and full
    stops; links, brackets, quotes and colons are refused). Lower case also stops a typed AND or OR
    from acting as a PubMed operator.
    """
    cleaned = clean_place_text(text, RESEARCH_CONFIG["max_term_length"])
    return cleaned.casefold() if cleaned else None


def _saved_search(conn, term, reviews_only):
    """(fetched_at as an aware datetime, papers) for a saved search, or None if there is none or it is unreadable."""
    row = conn.execute(
        "SELECT fetched_at, papers_json FROM pubmed_searches WHERE term = ? AND reviews_only = ?",
        (term, int(reviews_only)),
    ).fetchone()
    if row is None:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
        papers = json.loads(row["papers_json"])
    except (ValueError, TypeError):
        return None
    if fetched.tzinfo is None or not isinstance(papers, list):
        return None
    return fetched, papers


def _save_search(conn, term, reviews_only, papers, now):
    with conn:
        conn.execute(
            "INSERT INTO pubmed_searches (term, reviews_only, fetched_at, papers_json) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (term, reviews_only) DO UPDATE SET"
            " fetched_at = excluded.fetched_at, papers_json = excluded.papers_json",
            (term, int(reviews_only), now.isoformat(timespec="seconds"), json.dumps(papers)),
        )
        cutoff = (now - timedelta(days=RESEARCH_CONFIG["prune_days"])).isoformat(timespec="seconds")
        conn.execute("DELETE FROM pubmed_searches WHERE fetched_at < ?", (cutoff,))
        conn.execute(
            "DELETE FROM pubmed_searches WHERE rowid IN (SELECT rowid FROM pubmed_searches"
            " ORDER BY fetched_at DESC LIMIT -1 OFFSET ?)",
            (RESEARCH_CONFIG["max_rows"],),
        )


def search_research(term, reviews_only=False, db_path=None, now=None):
    """Published papers about an ingredient, from PubMed (or a saved copy); plain data only.

    Lists papers and nothing else: no claim about what an ingredient does is made or implied.
    The search is "<term> AND skin"; `reviews_only` keeps only review papers.

    Returns {"status", "term", "query", "reviews_only", "papers", "source", "fetched_at"}:
    - status: "ok" (papers found), "empty" (a search with no match), "invalid" (unusable text)
      or "unavailable" (PubMed could not be reached and nothing is saved).
    - papers: up to 10 of {"pmid", "title", "journal", "year", "types", "url"} in PubMed's
      relevance order; journal and year may be None.
    - source: "live" (fetched now), "cache" (saved less than 24 hours ago, no call made) or
      "stale_cache" (older, shown only because PubMed could not be reached); fetched_at is the
      UTC time (ISO text) the papers were fetched, or None.
    """
    reviews_only = bool(reviews_only)
    cleaned = clean_search_text(term)
    result = {"status": None, "term": cleaned, "query": f"{cleaned} AND skin" if cleaned else None,
              "reviews_only": reviews_only, "papers": [], "source": None, "fetched_at": None}
    if cleaned is None:
        result["status"] = "invalid"
        return result

    init_db(db_path)
    now = now or datetime.now(timezone.utc)
    with closing(get_db(db_path)) as conn:
        saved = _saved_search(conn, cleaned, reviews_only)
        if saved and now - saved[0] < timedelta(hours=RESEARCH_CONFIG["cache_hours"]):
            result.update(papers=saved[1], source="cache", fetched_at=saved[0].isoformat(timespec="seconds"))
        else:
            try:
                papers = search_pubmed(cleaned, reviews_only)
            except PubmedError:
                if saved is None:
                    result["status"] = "unavailable"
                    return result
                result.update(papers=saved[1], source="stale_cache", fetched_at=saved[0].isoformat(timespec="seconds"))
            else:
                _save_search(conn, cleaned, reviews_only, papers, now)
                result.update(papers=papers, source="live", fetched_at=now.isoformat(timespec="seconds"))
    result["status"] = "ok" if result["papers"] else "empty"
    return result


def _saved_count(conn, query, now):
    """(count, fetched_at) of a saved count under 24 hours old, else None."""
    row = conn.execute(
        "SELECT paper_count, fetched_at FROM pubmed_counts WHERE query = ?", (query,)
    ).fetchone()
    if row is None:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None
    if fetched.tzinfo is None or now - fetched >= timedelta(hours=RESEARCH_CONFIG["cache_hours"]):
        return None
    return row["paper_count"], fetched


def _save_count(conn, query, count, now):
    with conn:
        conn.execute(
            "INSERT INTO pubmed_counts (query, paper_count, fetched_at) VALUES (?, ?, ?)"
            " ON CONFLICT (query) DO UPDATE SET paper_count = excluded.paper_count,"
            " fetched_at = excluded.fetched_at",
            (query, count, now.isoformat(timespec="seconds")),
        )
        cutoff = (now - timedelta(days=RESEARCH_CONFIG["prune_days"])).isoformat(timespec="seconds")
        conn.execute("DELETE FROM pubmed_counts WHERE fetched_at < ?", (cutoff,))
        conn.execute(
            "DELETE FROM pubmed_counts WHERE rowid IN (SELECT rowid FROM pubmed_counts"
            " ORDER BY fetched_at DESC LIMIT -1 OFFSET ?)",
            (RESEARCH_CONFIG["max_count_rows"],),
        )


def get_ingredient_card(term):
    """The "At a glance" card for an ingredient, or None if it has none; plain data only.

    Two short lines, each with a named source and link, from content/ingredient_cards.py:
    {"key", "what", "discussed", "checked"}. what is {"text", "source_name", "source_url"} or None;
    discussed is {"topics", "context", "source_name", "source_url"} or None. A line the content file
    leaves out comes back as None. No call is made: the card is fixed text, not a PubMed result.
    """
    cleaned = clean_search_text(term)
    if cleaned is None:
        return None
    for card in cards_content.CARDS:
        if cleaned not in card["names"]:
            continue
        what, discussed = card.get("what"), card.get("discussed")
        if not what and not discussed:
            return None
        return {
            "key": card["key"], "checked": card["checked"],
            "what": what and {"text": what["text"], "source_name": what["source"]["name"],
                              "source_url": what["source"]["url"]},
            "discussed": discussed and {"topics": list(discussed["topics"]), "context": discussed.get("context"),
                                        "source_name": discussed["source"]["name"],
                                        "source_url": discussed["source"]["url"]},
        }
    return None


def get_ingredient_glance(term, db_path=None, now=None):
    """Topic counts for the "At a glance" box; plain data only.

    For each topic in the content file, how many papers PubMed finds for "<term> AND <topic>". A
    count says how often a topic appears in published papers together with the ingredient; it does
    not say that an ingredient works or suits anyone. Nothing else is counted.

    Returns {"status", "term", "topics", "incomplete", "fetched_at"}:
    - status: "ok" (at least one topic has papers), "none" (no papers for the ingredient, in which
      case no topic is searched, or no topic has a paper), "invalid" (unusable text) or "unavailable"
      (PubMed could not be reached, only an old saved list of papers exists, or no count worked).
    - topics: [{"topic", "count"}] with at least one paper, most papers first (ties in the order of
      the content file). A topic whose count failed is left out; incomplete is True when any count
      was left out. After max_count_failures failed counts in a row the rest are not tried.
    - fetched_at: the UTC time (ISO text) of the oldest count used.
    Every count is saved and reused for 24 hours; a failed count is never saved.
    """
    cleaned = clean_search_text(term)
    result = {"status": None, "term": cleaned, "topics": [], "incomplete": False, "fetched_at": None}
    if cleaned is None:
        result["status"] = "invalid"
        return result
    found = search_research(cleaned, False, db_path, now)
    if found["status"] == "empty":
        result["status"] = "none"              # no papers: no topic is searched
        return result
    if found["status"] != "ok" or found["source"] == "stale_cache":
        result["status"] = "unavailable"       # PubMed is down: no counts are tried
        return result

    now = now or datetime.now(timezone.utc)
    fetched, failures = [], 0
    with closing(get_db(db_path)) as conn:
        def count(query):
            """The count for a query (saved or fresh), or None when it failed."""
            saved = _saved_count(conn, query, now)
            if saved:
                fetched.append(saved[1])
                return saved[0]
            try:
                value = count_pubmed(query)
            except PubmedError:
                return None
            _save_count(conn, query, value, now)
            fetched.append(now)
            return value

        for topic in science_content.GLANCE_TOPICS:
            if failures >= RESEARCH_CONFIG["max_count_failures"]:
                result["incomplete"] = True
                continue
            value = count(topic_query(cleaned, topic))
            if value is None:
                failures += 1
                result["incomplete"] = True
            else:
                failures = 0
                if value > 0:
                    result["topics"].append({"topic": topic, "count": value})
    order = {topic: i for i, topic in enumerate(science_content.GLANCE_TOPICS)}
    result["topics"].sort(key=lambda t: (-t["count"], order[t["topic"]]))
    if fetched:
        result["fetched_at"] = min(fetched).isoformat(timespec="seconds")
    if result["topics"]:
        result["status"] = "ok"
    else:
        result["status"] = "unavailable" if result["incomplete"] else "none"
    return result


def paper_label(types):
    """The plain label for a paper from its PubMed publication types (a list of names).

    The first label in science_content.PAPER_LABELS that one of the types fits; a paper that fits
    none is a "Research paper". Only the kind of paper is named: nothing about what it found.
    """
    types = set(types or [])
    for label, names in science_content.PAPER_LABELS:
        if types & set(names):
            return label
    return science_content.OTHER_LABEL


def group_papers(papers):
    """Papers grouped under their plain labels, summaries first, empty groups left out.

    Returns [{"label", "papers"}]; inside a group the papers keep PubMed's relevance order.
    """
    groups = {label: [] for label in science_content.GROUP_ORDER}
    for paper in papers:
        groups[paper_label(paper.get("types"))].append(paper)
    return [{"label": label, "papers": groups[label]} for label in science_content.GROUP_ORDER if groups[label]]


def inr_price(price_usd, rate):
    """USD price to whole rupees, halves rounded up; None if either input is missing."""
    if price_usd is None or rate is None:
        return None
    # Decimal on the printed values: float 452.5 rounds half up here, not to even
    exact = Decimal(str(price_usd)) * Decimal(str(rate))
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def inr_per_ml(price_per_ml_usd, rate):
    """USD per ml to INR per ml, rounded to 2 decimals; None if either input is missing."""
    if price_per_ml_usd is None or rate is None:
        return None
    return round(price_per_ml_usd * rate, 2)
