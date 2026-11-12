import math
from contextlib import closing

from flask import Flask, abort, render_template, request, url_for

from database.db import DB_PATH, get_db
from database.services import (
    compare_products, escape_like, get_product_detail, get_usd_inr_rate, inr_per_ml,
    inr_price, list_brands_in_group, list_groups, list_products_in_group,
)

PAGE_SIZE = 24
SORT_OPTIONS = {
    "name": "Name (A-Z)",
    "price": "Price (low to high)",
    "price_per_ml": "Price per ml (low to high)",
}

# All user input reaches SQLite as bound parameters. The sort key is bound too
# (CASE picks the column), so no SQL text is ever built from the request.
FILTER_SQL = """
    FROM products
    WHERE (:q = '' OR name LIKE :like ESCAPE '\\' OR brand LIKE :like ESCAPE '\\')
      AND (:category = '' OR category = :category)
"""
COUNT_SQL = "SELECT COUNT(*) " + FILTER_SQL
PRODUCTS_SQL = (
    "SELECT id, name, brand, category, price, size_text "
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
    "SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category"
)

app = Flask(__name__)
app.config["DATABASE"] = DB_PATH  # tests point this at a temporary database


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


def list_args(q, category, sort, page):
    """Search, filter, sort and page of the product list, for links that return to it.

    Defaults and unknown or invalid values become None, which url_for leaves out.
    """
    return {
        "q": q or None,
        "category": category or None,
        "sort": sort if sort in SORT_OPTIONS and sort != "name" else None,
        "page": page if page and page > 1 else None,
    }


@app.route("/products")
def products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort = request.args.get("sort", "name")
    if sort not in SORT_OPTIONS:
        sort = "name"
    page = request.args.get("page", 1, type=int)

    params = {"q": q, "like": f"%{escape_like(q)}%", "category": category}
    with closing(get_db(app.config["DATABASE"])) as conn:
        total = conn.execute(COUNT_SQL, params).fetchone()[0]
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(max(page, 1), pages)
        rows = conn.execute(
            PRODUCTS_SQL,
            {**params, "sort": sort, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
        ).fetchall()
        categories = [r["category"] for r in conn.execute(CATEGORIES_SQL)]

    rate = get_usd_inr_rate(app.config["DATABASE"])  # None: no INR column at all
    rows = [
        {**row, "inr_price": inr_price(row["price"], rate and rate.rate)}
        for row in map(dict, rows)
    ]

    def page_url(n):
        return url_for("products", q=q or None, category=category or None, sort=sort, page=n)

    return render_template(
        "products.html",
        products=rows,
        detail_args=list_args(q, category, sort, page),
        total=total,
        q=q,
        category=category,
        sort=sort,
        sort_options=SORT_OPTIONS,
        categories=categories,
        rate=rate,
        page=page,
        pages=pages,
        prev_url=page_url(page - 1) if page > 1 else None,
        next_url=page_url(page + 1) if page < pages else None,
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
        ),
    )
    return render_template(
        "product_detail.html",
        product=product,
        rate=rate,
        price_inr=inr_price(product["price"], rate_value),
        per_ml_inr=inr_per_ml(product["price_per_ml"], rate_value),
        back_url=back_url,
    )


@app.template_filter("percent")
def percent_filter(value):
    """12.025 -> '12.025', 2.0 -> '2', 0.0408 -> '0.0408' (no exponent, no trailing zeros)."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


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


def build_picker(side, args, other, db_path):
    """What the page needs to let the user choose the product for `side` ('a' or 'b').

    `other` is the product already chosen on the other side (or None). The picker then
    lists only that product's comparison group, without that product itself.
    """
    constrained = other["compare_group"] if other else None
    picker = {
        "side": side, "label": f"Product {side.upper()}", "group": constrained,
        "constrained": other is not None, "groups": None, "brands": [], "brand": "",
        "q": args.get(f"{side}_q", "").strip(), "options": [], "needs_brand": False,
        "total": 0, "capped": False, "other_id": other["id"] if other else None,
    }
    if other is None:
        picker["groups"] = list_groups(db_path)
        wanted = args.get(f"{side}_group", "")
        picker["group"] = wanted if wanted in {g["name"] for g in picker["groups"]} else None
    if not picker["group"]:
        return picker
    picker["brands"] = list_brands_in_group(picker["group"], db_path)
    wanted = args.get(f"{side}_brand", "")
    picker["brand"] = wanted if wanted in {b["brand"] for b in picker["brands"]} else ""
    listing = list_products_in_group(
        picker["group"], picker["brand"] or None, picker["q"],
        exclude_id=picker["other_id"], db_path=db_path,
    )
    picker.update(
        options=[{"id": p["id"], "label": product_label(p)} for p in listing["products"]],
        needs_brand=listing["needs_brand"], total=listing["total"], capped=listing["capped"],
    )
    return picker


@app.route("/compare")
def compare():
    db_path = app.config["DATABASE"]
    args = request.args
    ids = {"a": parse_product_id(args.get("a")), "b": parse_product_id(args.get("b"))}
    result = compare_products(ids["a"], ids["b"], db_path)

    # A product left over from an earlier choice of category or brand (a form sent
    # without JavaScript) is not a choice: show the picker again instead.
    stale = {
        side: result[side] is not None and (
            (args.get(f"{side}_group") and result[side]["compare_group"] != args.get(f"{side}_group"))
            or (args.get(f"{side}_brand") and result[side]["brand"] != args.get(f"{side}_brand"))
        )
        for side in ("a", "b")
    }
    if stale["a"] or stale["b"]:
        ids = {side: None if stale[side] else ids[side] for side in ids}
        result = compare_products(ids["a"], ids["b"], db_path)

    # With the same product on both sides, B is still to be chosen
    shown = {side: result[side] for side in ("a", "b")}
    if result["status"] == "same_product":
        shown["b"] = None

    messages = []
    for side in ("a", "b"):
        if result[f"{side}_state"] == "unknown":
            messages.append(f"We couldn't find product {side.upper()} (id {ids[side]}). Please choose one below.")
    if result["status"] == "same_product":
        messages.append("Product A and product B are the same product. Please choose a different product for B.")
    elif result["status"] == "different_groups":
        messages.append(
            f"Product A is in {result['a_group']} and product B is in {result['b_group']}, "
            "so they can't be compared fairly."
        )
    elif result["status"] == "no_group":
        for side in ("a", "b"):
            if shown[side] and shown[side]["compare_group"] is None:
                category = shown[side]["category"] or "its category"
                messages.append(
                    f"Product {side.upper()} ({category}) has no comparison group, "
                    "so it can't be compared fairly with other products."
                )

    rate = get_usd_inr_rate(db_path) if any(shown.values()) else None
    rate_value = rate and rate.rate
    sides = []
    for side, other_side in (("a", "b"), ("b", "a")):
        product, other = shown[side], shown[other_side]
        picker = None
        blocked = other is not None and other["compare_group"] is None
        if product is None and not blocked and (side == "a" or other is not None):
            picker = build_picker(side, args, other, db_path)
        if product is None and blocked:
            messages.append(
                f"Product {other_side.upper()} ({other['category'] or 'its category'}) has no "
                "comparison group, so it can't be compared fairly with other products."
            )
        sides.append({
            "side": side, "label": f"Product {side.upper()}", "product": product,
            "price_inr": product and inr_price(product["price"], rate_value),
            "per_ml_inr": product and inr_per_ml(product["price_per_ml"], rate_value),
            "change_url": url_for("compare", **{other_side: other["id"]}) if other else url_for("compare"),
            "picker": picker, "blocked": blocked and product is None,
        })

    both_shown = shown["a"] is not None and shown["b"] is not None
    if both_shown and result["status"] == "different_groups":
        retry_url = url_for("compare", a=shown["a"]["id"])
    else:
        retry_url = url_for("compare")
    return render_template(
        "compare.html", sides=sides, result=result, both_shown=both_shown, messages=messages,
        rate=rate, retry_url=retry_url,
    )


# ------------------------------------------------------------------ #
# Placeholder routes — to be implemented step by step                 #
# ------------------------------------------------------------------ #

@app.route("/insights")
def insights():
    return "Market insights — coming in Step 7"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
