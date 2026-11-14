import json
import math
from contextlib import closing
from datetime import datetime
from urllib.parse import unquote

from flask import Flask, abort, redirect, render_template, request, url_for

from content import avoid_list as avoid_content
from content import ingredient_cards as cards_content
from content import main_ingredients as main_ingredients_content
from content import science as science_content
from content import today_tips as today_content
from content.compare_groups import GROUP_SEPARATOR, split_group
from database.db import DB_PATH, get_db
from database.services import (
    MAIN_INGREDIENT_LABELS, TODAY_CONFIG, check_avoid_list, clean_avoid_terms, compare_products, escape_like, get_insights,
    get_ingredient_card, get_ingredient_glance, get_product_detail, get_today_conditions, get_usd_inr_rate, group_papers, inr_per_ml,
    inr_price, list_group_ingredients, list_groups, list_products_in_group,
    main_ingredients_of, search_research, split_ingredients_text,
)

PAGE_SIZE = 24
SORT_OPTIONS = {
    "name": "Name (A-Z)",
    "price": "Price (low to high)",
    "price_per_ml": "Price per ml (low to high)",
}

# All user input reaches SQLite as bound parameters. The sort key is bound too
# (CASE picks the column), so no SQL text is ever built from the request.
# The "category" filter and column are the cleaned compare group (content/compare_groups.py),
# not the original `category` column, which only the detail page shows. A parent ("Sunscreen")
# also matches its subcategories ("Sunscreen › Face"); a subcategory matches only itself.
FILTER_SQL = """
    FROM products
    WHERE (:q = '' OR name LIKE :like ESCAPE '\\' OR brand LIKE :like ESCAPE '\\')
      AND (:category = '' OR compare_group = :category OR compare_group LIKE :sub_prefix ESCAPE '\\')
"""
COUNT_SQL = "SELECT COUNT(*) " + FILTER_SQL
PRODUCTS_SQL = (
    "SELECT id, name, brand, compare_group, price, size_text, ingredients_text "
    + FILTER_SQL
    + """
    ORDER BY
        CASE WHEN :sort = 'price' THEN price END,
        CASE WHEN :sort = 'price_per_ml' THEN price_per_ml END,
        name COLLATE NOCASE,
        id
    LIMIT :limit OFFSET :offset
"""
)
CATEGORIES_SQL = (
    "SELECT DISTINCT compare_group FROM products WHERE compare_group IS NOT NULL ORDER BY compare_group"
)

app = Flask(__name__)
app.config["DATABASE"] = DB_PATH  # tests point this at a temporary database

# Pages that read the visitor's avoid list from their cookie. Never cached for anyone else.
AVOID_LIST_ENDPOINTS = {"products", "product_detail", "compare"}


def avoid_terms():
    """The visitor's avoid list for this request: the cleaned words in their cookie, else [].

    The cookie is set by the visitor's own action in the browser (static/js/avoid.js). It is read
    here to filter and tag this one response and is never saved, logged or put in a link.
    """
    if "skin_index.avoid_terms" not in request.environ:    # per request, even when a test keeps one app context
        raw = request.cookies.get(avoid_content.COOKIE_NAME, "")[:4096]
        try:
            terms = clean_avoid_terms(json.loads(unquote(raw))) if raw else []
        except ValueError:
            terms = []
        request.environ["skin_index.avoid_terms"] = terms
    return request.environ["skin_index.avoid_terms"]


@app.after_request
def keep_avoid_list_pages_private(response):
    if request.endpoint in AVOID_LIST_ENDPOINTS:
        response.headers["Cache-Control"] = "private"
        response.vary.add("Cookie")
    return response


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

def group_sections(entries, all_option=False):
    """Dropdown sections for compare groups: [{"label", "options": [{"value", "label"}]}].

    `entries` are (group name, text to add after the label, such as " (95)"). A parent with
    subcategories becomes one section named after it (an <optgroup>), listing only the
    subcategory names; with `all_option` it starts with "All <parent>" (the parent's own value).
    Any other group is a plain option (section label None).
    """
    by_parent = {}
    for name, suffix in entries:
        by_parent.setdefault(split_group(name)[0], []).append((name, suffix))
    sections = []
    for parent in sorted(by_parent, key=str.casefold):
        items = sorted(by_parent[parent])
        if not any(split_group(name)[1] for name, _ in items):
            sections += [{"label": None, "options": [{"value": n, "label": n + s}]} for n, s in items]
            continue
        options = [{"value": parent, "label": f"All {parent}"}] if all_option else []
        for name, suffix in items:
            sub_name = split_group(name)[1]
            if sub_name:
                options.append({"value": name, "label": sub_name + suffix})
            elif not all_option:
                options.append({"value": name, "label": "No subcategory" + suffix})
        sections.append({"label": parent, "options": options})
    return sections


@app.route("/")
def landing():
    return render_template("landing.html")


def list_args(q, category, sort, page, hide=False):
    """Search, filter, sort, page and the hide switch of the product list, for links that return to it.

    Defaults and unknown or invalid values become None, which url_for leaves out. The avoid list
    itself is never part of a link: only whether the hide switch is on.
    """
    return {
        "q": q or None,
        "category": category or None,
        "sort": sort if sort in SORT_OPTIONS and sort != "name" else None,
        "page": page if page and page > 1 else None,
        "hide": "1" if hide else None,
    }


@app.route("/products")
def products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort = request.args.get("sort", "name")
    if sort not in SORT_OPTIONS:
        sort = "name"
    page = request.args.get("page", 1, type=int)

    terms = avoid_terms()
    hide = request.args.get("hide") == "1" and bool(terms)   # the switch needs a list to do anything

    params = {"q": q, "like": f"%{escape_like(q)}%", "category": category,
              "sub_prefix": escape_like(category + GROUP_SEPARATOR) + "%"}
    with closing(get_db(app.config["DATABASE"])) as conn:
        if hide:
            # every match is checked first, so the count and the pages follow what is left
            found = [dict(r) for r in conn.execute(
                PRODUCTS_SQL, {**params, "sort": sort, "limit": -1, "offset": 0})]
            checks = {r["id"]: check_avoid_list(terms, split_ingredients_text(r["ingredients_text"])) for r in found}
            kept = [r for r in found if checks[r["id"]]["status"] != "found"]
            hidden_count = len(found) - len(kept)
            total = len(kept)
            pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(max(page, 1), pages)
            rows = kept[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
        else:
            total = conn.execute(COUNT_SQL, params).fetchone()[0]
            pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(max(page, 1), pages)
            rows = [dict(r) for r in conn.execute(
                PRODUCTS_SQL,
                {**params, "sort": sort, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
            )]
            checks = {r["id"]: check_avoid_list(terms, split_ingredients_text(r["ingredients_text"])) for r in rows} if terms else {}
            hidden_count = 0
        groups = [r["compare_group"] for r in conn.execute(CATEGORIES_SQL)]

    rate = get_usd_inr_rate(app.config["DATABASE"])  # None: no INR column at all
    rows = [
        {**{k: v for k, v in row.items() if k != "ingredients_text"}, "inr_price": inr_price(row["price"], rate and rate.rate)}
        for row in rows
    ]

    def page_url(n):
        return url_for("products", q=q or None, category=category or None, sort=sort, page=n,
                       hide="1" if hide else None)

    return render_template(
        "products.html",
        products=rows,
        detail_args=list_args(q, category, sort, page, hide),
        total=total,
        q=q,
        category=category,
        sort=sort,
        sort_options=SORT_OPTIONS,
        category_sections=group_sections([(g, "") for g in groups], all_option=True),
        rate=rate,
        page=page,
        pages=pages,
        prev_url=page_url(page - 1) if page > 1 else None,
        next_url=page_url(page + 1) if page < pages else None,
        avoid=avoid_content, avoid_terms=terms, avoid_checks=checks, hide=hide, hidden_count=hidden_count,
    )


@app.route("/products/<int:id>")
def product_detail(id):
    product = get_product_detail(id, app.config["DATABASE"])
    if product is None:
        abort(404)

    rate = get_usd_inr_rate(app.config["DATABASE"])  # None: no INR anywhere on the page
    rate_value = rate and rate.rate
    back_url = url_for(
        "products",
        **list_args(
            request.args.get("q", "").strip(),
            request.args.get("category", "").strip(),
            request.args.get("sort"),
            request.args.get("page", type=int),
            request.args.get("hide") == "1",
        ),
    )
    terms = avoid_terms()
    avoid_check = check_avoid_list(terms, [i["name"] for i in product["ingredients"]]) if terms else None
    science_links = [
        {"label": f"Studies on {entry['label']}", "url": url_for("science", q=entry["science_term"])}
        for entry in main_ingredients_content.MAIN_INGREDIENTS
        if entry["key"] in main_ingredients_of(product["name"], [i["name"] for i in product["ingredients"]])
    ]
    return render_template(
        "product_detail.html",
        product=product,
        science_links=science_links,
        rate=rate,
        price_inr=inr_price(product["price"], rate_value),
        per_ml_inr=inr_per_ml(product["price_per_ml"], rate_value),
        back_url=back_url,
        avoid=avoid_content, avoid_check=avoid_check,
    )


@app.template_filter("percent")
def percent_filter(value):
    """12.025 -> '12.025', 2.0 -> '2', 0.0408 -> '0.0408' (no exponent, no trailing zeros)."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


@app.template_filter("shorten")
def shorten_filter(text, length=science_content.TITLE_MAX_LENGTH):
    """A long text cut at a word boundary to about `length` characters, with an ellipsis."""
    if len(text) <= length:
        return text
    cut = text[:length]
    if text[length] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-\u2013") + "\u2026"


@app.template_filter("and_list")
def and_list_filter(items):
    """['a'] -> 'a', ['a', 'b', 'c'] -> 'a, b and c'."""
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


def parse_product_id(raw):
    """A positive whole number from the query string, else None (anything else is ignored)."""
    raw = (raw or "").strip()
    if not (raw.isascii() and raw.isdigit()):
        return None
    return int(raw) or None


def product_label(p):
    """'Brand - Name (size, $price)' for a product dropdown."""
    size = p["size_text"] or "size not available"
    price = f"${p['price']:.2f}" if p["price"] is not None else "price not available"
    return f"{p['brand']} - {p['name']} ({size}, {price})"


def join_labels(keys):
    """'niacinamide', 'niacinamide and vitamin C', 'a, b and c' for main ingredient keys."""
    labels = [MAIN_INGREDIENT_LABELS[key] for key in keys]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


@app.route("/compare")
def compare():
    db_path = app.config["DATABASE"]
    args = request.args
    raw_group = args.get("group", "")
    raw_ingredient = args.get("ingredient", "")
    ids = {"a": parse_product_id(args.get("a")), "b": parse_product_id(args.get("b"))}
    result = compare_products(ids["a"], ids["b"], db_path)

    # A product left over from an earlier choice of category or main ingredient (a form sent
    # without JavaScript) is not a choice: show the pickers again instead.
    def stale(side):
        product = result[side]
        return product is not None and (
            (raw_group and product["compare_group"] != raw_group)
            or (raw_ingredient and raw_ingredient not in result[f"{side}_main"])
        )

    if stale("a") or stale("b"):
        ids = {side: None if stale(side) else ids[side] for side in ids}
        result = compare_products(ids["a"], ids["b"], db_path)

    # With the same product on both sides, B is still to be chosen
    shown = {side: result[side] for side in ("a", "b")}
    if result["status"] == "same_product":
        shown["b"] = None
    anchor_side = "a" if shown["a"] else "b" if shown["b"] else None
    anchor = shown[anchor_side] if anchor_side else None
    anchor_main = result[f"{anchor_side}_main"] if anchor_side else []

    groups = list_groups(db_path)
    group_sizes = {g["name"]: g["products"] for g in groups}
    group = anchor["compare_group"] if anchor else (raw_group if raw_group in group_sizes else None)
    group = group or None

    ingredients = []
    if group:
        ingredients = [i for i in list_group_ingredients(group, db_path) if not anchor or i["key"] in anchor_main]
    keys = {i["key"] for i in ingredients}
    ingredient = raw_ingredient if raw_ingredient in keys else ""
    if not ingredient and result["status"] == "ok" and result["shared_main"]:
        ingredient = result["shared_main"][0]
    if not ingredient and anchor and len(ingredients) == 1:
        ingredient = ingredients[0]["key"]
    ingredient_products = {i["key"]: i["products"] for i in ingredients}

    messages = []
    for side in ("a", "b"):
        if result[f"{side}_state"] == "unknown":
            messages.append(f"We couldn't find product {side.upper()} (id {ids[side]}). Please choose one below.")
    if result["status"] == "same_product":
        messages.append("Product A and product B are the same product. Please choose a different product for B.")
    for side in ("a", "b"):
        product = shown[side]
        if product is None:
            continue
        if product["compare_group"] is None:
            category = product["category"] or "its category"
            messages.append(
                f"Product {side.upper()} ({category}) has no comparison group, "
                "so it can't be compared fairly with other products."
            )
        elif not result[f"{side}_main"]:
            messages.append(
                f"Product {side.upper()} doesn't name any of the main ingredients we group by or list one "
                f"among its first {main_ingredients_content.TOP_N} ingredients, so it can't be compared here."
            )
    if result["status"] == "different_groups":
        messages.append(
            f"Product A is in {result['a_group']} and product B is in {result['b_group']}, "
            "so they can't be compared fairly."
        )
    elif result["status"] == "different_ingredients":
        messages.append(
            f"Product A is grouped under {join_labels(result['a_main'])} and product B under "
            f"{join_labels(result['b_main'])}, so they can't be compared here: "
            "they share no main ingredient group."
        )
    if group and group not in group_sizes:
        messages.append(f"There is only 1 product in {group}, so there is nothing to compare.")
    elif ingredient and ingredient_products.get(ingredient, 0) < 2:
        messages.append(
            f"Only 1 product in {group} is in the {MAIN_INGREDIENT_LABELS[ingredient]} group, "
            "so there is nothing to compare."
        )
    elif group and ingredients and not any(i["products"] >= 2 for i in ingredients):
        messages.append(
            f"In {group}, no main ingredient group has 2 or more products, so there is nothing to compare."
        )
    elif group and not ingredients and not anchor:
        messages.append(f"No product in {group} is in a main ingredient group, so there is nothing to compare.")

    options = {"a": [], "b": []}
    if group and ingredient and ingredient_products.get(ingredient, 0) >= 2:
        for side, other_side in (("a", "b"), ("b", "a")):
            exclude = shown[other_side]["id"] if shown[other_side] else None
            options[side] = [
                {"id": p["id"], "label": product_label(p)}
                for p in list_products_in_group(group, ingredient, exclude, db_path)
            ]

    both_shown = shown["a"] is not None and shown["b"] is not None
    rate = get_usd_inr_rate(db_path) if both_shown else None
    rate_value = rate and rate.rate
    facts = {
        side: {
            "price_inr": shown[side] and inr_price(shown[side]["price"], rate_value),
            "per_ml_inr": shown[side] and inr_per_ml(shown[side]["price_per_ml"], rate_value),
        }
        for side in ("a", "b")
    }
    if both_shown and result["status"] == "different_groups":
        retry_url, retry_label = url_for("compare", a=shown["a"]["id"]), f"Choose a product from {result['a_group']}"
    elif both_shown and result["status"] == "different_ingredients":
        retry_url, retry_label = url_for("compare", a=shown["a"]["id"]), "Choose another product to compare with A"
    else:
        retry_url, retry_label = url_for("compare"), "Start again"

    terms = avoid_terms()
    avoid_checks = None
    if terms and both_shown and result["comparable"]:
        avoid_checks = {
            side: check_avoid_list(terms, [i["name"] for i in shown[side]["ingredients"]]) for side in ("a", "b")
        }

    return render_template(
        "compare.html", result=result, shown=shown, both_shown=both_shown, messages=messages,
        groups=groups, group_sections=group_sections([(g["name"], f" ({g['products']})") for g in groups]),
        group=group, ingredients=ingredients, ingredient=ingredient,
        ingredient_label=MAIN_INGREDIENT_LABELS.get(ingredient), options=options,
        selected={side: shown[side]["id"] if shown[side] else None for side in ("a", "b")},
        facts=facts, rate=rate, retry_url=retry_url, retry_label=retry_label,
        shared_label=join_labels(result["shared_main"]) if result["shared_main"] else None,
        top_n=main_ingredients_content.TOP_N,
        avoid=avoid_content, avoid_checks=avoid_checks,
    )


def bar_percent(value, largest):
    """Width of a bar as a percentage of the largest value on its chart."""
    return round(value / largest * 100, 1) if largest else 0.0


def ingredient_takeaway(summary):
    if not summary["top"]:
        return None
    top = summary["top"][0]
    return (f"After water, the most common ingredient is {top['name']}, found in "
            f"{top['share_percent']:.1f}% of products ({top['products']:,} of {summary['products']:,}).")


def build_takeaways(data):
    """Plain, neutral sentences made from the computed numbers.

    They describe shopper engagement (likes, ratings, reviews) and ingredients; they never
    say anything about sales, effectiveness or quality.
    """
    group, config = data["scope_group"], data["config"]
    sentences = []
    if data["brands"]:
        top = data["brands"][0]
        lead = "Across all products, " if group else ""
        noun = "product" if top["products"] == 1 else "products"
        sentence = (f"{lead}{top['brand']} has the most likes ({top['loves']:,}) "
                    f"from its {top['products']} {noun}")
        if top["average_rating"] is not None:
            sentence += f", with a review-weighted average rating of {top['average_rating']:.2f}"
        sentences.append(sentence + ".")
    if data["loved_products"]:
        top = data["loved_products"][0]
        where = f" in {group}" if group else ""
        sentences.append(
            f"The most liked product{where} is {top['name']} by {top['brand']} ({top['loves_count']:,} likes)."
        )
    sentences.append(ingredient_takeaway(data["ingredients"]))
    if group:
        bands = data["price_bands"]
        if bands and bands["enough"]:
            ratings = [f"{b['average_rating']:.2f}" for b in bands["bands"]]
            counts = [str(b["products"]) for b in bands["bands"]]
            sentences.append(
                f"In {group}, products in the lower, middle and higher price-per-ml bands have review-weighted "
                f"average ratings of {ratings[0]}, {ratings[1]} and {ratings[2]} "
                f"(n={counts[0]}, {counts[1]} and {counts[2]}); this shows a pattern, not a cause."
            )
        well = data["well_reviewed"]
        if well and well["qualifying_products"]:
            sentences.append(
                f"{well['qualifying_products']} products in {group} have at least "
                f"{config['well_reviewed_min_reviews']} reviews and a rating of at least "
                f"{config['well_reviewed_min_rating']:.1f}."
            )
    return [s for s in sentences if s]


def uv_timeline_sentences(data):
    """The timeline sentences for the full UV card (today's peak UV is 3 or higher)."""
    texts, level = today_content.TIMELINE, TODAY_CONFIG["sun_protection_from_uv"]
    timeline = data["timeline"]
    if not timeline["available"]:
        return [texts["unavailable"]]
    sentences = []
    if timeline["reaches"]:
        ranges = " and ".join(f"{r['from']} to {r['to']}" for r in timeline["ranges"])
        sentences.append(texts["reaches"].format(level=level, ranges=ranges))
    # when no hourly average reaches the level, only the peak hour is given
    peak = timeline["peak"]
    sentences.append(texts["peak"].format(span=f"{peak['from']}–{peak['to']}", uv=peak["uv"]))
    return sentences


def tip_cards(data):
    """The weather tips card, if the weather fits a group (otherwise nothing), with link URLs."""
    tips, cards = data["tips"], []
    for group in tips["groups"]:
        links = [
            {"label": link["label"],
             "url": url_for("products", **{k: v for k, v in link.items() if k != "label"})}
            for link in today_content.TIP_LINKS.get(group, [])
        ]
        cards.append({"title": today_content.HEADLINES[tips["headline"]],
                      "tips": today_content.TIP_GROUPS[group], "links": links})
    return cards


@app.route("/science")
def science():
    term = request.args.get("q")
    reviews_only = request.args.get("reviews") == "1"
    searched = term is not None and term.strip() != ""
    result = search_research(term, reviews_only, app.config["DATABASE"]) if searched else None
    saved_on = None
    if result and result["source"] == "stale_cache":
        saved_on = datetime.fromisoformat(result["fetched_at"]).strftime("%d %b %Y").lstrip("0")
    # The At a glance box: an ingredient with a card shows the card (fixed text with sources, no PubMed
    # counts are asked for); one without shows the topic counts when they are available, else no box.
    card = get_ingredient_card(term) if result and result["status"] == "ok" else None
    glance = None
    if result and result["status"] == "ok" and card is None:
        glance = get_ingredient_glance(term, app.config["DATABASE"])
        if glance["status"] != "ok":
            glance = None
    return render_template(
        "science.html", result=result, content=science_content, cards=cards_content, reviews_only=reviews_only, glance=glance, card=card,
        term_text=" ".join((term or "").split())[:60], saved_on=saved_on,
        paper_groups=group_papers(result["papers"]) if result else [],
        quick_links=[{"name": name, "url": url_for("science", q=name, **({"reviews": "1"} if reviews_only else {}))}
                     for name in science_content.QUICK_LINKS],
    )


@app.route("/research")
def research():
    """The page was called Research before it became Ingredient Science: old links still work."""
    return redirect(url_for("science", q=request.args.get("q"), reviews=request.args.get("reviews")), code=301)


@app.route("/today")
def today():
    city = request.args.get("city")
    data = get_today_conditions(
        city=city, latitude=request.args.get("lat"), longitude=request.args.get("lon"),
        label=request.args.get("label"),
    )
    # what the city box shows: what was typed, else the place being shown
    place = data["place"]
    typed = " ".join((city or "").split())[:60]
    return render_template(
        "today.html", data=data, place=place,
        city_text=typed or (place["name"] if place else ""),
        sunscreen_url=url_for("products", category="Sunscreen"),
        content=today_content,
        timeline_sentences=uv_timeline_sentences(data) if data["guidance"]["uv_card"] == "full" else [],
        extra_steps=today_content.EXTRA_STEPS.get(data["guidance"]["extra_steps"]),
        tip_cards=tip_cards(data) if place else [],
    )


@app.route("/insights")
def insights():
    db_path = app.config["DATABASE"]
    requested = request.args.get("group", "").strip() or None
    data = get_insights(requested, db_path)
    config = data["config"]

    message = None
    if data["group_status"] == "unavailable":
        message = ("We couldn't show that product type, so this is the overall view. Only types with at "
                   f"least {config['min_group_products']} products can be shown.")

    rate = get_usd_inr_rate(db_path) if data["overview"]["products"] else None
    rate_value = rate and rate.rate

    largest_loves = max((b["loves"] for b in data["brands"]), default=0)
    brands = [{**b, "bar": bar_percent(b["loves"], largest_loves)} for b in data["brands"]]

    largest_loved = max((p["loves_count"] for p in data["loved_products"]), default=0)
    loved_products = [
        {**p, "price_inr": inr_price(p["price"], rate_value), "bar": bar_percent(p["loves_count"], largest_loved)}
        for p in data["loved_products"]
    ]

    well_reviewed = data["well_reviewed"]
    if well_reviewed:
        well_reviewed = {**well_reviewed, "products": [
            {**p, "price_inr": inr_price(p["price"], rate_value),
             "price_per_ml_inr": inr_per_ml(p["price_per_ml"], rate_value)}
            for p in well_reviewed["products"]
        ]}

    price_bands = data["price_bands"]
    if price_bands:
        # ratings run 0 to 5, so the bar uses that scale
        price_bands = {**price_bands, "bands": [
            {**b, "bar": round(b["average_rating"] / 5 * 100, 1)} for b in price_bands["bands"]
        ]}

    def ingredient_bars(summary):
        # shares are already percentages of products, so the bar uses that 0-100 scale
        return {**summary, "top": [{**i, "bar": round(i["share_percent"], 1)} for i in summary["top"]]}

    return render_template(
        "insights.html",
        data=data, overview=data["overview"], config=config, brands=brands,
        loved_products=loved_products, well_reviewed=well_reviewed, price_bands=price_bands,
        ingredients=ingredient_bars(data["ingredients"]), takeaways=build_takeaways(data),
        message=message, rate=rate, group=data["scope_group"],
        group_sections=group_sections([(g["name"], f" ({g['products']})") for g in data["selector_groups"]]),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)
