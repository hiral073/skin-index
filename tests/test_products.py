from contextlib import closing

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
    assert "$30.00" in html          # price
    assert "100 mL" in html          # size
    assert "$0.200" in html          # price per ml


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
