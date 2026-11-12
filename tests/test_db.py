import sqlite3
from contextlib import closing

import pytest

from database.db import get_db, init_db, seed_db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def query(db_path, sql, params=()):
    with closing(get_db(db_path)) as conn:
        return conn.execute(sql, params).fetchall()


def test_init_db_creates_tables(db_path):
    init_db(db_path)
    rows = query(db_path, "SELECT name FROM sqlite_master WHERE type = 'table'")
    names = {row["name"] for row in rows}
    assert {"products", "ingredients", "product_ingredients", "exchange_rates"} <= names


def product_ingredient_columns(db_path):
    return [r["name"] for r in query(db_path, "PRAGMA table_info(product_ingredients)")]


def test_new_database_has_stated_percent_column(db_path):
    init_db(db_path)
    assert "stated_percent" in product_ingredient_columns(db_path)


def test_init_db_adds_stated_percent_to_an_older_database_and_keeps_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn, conn:   # the schema before this column
        conn.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,"
            " category TEXT, price REAL, size_text TEXT, size_ml REAL, price_per_ml REAL,"
            " ingredients_text TEXT);"
            "CREATE TABLE ingredients (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);"
            "CREATE TABLE product_ingredients (product_id INTEGER NOT NULL REFERENCES products(id)"
            " ON DELETE CASCADE, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id)"
            " ON DELETE CASCADE, position INTEGER NOT NULL, PRIMARY KEY (product_id, ingredient_id));"
            "INSERT INTO products (id, name, brand) VALUES (1, 'Old', 'Brand');"
            "INSERT INTO ingredients (id, name) VALUES (1, 'Water');"
            "INSERT INTO product_ingredients VALUES (1, 1, 1);"
        )
    assert "stated_percent" not in product_ingredient_columns(db_path)
    init_db(db_path)
    init_db(db_path)   # idempotent
    assert "stated_percent" in product_ingredient_columns(db_path)
    rows = query(db_path, "SELECT product_id, ingredient_id, position, stated_percent FROM product_ingredients")
    assert [tuple(r) for r in rows] == [(1, 1, 1, None)]


def product_columns(db_path):
    return [r["name"] for r in query(db_path, "PRAGMA table_info(products)")]


def test_new_database_has_compare_group_column(db_path):
    init_db(db_path)
    assert "compare_group" in product_columns(db_path)


def test_init_db_adds_compare_group_to_an_older_products_table_and_keeps_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn, conn:    # products before compare_group
        conn.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,"
            " category TEXT, price REAL, size_text TEXT, size_ml REAL, price_per_ml REAL,"
            " ingredients_text TEXT);"
            "INSERT INTO products (id, name, brand, category) VALUES (1, 'Old', 'Brand', 'Serum');"
        )
    init_db(db_path)
    init_db(db_path)   # idempotent
    assert "compare_group" in product_columns(db_path)
    assert [tuple(r) for r in query(db_path, "SELECT id, name, compare_group FROM products")] == [(1, "Old", None)]


def test_new_database_has_the_popularity_columns(db_path):
    init_db(db_path)
    assert {"loves_count", "rating", "reviews"} <= set(product_columns(db_path))


def test_init_db_adds_the_popularity_columns_to_an_older_products_table_and_keeps_rows(db_path):
    with closing(sqlite3.connect(db_path)) as conn, conn:    # products before loves, rating and reviews
        conn.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL,"
            " category TEXT, price REAL, size_text TEXT, size_ml REAL, price_per_ml REAL,"
            " ingredients_text TEXT, compare_group TEXT);"
            "INSERT INTO products (id, name, brand, compare_group) VALUES (1, 'Old', 'Brand', 'Serums');"
        )
    init_db(db_path)
    init_db(db_path)   # idempotent
    assert {"loves_count", "rating", "reviews"} <= set(product_columns(db_path))
    rows = query(db_path, "SELECT id, name, compare_group, loves_count, rating, reviews FROM products")
    assert [tuple(r) for r in rows] == [(1, "Old", "Serums", None, None, None)]


def test_popularity_values_round_trip_and_may_be_empty(db_path):
    init_db(db_path)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("INSERT INTO products (name, brand, loves_count, rating, reviews) VALUES ('a', 'b', 763168, 4.3815, 1376)")
        conn.execute("INSERT INTO products (name, brand) VALUES ('c', 'd')")
    rows = query(db_path, "SELECT loves_count, rating, reviews FROM products ORDER BY id")
    assert [tuple(r) for r in rows] == [(763168, 4.3815, 1376), (None, None, None)]


def test_seed_db_gives_each_product_a_compare_group(db_path):
    init_db(db_path)
    seed_db(db_path)
    rows = query(db_path, "SELECT category, compare_group FROM products")
    assert len(rows) == 5 and all(r["compare_group"] == r["category"] for r in rows)


@pytest.mark.parametrize("bad", [0, -1, 100, 150])
def test_stated_percent_must_be_between_0_and_100(db_path, bad):
    init_db(db_path)
    seed_db(db_path)
    with closing(get_db(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE product_ingredients SET stated_percent = ?", (bad,))


def test_stated_percent_accepts_null_and_a_value_in_range(db_path):
    init_db(db_path)
    seed_db(db_path)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("UPDATE product_ingredients SET stated_percent = 12.025 WHERE position = 1")
    assert query(db_path, "SELECT COUNT(*) FROM product_ingredients WHERE stated_percent = 12.025")[0][0] > 0
    assert query(db_path, "SELECT COUNT(*) FROM product_ingredients WHERE stated_percent IS NULL")[0][0] > 0


def test_exchange_rates_survive_a_second_init_db(db_path):
    init_db(db_path)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES ('2026-11-11', 'USD', 'INR', 93.69, '2026-11-11')"
        )
    init_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM exchange_rates")[0][0] == 1


def test_exchange_rates_are_unique_per_pair_and_date(db_path):
    init_db(db_path)
    insert = (
        "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
        " VALUES ('2026-11-11', 'USD', 'INR', 93.69, '2026-11-11')"
    )
    with closing(get_db(db_path)) as conn:
        conn.execute(insert)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert)


def test_init_db_is_idempotent(db_path):
    init_db(db_path)
    init_db(db_path)


def test_get_db_uses_row_factory_and_foreign_keys(db_path):
    with closing(get_db(db_path)) as conn:
        assert conn.row_factory is sqlite3.Row
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_seed_db_inserts_five_products(db_path):
    init_db(db_path)
    seed_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM products")[0][0] == 5


def test_seed_db_twice_does_not_duplicate(db_path):
    init_db(db_path)
    seed_db(db_path)
    seed_db(db_path)
    assert query(db_path, "SELECT COUNT(*) FROM products")[0][0] == 5


def test_seed_db_ingredients_are_unique_and_shared(db_path):
    init_db(db_path)
    seed_db(db_path)
    names = [r["name"] for r in query(db_path, "SELECT name FROM ingredients")]
    assert names
    assert len(names) == len(set(names))
    links = query(db_path, "SELECT COUNT(*) FROM product_ingredients")[0][0]
    assert links > len(names)  # at least one ingredient used by several products


def test_seed_db_positions_follow_label_order(db_path):
    init_db(db_path)
    seed_db(db_path)
    for product in query(db_path, "SELECT id FROM products"):
        positions = [
            r["position"]
            for r in query(
                db_path,
                "SELECT position FROM product_ingredients WHERE product_id = ?"
                " ORDER BY position",
                (product["id"],),
            )
        ]
        assert positions == list(range(1, len(positions) + 1))


def test_seed_db_price_per_ml(db_path):
    init_db(db_path)
    seed_db(db_path)
    for row in query(db_path, "SELECT price, size_ml, price_per_ml FROM products"):
        assert row["price_per_ml"] == pytest.approx(row["price"] / row["size_ml"], abs=1e-4)


def test_foreign_key_is_enforced(db_path):
    init_db(db_path)
    seed_db(db_path)
    with closing(get_db(db_path)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position)"
                " VALUES (999, 1, 1)"
            )
