from contextlib import closing
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from database.db import get_db

TODAY = date.today().isoformat()


def add_product(db_path, name="Bravo Cream", brand="Dew Labs", category="Moisturizers",
                price=20.0, size_text="100 mL", price_per_ml=0.2, ingredients=()):
    """Insert one product (any field may be None) and its ingredients; return its id."""
    with closing(get_db(db_path)) as conn, conn:
        product_id = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, size_ml, price_per_ml)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category, price, size_text, None, price_per_ml),
        ).lastrowid
        for position, ingredient, *percent in ingredients:   # (position, name[, stated_percent])
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            ingredient_id = conn.execute(
                "SELECT id FROM ingredients WHERE name = ?", (ingredient,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
                " VALUES (?, ?, ?, ?)",
                (product_id, ingredient_id, position, percent[0] if percent else None),
            )
    return product_id


def save_rate(db_path, rate, rate_date=TODAY, fetched_on=TODAY):
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES (?, 'USD', 'INR', ?, ?)",
            (rate_date, rate, fetched_on),
        )


# Stored out of order on purpose: the page must follow `position`
INGREDIENTS = [(3, "Squalane"), (1, "Water"), (4, "Tocopherol"), (2, "Glycerin")]


@pytest.fixture
def product_id(app):
    return add_product(app.config["DATABASE"], ingredients=INGREDIENTS)


def get_html(client, url):
    response = client.get(url)
    return response, response.get_data(as_text=True)


def test_detail_page_shows_product_facts(app, client, product_id):
    save_rate(app.config["DATABASE"], 90.0)
    response, html = get_html(client, f"/products/{product_id}")
    assert response.status_code == 200
    assert "Bravo Cream" in html and "Dew Labs" in html and "Moisturizers" in html
    assert "100 mL" in html
    assert "$20.00" in html
    assert "₹1,800" in html           # $20 x 90, whole rupees
    assert "$0.200" in html           # price per ml (USD)
    assert "₹18.00" in html           # 0.2 x 90, two decimals
    assert "Converted from US prices at 1 USD = ₹90.00 (" in html
    assert "Approximate, not Indian retail prices." in html
    assert "(older rate)" not in html
    assert "Not available" not in html


def test_ingredients_are_numbered_in_label_order(client, product_id):
    _, html = get_html(client, f"/products/{product_id}")
    assert "<ol" in html
    items = [i.split("</li>")[0].strip() for i in html.split("<li>")[1:]]
    assert items == ["Water", "Glycerin", "Squalane", "Tocopherol"]
    assert "Ingredients are listed roughly from highest to lowest concentration." in html


STRENGTH_NOTE = "Only some brands state strengths. A missing percentage means not stated, not low."


def list_items(html):
    return [i.split("</li>")[0] for i in html.split("<li>")[1:]]


def test_stated_percent_badge_only_on_ingredients_that_have_one(app, client):
    pid = add_product(
        app.config["DATABASE"],
        ingredients=[(1, "Water"), (2, "Zinc Oxide", 12.025), (3, "Glycerin"),
                     (4, "Salicylic Acid", 2.0), (5, "Fragrance Compound", 0.0408)],
    )
    _, html = get_html(client, f"/products/{pid}")
    items = list_items(html)
    assert [i.split("<span")[0].strip() for i in items] == [
        "Water", "Zinc Oxide", "Glycerin", "Salicylic Acid", "Fragrance Compound",
    ]
    assert "stated by brand" not in items[0] and "stated by brand" not in items[2]
    assert "12.025% (stated by brand)" in items[1]
    assert "2% (stated by brand)" in items[3] and "2.0%" not in items[3]
    assert "0.0408% (stated by brand)" in items[4]
    assert html.count("(stated by brand)") == 3
    assert STRENGTH_NOTE in html


def test_no_strength_note_when_no_ingredient_has_a_percent(client, product_id):
    _, html = get_html(client, f"/products/{product_id}")
    assert "stated by brand" not in html
    assert "Only some brands state strengths" not in html


def test_product_without_ingredients_shows_no_strength_note(app, client):
    pid = add_product(app.config["DATABASE"], ingredients=[])
    _, html = get_html(client, f"/products/{pid}")
    assert "Only some brands state strengths" not in html


def test_unknown_id_gives_a_friendly_404(client, product_id):
    response, html = get_html(client, "/products/99999")
    assert response.status_code == 404
    assert "navbar" in html                     # extends base.html
    assert "We couldn't find that" in html
    assert 'href="/products"' in html


def test_non_numeric_id_gives_404(client):
    response, html = get_html(client, "/products/abc")
    assert response.status_code == 404
    assert "We couldn't find that" in html


def test_404_does_not_fetch_a_rate(client, rate_api):
    client.get("/products/99999")
    assert rate_api.calls == []


def back_link_args(html):
    href = html.split('class="back-link" href="')[1].split('"')[0].replace("&amp;", "&")
    parsed = urlparse(href)
    return parsed.path, parse_qs(parsed.query)


def test_back_link_keeps_search_filter_sort_and_page(client, product_id):
    _, html = get_html(
        client, f"/products/{product_id}?q=cream&category=Moisturizers&sort=price&page=3"
    )
    path, args = back_link_args(html)
    assert path == "/products"
    assert args == {"q": ["cream"], "category": ["Moisturizers"], "sort": ["price"], "page": ["3"]}


def test_back_link_keeps_special_characters(client, product_id):
    _, html = get_html(client, f"/products/{product_id}?q=vitamin%20c%20%26%20e")
    assert back_link_args(html) == ("/products", {"q": ["vitamin c & e"]})


def test_back_link_is_plain_without_a_query_string(client, product_id):
    _, html = get_html(client, f"/products/{product_id}")
    assert back_link_args(html) == ("/products", {})
    assert "Back to results" in html


@pytest.mark.parametrize("query", [
    "sort=evil&page=abc&foo=bar&next=http://evil.example",
    "sort=name&page=1",           # defaults are left out
    "page=0&page=-4",
])
def test_back_link_drops_unknown_or_invalid_params(client, product_id, query):
    _, html = get_html(client, f"/products/{product_id}?{query}")
    assert back_link_args(html) == ("/products", {})
    assert "evil" not in html.split('class="back-link"')[1].split("</a>")[0]


def test_product_with_missing_data_still_renders(app, client):
    pid = add_product(
        app.config["DATABASE"], name="Mystery Balm", category=None, price=None,
        size_text=None, price_per_ml=None, ingredients=[],
    )
    response, html = get_html(client, f"/products/{pid}")
    assert response.status_code == 200
    assert "Mystery Balm" in html
    assert html.count("Not available") == 5     # category, size, price, price per ml, ingredients
    assert "<ol" not in html
    assert "highest to lowest" not in html
    assert "₹" not in html                      # no rate saved, API offline


def test_missing_data_with_a_rate_shows_not_available_for_rupees_too(app, client):
    save_rate(app.config["DATABASE"], 90.0)
    pid = add_product(
        app.config["DATABASE"], name="Mystery Balm", price=None, price_per_ml=None,
        ingredients=[(1, "Water")],
    )
    response, html = get_html(client, f"/products/{pid}")
    assert response.status_code == 200
    assert html.count("Not available") == 4     # price, ≈ price, price per ml, ≈ per ml
    assert "₹90.00" in html                     # the rate note still shows the rate
    assert "<ol" in html


def test_no_rate_hides_all_inr_and_the_note(client, product_id):
    _, html = get_html(client, f"/products/{product_id}")   # API offline in tests
    assert "$20.00" in html and "$0.200" in html
    assert "₹" not in html
    assert "Converted from" not in html
    assert "Approximate" not in html


def test_stale_rate_is_marked_older(app, client, product_id):
    save_rate(app.config["DATABASE"], 88.5, rate_date="2026-01-02", fetched_on="2026-01-02")
    _, html = get_html(client, f"/products/{product_id}")
    assert "₹1,770" in html                     # $20 x 88.5
    assert "1 USD = ₹88.50 (2026-01-02). Approximate, not Indian retail prices. (older rate)" in html


def test_rate_is_fetched_once_for_list_and_detail(app, client, product_id, rate_api):
    client.get(f"/products/{product_id}")
    client.get("/products")
    assert len(rate_api.calls) == 1
