import math
from contextlib import closing

from flask import Flask, abort, render_template, request, url_for

from database.db import DB_PATH, get_db
from database.services import get_product_detail, get_usd_inr_rate, inr_per_ml, inr_price

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


def escape_like(text):
    """Make %, _ and \\ in user text match literally inside LIKE ... ESCAPE '\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


# ------------------------------------------------------------------ #
# Placeholder routes — to be implemented step by step                 #
# ------------------------------------------------------------------ #

@app.route("/compare")
def compare():
    return "Compare products — coming in Step 6"


@app.route("/insights")
def insights():
    return "Market insights — coming in Step 7"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
