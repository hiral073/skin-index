import ast
import os
import re
import sys
import warnings
from collections import Counter
from contextlib import closing

import pandas as pd

from database.db import BASE_DIR, get_db, init_db

CSV_PATH = os.path.join(BASE_DIR, "data", "product_info.csv")
COLUMNS = [
    "product_name", "brand_name", "primary_category", "secondary_category",
    "price_usd", "size", "ingredients",
]

ML_PER_FL_OZ = 29.5735
WATER_WORDS = {"water", "aqua", "eau"}

# Drop reasons, in the order they are checked
NOT_SKINCARE = "not Skincare"
NO_PRICE = "missing price"
NO_SIZE = "missing size"
WEIGHT_SIZE = "size is weight (oz/g), not volume"
MULTIPACK = "multipack size"
BAD_SIZE = "size not readable (count, set, tool)"
NO_INGREDIENTS = "no ingredients"
DUPLICATE = "duplicate product"
DROP_ORDER = [
    NOT_SKINCARE, NO_PRICE, NO_SIZE, WEIGHT_SIZE, MULTIPACK, BAD_SIZE,
    NO_INGREDIENTS, DUPLICATE,
]


def parse_size_ml(text):
    """Return (size_ml, None) or (None, drop_reason)."""
    if not isinstance(text, str) or not text.strip():
        return None, NO_SIZE
    if re.search(r"\d\s*x\s*\d", text, re.I):
        return None, MULTIPACK
    ml = re.search(r"(\d*\.?\d+)\s*ml\b", text, re.I)
    if ml:
        value = float(ml.group(1))
    else:
        oz = re.search(r"(\d*\.?\d+)\s*(?:fl\.?\s*)?oz\b", text, re.I)
        if not oz:
            return None, BAD_SIZE
        if re.search(r"\d\s*g\b", text, re.I):
            return None, WEIGHT_SIZE
        value = round(float(oz.group(1)) * ML_PER_FL_OZ, 2)
    if value <= 0:
        return None, BAD_SIZE
    return value, None


def canonical_ingredient(name):
    """Fold Water / Aqua / Eau variants (e.g. 'Water (Aqua)') into 'Water'."""
    words = re.findall(r"[a-z]+", name.lower())
    if words and set(words) <= WATER_WORDS:
        return "Water"
    return name


def split_ingredients(value):
    """Turn the CSV's list-as-string ingredients into an ordered, de-duplicated list."""
    if not isinstance(value, str):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # stray backslashes in the data
            parsed = ast.literal_eval(value)
        text = " ".join(map(str, parsed)) if isinstance(parsed, list) else str(parsed)
    except (ValueError, SyntaxError):
        text = value
    names, seen = [], set()
    for part in text.split(","):
        name = re.sub(r"\s+", " ", part).strip(" .*")
        if not name:
            continue
        name = canonical_ingredient(name)
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def clean_products(df):
    """Return (product dicts ready to insert, Counter of drop reasons)."""
    drops = Counter()
    skincare = df[df["primary_category"] == "Skincare"]
    drops[NOT_SKINCARE] = len(df) - len(skincare)

    products, seen = [], set()
    for row in skincare.itertuples(index=False):
        if pd.isna(row.price_usd):
            drops[NO_PRICE] += 1
            continue
        size_ml, reason = parse_size_ml(row.size)
        if reason:
            drops[reason] += 1
            continue
        ingredients = split_ingredients(row.ingredients)
        if not ingredients:
            drops[NO_INGREDIENTS] += 1
            continue
        key = (row.brand_name.lower(), row.product_name.lower(), size_ml)
        if key in seen:
            drops[DUPLICATE] += 1
            continue
        seen.add(key)
        products.append({
            "name": row.product_name,
            "brand": row.brand_name,
            "category": None if pd.isna(row.secondary_category) else row.secondary_category,
            "price": float(row.price_usd),
            "size_text": row.size,
            "size_ml": size_ml,
            "price_per_ml": round(float(row.price_usd) / size_ml, 4),
            "ingredients": ingredients,
        })
    return products, drops


def load_products(products, db_path=None):
    """Replace the contents of the three tables with `products`."""
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("DELETE FROM product_ingredients")
        conn.execute("DELETE FROM ingredients")
        conn.execute("DELETE FROM products")

        ingredient_ids = {}
        links = []
        for p in products:
            cur = conn.execute(
                "INSERT INTO products (name, brand, category, price, size_text,"
                " size_ml, price_per_ml, ingredients_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p["name"], p["brand"], p["category"], p["price"], p["size_text"],
                 p["size_ml"], p["price_per_ml"], ", ".join(p["ingredients"])),
            )
            for position, name in enumerate(p["ingredients"], start=1):
                key = name.lower()
                if key not in ingredient_ids:
                    ingredient_ids[key] = conn.execute(
                        "INSERT INTO ingredients (name) VALUES (?)", (name,)
                    ).lastrowid
                links.append((cur.lastrowid, ingredient_ids[key], position))
        conn.executemany(
            "INSERT INTO product_ingredients (product_id, ingredient_id, position)"
            " VALUES (?, ?, ?)",
            links,
        )


def table_counts(db_path=None):
    with closing(get_db(db_path)) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("products", "ingredients", "product_ingredients")
        }


def main(csv_path=None, db_path=None):
    init_db(db_path)
    df = pd.read_csv(csv_path or CSV_PATH, usecols=COLUMNS)
    products, drops = clean_products(df)
    load_products(products, db_path)

    print(f"Rows read: {len(df)}")
    print("Dropped:")
    for reason in DROP_ORDER:
        print(f"  {reason:<40} {drops[reason]:>6}")
    print(f"  {'total dropped':<40} {sum(drops.values()):>6}")
    counts = table_counts(db_path)
    print("Loaded:")
    for table, n in counts.items():
        print(f"  {table:<40} {n:>6}")
    return counts


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
