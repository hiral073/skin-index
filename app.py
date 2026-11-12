import math
from contextlib import closing

from flask import Flask, render_template, request, url_for

from database.db import DB_PATH, get_db
from database.services import get_usd_inr_rate, inr_price

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


# ------------------------------------------------------------------ #
# Placeholder routes — to be implemented step by step                 #
# ------------------------------------------------------------------ #

@app.route("/products/<int:id>")
def product_detail(id):
    return "Product page — coming in Step 4"


@app.route("/compare")
def compare():
    return "Compare products — coming in Step 5"


@app.route("/insights")
def insights():
    return "Market insights — coming in Step 6"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
