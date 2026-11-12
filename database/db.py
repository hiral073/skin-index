import os
import sqlite3
from contextlib import closing

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "skin_index.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    brand            TEXT NOT NULL,
    category         TEXT,
    price            REAL,
    size_text        TEXT,
    size_ml          REAL,
    price_per_ml     REAL,
    ingredients_text TEXT
);

CREATE TABLE IF NOT EXISTS ingredients (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- stated_percent is only ever a number the brand printed on the label (NULL
-- when none); it is never inferred or computed.
CREATE TABLE IF NOT EXISTS product_ingredients (
    product_id     INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    stated_percent REAL CHECK (stated_percent IS NULL OR (stated_percent > 0 AND stated_percent < 100)),
    PRIMARY KEY (product_id, ingredient_id)
);

-- rate_date is the date the source publishes the rate for (the last working
-- day at weekends); fetched_on is the day we saved it, so a weekend rate is
-- not fetched again on every page load.
CREATE TABLE IF NOT EXISTS exchange_rates (
    id         INTEGER PRIMARY KEY,
    rate_date  TEXT NOT NULL,
    base       TEXT NOT NULL,
    quote      TEXT NOT NULL,
    rate       REAL NOT NULL,
    fetched_on TEXT NOT NULL,
    UNIQUE (base, quote, rate_date)
);
"""

# (name, brand, category, price, size_text, size_ml, ingredients in label order)
SAMPLE_PRODUCTS = [
    (
        "Hydrating Gel Cleanser", "Aveline", "Cleanser", 14.00, "200 ml", 200,
        ["Water", "Glycerin", "Cocamidopropyl Betaine", "Sodium Hyaluronate", "Panthenol"],
    ),
    (
        "Vitamin C Brightening Serum", "Lumora", "Serum", 32.00, "30 ml", 30,
        ["Water", "Ascorbic Acid", "Glycerin", "Ferulic Acid", "Tocopherol"],
    ),
    (
        "Barrier Repair Moisturizer", "Aveline", "Moisturizer", 24.50, "50 ml", 50,
        ["Water", "Glycerin", "Ceramide NP", "Cholesterol", "Panthenol", "Squalane"],
    ),
    (
        "Daily Mineral Sunscreen SPF 50", "Solenne", "Sunscreen", 18.00, "60 ml", 60,
        ["Zinc Oxide", "Water", "Squalane", "Tocopherol", "Glycerin"],
    ),
    (
        "Soothing Niacinamide Toner", "Lumora", "Toner", 16.00, "150 ml", 150,
        ["Water", "Niacinamide", "Glycerin", "Sodium Hyaluronate", "Allantoin"],
    ),
]


def get_db(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    with closing(get_db(db_path)) as conn:
        conn.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS leaves an older product_ingredients as it was
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(product_ingredients)")}
        if "stated_percent" not in columns:
            conn.execute(
                "ALTER TABLE product_ingredients ADD COLUMN stated_percent REAL"
                " CHECK (stated_percent IS NULL OR (stated_percent > 0 AND stated_percent < 100))"
            )


def seed_db(db_path=None):
    with closing(get_db(db_path)) as conn:
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] > 0:
            return
        with conn:
            for name, brand, category, price, size_text, size_ml, ingredients in SAMPLE_PRODUCTS:
                cur = conn.execute(
                    "INSERT INTO products (name, brand, category, price, size_text,"
                    " size_ml, price_per_ml, ingredients_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, brand, category, price, size_text, size_ml,
                     round(price / size_ml, 4), ", ".join(ingredients)),
                )
                product_id = cur.lastrowid
                for position, ingredient in enumerate(ingredients, start=1):
                    conn.execute(
                        "INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,)
                    )
                    ingredient_id = conn.execute(
                        "SELECT id FROM ingredients WHERE name = ?", (ingredient,)
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT INTO product_ingredients (product_id, ingredient_id, position)"
                        " VALUES (?, ?, ?)",
                        (product_id, ingredient_id, position),
                    )
