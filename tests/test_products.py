import re
from contextlib import closing
from datetime import date

import pytest

from database.db import get_db

# name, brand, category, price, size_ml
PRODUCTS = [
    ("Alpha Serum", "Glow Co", "Serums", 30.0, 30.0),       # 1.0000 / ml
    ("Bravo Cream", "Dew Labs", "Moisturizers", 20.0, 100.0),  # 0.2000 / ml
    ("Charlie Gel", "Glow Co", "Cleansers", 10.0, 10.0),    # 1.0000 / ml
    ("delta Toner", "Pure_Skin", "Toners", 5.0, 250.0),      # 0.0200 / ml
]


def add_products(db_path, rows):
    with closing(get_db(db_path)) as conn, conn:
        conn.executemany(
            "INSERT INTO products (name, brand, category, price, size_text, size_ml, price_per_ml)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(n, b, c, p, f"{s:g} mL", s, round(p / s, 4)) for n, b, c, p, s in rows],
        )


@pytest.fixture
def catalog(app):
    add_products(app.config["DATABASE"], PRODUCTS)
    return app


def product_names(response):
    """Names from PRODUCTS shown on the page, in page order."""
    html = response.get_data(as_text=True)
    shown = [n for n, *_ in PRODUCTS if n in html]
    return sorted(shown, key=html.index)


def row_count(response):
    return response.get_data(as_text=True).count('href="/products/')


def test_products_page_lists_products_with_details(catalog, client):
    response = client.get("/products")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for name, brand, category, *_ in PRODUCTS:
        assert name in html and brand in html and category in html
    assert "$30.00" in html          # price (USD)
    assert "100 mL" in html          # size
    assert "per ml</th>" not in html  # price per ml is not a column (the sort option stays)
    assert "$0.200" not in html


def test_table_columns_in_order_without_a_rate(catalog, client):
    html = client.get("/products").get_data(as_text=True)
    headers = re.findall(r"<th[^>]*>(.*?)</th>", html)
    assert headers == ["Product", "Brand", "Category", "Size", "Price (USD)"]


def test_table_columns_in_order_with_a_rate(catalog, client):
    today = date.today().isoformat()
    save_rate(catalog.config["DATABASE"], 90.0, today, today)
    headers = re.findall(r"<th[^>]*>(.*?)</th>", client.get("/products").get_data(as_text=True))
    assert headers == ["Product", "Brand", "Category", "Size", "Price (USD)", "≈ Price (₹)"]


def test_each_product_links_to_its_detail_page(catalog, client):
    html = client.get("/products").get_data(as_text=True)
    with closing(get_db(catalog.config["DATABASE"])) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM products")]
    for pid in ids:
        assert f'href="/products/{pid}"' in html


@pytest.mark.parametrize("query, expected", [
    ("serum", ["Alpha Serum"]),                  # name, case-insensitive
    ("DEW", ["Bravo Cream"]),                    # brand, case-insensitive
    ("glow", ["Alpha Serum", "Charlie Gel"]),    # several matches
    ("  cream  ", ["Bravo Cream"]),              # surrounding spaces ignored
])
def test_search_matches_name_or_brand(catalog, client, query, expected):
    response = client.get("/products", query_string={"q": query})
    assert product_names(response) == expected


@pytest.mark.parametrize("query", ["%", "' OR 1=1 --", "x'; DROP TABLE products; --"])
def test_search_treats_input_as_plain_text(catalog, client, query):
    response = client.get("/products", query_string={"q": query})
    assert response.status_code == 200
    assert product_names(response) == []
    # table still there
    assert product_names(client.get("/products")) != []


def test_search_underscore_matches_literally(catalog, client):
    # "_" is a LIKE wildcard; it must match only the real underscore, not any character
    assert product_names(client.get("/products", query_string={"q": "pure_skin"})) == ["delta Toner"]
    assert product_names(client.get("/products", query_string={"q": "pure skin"})) == []
    assert product_names(client.get("/products", query_string={"q": "_"})) == ["delta Toner"]


@pytest.mark.parametrize("category, expected", [
    ("Serums", ["Alpha Serum"]),
    ("Cleansers", ["Charlie Gel"]),
    ("", ["Alpha Serum", "Bravo Cream", "Charlie Gel", "delta Toner"]),
    ("Nope", []),
])
def test_category_filter(catalog, client, category, expected):
    response = client.get("/products", query_string={"category": category})
    assert sorted(product_names(response)) == sorted(expected)


def test_category_dropdown_lists_categories(catalog, client):
    html = client.get("/products", query_string={"category": "Toners"}).get_data(as_text=True)
    for _, _, category, *_ in PRODUCTS:
        assert f'<option value="{category}"' in html
    assert '<option value="Toners" selected>' in html


def test_search_and_category_combine(catalog, client):
    response = client.get("/products", query_string={"q": "glow", "category": "Serums"})
    assert product_names(response) == ["Alpha Serum"]


@pytest.mark.parametrize("sort, expected", [
    ("name", ["Alpha Serum", "Bravo Cream", "Charlie Gel", "delta Toner"]),  # case-insensitive
    ("price", ["delta Toner", "Charlie Gel", "Bravo Cream", "Alpha Serum"]),
    # Alpha and Charlie tie at 1.0 per ml, so name breaks the tie
    ("price_per_ml", ["delta Toner", "Bravo Cream", "Alpha Serum", "Charlie Gel"]),
])
def test_sorting(catalog, client, sort, expected):
    response = client.get("/products", query_string={"sort": sort})
    assert product_names(response) == expected


def test_default_sort_is_name(catalog, client):
    assert product_names(client.get("/products")) == [
        "Alpha Serum", "Bravo Cream", "Charlie Gel", "delta Toner",
    ]


def test_unknown_sort_falls_back_to_name(catalog, client):
    response = client.get("/products", query_string={"sort": "price; DROP TABLE products"})
    assert response.status_code == 200
    assert product_names(response)[0] == "Alpha Serum"


def test_empty_database_shows_empty_message(app, client):
    response = client.get("/products")
    assert response.status_code == 200
    assert b"No products found" in response.data
    assert row_count(response) == 0


def test_no_matches_shows_empty_message(catalog, client):
    response = client.get("/products", query_string={"q": "zzz-not-a-product"})
    assert response.status_code == 200
    assert b"No products found" in response.data
    assert row_count(response) == 0
    assert b"Next" not in response.data


def save_rate(db_path, rate, rate_date, fetched_on):
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES (?, 'USD', 'INR', ?, ?)",
            (rate_date, rate, fetched_on),
        )


def test_inr_column_and_note_with_todays_rate(catalog, client):
    save_rate(catalog.config["DATABASE"], 90.0, date.today().isoformat(), date.today().isoformat())
    html = client.get("/products").get_data(as_text=True)
    assert "≈ Price (₹)" in html
    assert "₹1,800" in html          # Bravo Cream: $20 x 90
    assert "₹2,700" in html          # Alpha Serum: $30 x 90
    assert "₹900" in html            # Charlie Gel: $10 x 90
    assert "₹450" in html            # delta Toner: $5 x 90
    assert "per ml</th>" not in html
    assert f"Converted from US prices at 1 USD = ₹90.00 ({date.today().isoformat()})." in html
    assert "Approximate, not Indian retail prices." in html
    assert "(older rate)" not in html


def test_inr_note_says_older_rate_when_stale(catalog, client):
    save_rate(catalog.config["DATABASE"], 88.5, "2026-01-02", "2026-01-02")
    html = client.get("/products").get_data(as_text=True)  # API is offline in tests
    assert "₹1,770" in html          # Bravo Cream: $20 x 88.5
    assert "1 USD = ₹88.50 (2026-01-02). Approximate, not Indian retail prices. (older rate)" in html


def test_inr_fetched_from_api_when_no_rate_saved(catalog, client, rate_api):
    html = client.get("/products").get_data(as_text=True)
    assert "₹1,874" in html          # Bravo Cream: $20 x 93.69 = 1873.8
    assert "1 USD = ₹93.69 (2026-11-11)" in html
    client.get("/products")
    assert len(rate_api.calls) == 1  # second page load reuses the saved rate


def test_inr_hidden_when_no_rate_was_ever_saved(catalog, client):
    html = client.get("/products").get_data(as_text=True)  # API is offline in tests
    assert "₹" not in html
    assert "Price (USD)" in html
    assert "Converted from" not in html
    assert "Approximate" not in html
    assert product_names(client.get("/products")) != []    # USD table still works


def test_inr_price_has_thousands_separators_and_whole_rupees(app, client):
    today = date.today().isoformat()
    save_rate(app.config["DATABASE"], 93.0, today, today)
    add_products(app.config["DATABASE"], [("Luxe Cream", "Pricey", "Moisturizers", 120.0, 50.0)])
    html = client.get("/products").get_data(as_text=True)
    assert "₹11,160" in html         # $120 x 93
    assert "$120.00" in html


def test_inr_price_is_rounded_to_a_whole_rupee(app, client):
    today = date.today().isoformat()
    save_rate(app.config["DATABASE"], 93.69, today, today)
    add_products(app.config["DATABASE"], [("Odd Price", "Brand", "Serums", 12.34, 30.0)])
    html = client.get("/products").get_data(as_text=True)
    assert "₹1,156" in html          # 12.34 x 93.69 = 1156.1346
    assert "1,156.13" not in html


def test_sorting_by_price_per_ml_works_without_showing_it(catalog, client):
    today = date.today().isoformat()
    save_rate(catalog.config["DATABASE"], 90.0, today, today)
    response = client.get("/products", query_string={"sort": "price_per_ml"})
    assert product_names(response) == ["delta Toner", "Bravo Cream", "Alpha Serum", "Charlie Gel"]
    assert "per ml</th>" not in response.get_data(as_text=True)
    assert "$0.200" not in response.get_data(as_text=True)


def test_sorting_by_price_uses_the_actual_price(catalog, client):
    # price order (5, 10, 20, 30) differs from price-per-ml order (0.02, 0.2, 1.0, 1.0)
    response = client.get("/products", query_string={"sort": "price"})
    assert product_names(response) == ["delta Toner", "Charlie Gel", "Bravo Cream", "Alpha Serum"]


@pytest.fixture
def many(app):
    rows = [(f"Product {i:02d}", "Bulk", "Serums", 10.0 + i, 10.0) for i in range(30)]
    add_products(app.config["DATABASE"], rows)
    return app


def test_first_page_has_24_results_and_next_link_only(many, client):
    response = client.get("/products")
    html = response.get_data(as_text=True)
    assert row_count(response) == 24
    assert "Product 23" in html and "Product 24" not in html
    assert 'rel="next"' in html and 'rel="prev"' not in html
    assert "page=2" in html
    assert "30 products" in html


def test_second_page_has_remaining_results_and_previous_link_only(many, client):
    response = client.get("/products", query_string={"page": 2})
    html = response.get_data(as_text=True)
    assert row_count(response) == 6
    assert "Product 24" in html and "Product 23" not in html
    assert 'rel="prev"' in html and 'rel="next"' not in html


def test_pagination_links_keep_filters(many, client):
    html = client.get(
        "/products", query_string={"q": "product", "category": "Serums", "sort": "price"}
    ).get_data(as_text=True)
    next_link = html.split('rel="next"')[0].rsplit("<a", 1)[1]
    assert "q=product" in next_link
    assert "category=Serums" in next_link
    assert "sort=price" in next_link
    assert "page=2" in next_link


@pytest.mark.parametrize("page, expected_rows", [(0, 24), (-3, 24), ("abc", 24), (99, 6)])
def test_out_of_range_page_is_clamped(many, client, page, expected_rows):
    response = client.get("/products", query_string={"page": page})
    assert response.status_code == 200
    assert row_count(response) == expected_rows
