import ast
import os
import re
import sys
import warnings
from collections import Counter, namedtuple
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

# Stated strengths, e.g. "Salicylic Acid 2.0%", "Zinc Oxide (12.025%)", "3% Procapil"
NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
PAREN, TRAILING, LEADING = "(12.5%)", "trailing 2%", "leading 3%"
STRENGTH_FORMATS = [
    (PAREN, re.compile(r"^(?P<name>.*?)\s*\(\s*(?P<num>" + NUMBER + r")\s*%\s*\)$")),
    (TRAILING, re.compile(r"^(?P<name>.*?)\s+(?P<num>" + NUMBER + r")\s*%$")),
    (LEADING, re.compile(r"^(?P<num>" + NUMBER + r")\s*%\s+(?P<name>.+)$")),
]
COLON_PERCENT = re.compile(r":\s*" + NUMBER + r"\s*%\s*\)?$")  # "Name : 0.0408%" fragrance compounds
# A name left over after taking the % off that is not one clean ingredient name: a range
# ("Zinc Oxide 13.20 - 14.00 %"), or a sentence or heading run into the ingredient
UNCLEAR_NAME = re.compile(r"[:;]|\.\s|[-–—/]\s*$|\b(?:to|and|or)\s*$", re.I)
STRENGTH_EXCLUDED = {"Value & Gift Sets", "Mini Size"}  # secondary categories left exactly as they are

# Outcome of looking at one ingredient piece
PLAIN, EXTRACTED, IGNORED_VALUE, IGNORED_COLON, AMBIGUOUS, MERGED = (
    "plain", "extracted", "ignored value", "ignored colon-style", "ambiguous", "merged duplicate",
)
Strength = namedtuple("Strength", "name percent status fmt")
StrengthEvent = namedtuple("StrengthEvent", "status original name percent fmt")

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


def ingredient_pieces(value):
    """The CSV's list-as-string ingredients as cleaned, comma-separated pieces in label order."""
    if not isinstance(value, str):
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # stray backslashes in the data
            parsed = ast.literal_eval(value)
        text = " ".join(map(str, parsed)) if isinstance(parsed, list) else str(parsed)
    except (ValueError, SyntaxError):
        text = value
    pieces = (re.sub(r"\s+", " ", part).strip(" .*") for part in text.split(","))
    return [piece for piece in pieces if piece]


def split_ingredients(value):
    """Turn the CSV's list-as-string ingredients into an ordered, de-duplicated list."""
    names, seen = [], set()
    for piece in ingredient_pieces(value):
        name = canonical_ingredient(piece)
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def parse_strength(piece):
    """Split a stated percentage off an ingredient piece, only when the format is clear.

    Never guesses: anything else containing a % comes back unchanged as AMBIGUOUS.
    """
    if "%" not in piece:
        return Strength(piece, None, PLAIN, None)
    if COLON_PERCENT.search(piece):
        return Strength(piece, None, IGNORED_COLON, None)
    for fmt, pattern in STRENGTH_FORMATS:
        match = pattern.match(piece)
        if not match:
            continue
        name = match.group("name").strip(" ,")
        if "%" in name or not re.search(r"[A-Za-z]", name) or UNCLEAR_NAME.search(name):
            break  # several strengths, a range, or no clean ingredient name left
        value = float(match.group("num"))
        if value <= 0 or value >= 100:
            return Strength(piece, None, IGNORED_VALUE, fmt)  # e.g. "100% Natural ..."
        return Strength(name, value, EXTRACTED, fmt)
    return Strength(piece, None, AMBIGUOUS, None)


def strengths_apply(primary_category, secondary_category):
    return primary_category == "Skincare" and secondary_category not in STRENGTH_EXCLUDED


def parse_ingredients(value, extract_strength=False):
    """Return ([(name, stated_percent or None), ...] in label order, [StrengthEvent, ...]).

    With extract_strength, a clearly stated percentage is split off the name; the
    cleaned name then goes through the alias map and is de-duplicated like any other.
    """
    items, index, events = [], {}, []
    for piece in ingredient_pieces(value):
        strength = parse_strength(piece) if extract_strength else Strength(piece, None, PLAIN, None)
        if strength.status != PLAIN:
            events.append(StrengthEvent(strength.status, piece, strength.name, strength.percent, strength.fmt))
        name = canonical_ingredient(strength.name)
        key = name.lower()
        if key not in index:
            index[key] = len(items)
            items.append((name, strength.percent))
        elif strength.percent is not None:
            # The same ingredient is listed again with a strength: keep the first
            # position, and the strength unless the first entry already has one
            kept_name, kept_percent = items[index[key]]
            if kept_percent is None:
                items[index[key]] = (kept_name, strength.percent)
            events.append(StrengthEvent(MERGED, piece, kept_name, strength.percent, strength.fmt))
    return items, events


class StrengthReport:
    """What the strength parsing did to the kept products, for the loader's printed report."""

    def __init__(self):
        self.rows = []  # (product name, secondary category, StrengthEvent)

    def add(self, product_name, category, events):
        self.rows.extend((product_name, category, event) for event in events)

    def with_status(self, status):
        return [row for row in self.rows if row[2].status == status]


def spread(items, count):
    """`count` items spread evenly across the list."""
    count = min(count, len(items))
    return [items[int(i * len(items) / count)] for i in range(count)] if count else []


def pick_examples(events, n=30):
    """Up to n varied extracted strengths: every format is shown, one per ingredient name
    and format first; if there are fewer than n of those, other distinct texts fill up."""
    ordered = sorted(events, key=lambda e: (e.name.lower(), e.fmt, e.percent))
    first_per_name, seen = [], set()
    for event in ordered:
        if (event.name.lower(), event.fmt) not in seen:
            seen.add((event.name.lower(), event.fmt))
            first_per_name.append(event)
    rare = [e for e in first_per_name if e.fmt != TRAILING][: n // 3]
    picked = rare + spread([e for e in first_per_name if e.fmt == TRAILING], n - len(rare))
    if len(picked) < n:
        chosen, texts = set(picked), set()
        extra = []
        for event in ordered:
            if event not in chosen and event.original.lower() not in texts:
                texts.add(event.original.lower())
                extra.append(event)
        picked += spread(extra, n - len(picked))
    return picked


def clean_products(df, report=None):
    """Return (product dicts ready to insert, Counter of drop reasons).

    Pass a StrengthReport to collect what the strength parsing did.
    """
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
        ingredients, events = parse_ingredients(
            row.ingredients,
            extract_strength=strengths_apply(row.primary_category, row.secondary_category),
        )
        if not ingredients:
            drops[NO_INGREDIENTS] += 1
            continue
        key = (row.brand_name.lower(), row.product_name.lower(), size_ml)
        if key in seen:
            drops[DUPLICATE] += 1
            continue
        seen.add(key)
        if report is not None:
            report.add(row.product_name, row.secondary_category, events)
        products.append({
            "name": row.product_name,
            "brand": row.brand_name,
            "category": None if pd.isna(row.secondary_category) else row.secondary_category,
            "price": float(row.price_usd),
            "size_text": row.size,
            "size_ml": size_ml,
            "price_per_ml": round(float(row.price_usd) / size_ml, 4),
            "ingredients": [name for name, _ in ingredients],
            "stated_percents": [percent for _, percent in ingredients],
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
            percents = p.get("stated_percents") or [None] * len(p["ingredients"])
            for position, (name, percent) in enumerate(zip(p["ingredients"], percents), start=1):
                key = name.lower()
                if key not in ingredient_ids:
                    ingredient_ids[key] = conn.execute(
                        "INSERT INTO ingredients (name) VALUES (?)", (name,)
                    ).lastrowid
                links.append((cur.lastrowid, ingredient_ids[key], position, percent))
        conn.executemany(
            "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
            " VALUES (?, ?, ?, ?)",
            links,
        )


def table_counts(db_path=None):
    with closing(get_db(db_path)) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("products", "ingredients", "product_ingredients")
        }


def percent_text(value):
    return f"{value:g}%"


def print_strength_report(report, products, before, after):
    stored = sum(p is not None for product in products for p in product["stated_percents"])
    with_strength = sum(any(p is not None for p in product["stated_percents"]) for product in products)
    extracted = report.with_status(EXTRACTED)
    ambiguous = report.with_status(AMBIGUOUS)
    merged = report.with_status(MERGED)

    print("\nStated strengths (only what the brand printed; nothing inferred):")
    print(f"  {'products, before -> after':<40} {before['products']:>6} -> {after['products']}")
    print(f"  {'distinct ingredients, before -> after':<40} {before['ingredients']:>6} -> {after['ingredients']}")
    print(f"  {'strengths recognised':<40} {len(extracted):>6}")
    print(f"  {'strengths stored (stated_percent)':<40} {stored:>6}")
    print(f"  {'products with a stated strength':<40} {with_strength:>6}")
    print(f"  {'ignored: value 100 or more, or 0':<40} {len(report.with_status(IGNORED_VALUE)):>6}")
    print(f"  {'ignored: colon-style compound':<40} {len(report.with_status(IGNORED_COLON)):>6}")
    print(f"  {'merged duplicate ingredient names':<40} {len(merged):>6}")
    print(f"  {'ambiguous, left unchanged':<40} {len(ambiguous):>6}")

    print(f"\nExamples ({min(30, len(extracted))} varied; original text -> cleaned name + percent):")
    for event in pick_examples([e for _, _, e in extracted]):
        print(f"  [{event.fmt}] {event.original}  ->  {event.name} + {percent_text(event.percent)}")

    print("\nAmbiguous, left unchanged (product [category] :: text):")
    for product_name, category, event in ambiguous:
        print(f"  {product_name} [{category}] :: {event.original}")

    print("\nMerged duplicates (the first position is kept):")
    for product_name, category, event in merged:
        print(f"  {product_name} [{category}] :: {event.original}  ->  {event.name} + {percent_text(event.percent)}")


def main(csv_path=None, db_path=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # product names are not all console-safe
    init_db(db_path)
    before = table_counts(db_path)
    df = pd.read_csv(csv_path or CSV_PATH, usecols=COLUMNS)
    report = StrengthReport()
    products, drops = clean_products(df, report)
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
    print_strength_report(report, products, before, counts)
    return counts


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
