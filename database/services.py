import time
from collections import namedtuple
from contextlib import closing
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from database.db import COMPARE_DROPDOWN_MAX, get_db, init_db
from live.currency import CurrencyError, fetch_usd_inr

# stale is True when the rate is older than today's and today's fetch failed
RateInfo = namedtuple("RateInfo", ["rate", "rate_date", "stale"])

# After a failed fetch, do not try again for a while: otherwise an API outage
# would cost every page load a full request timeout.
RETRY_AFTER_FAILURE_SECONDS = 15 * 60
_last_failure = None  # time.monotonic() of the last failed fetch


def reset_rate_cooldown():
    global _last_failure
    _last_failure = None


def get_usd_inr_rate(db_path=None, today=None):
    """Return a RateInfo for 1 USD in INR, or None if no rate was ever saved.

    A rate already fetched today is returned without any network call. Otherwise
    the rate is fetched and saved; if that fails, the newest saved rate comes back
    marked stale. A rate is never made up.
    """
    global _last_failure
    today = today or date.today().isoformat()
    init_db(db_path)  # databases created before exchange_rates existed get the table
    with closing(get_db(db_path)) as conn:
        saved = conn.execute(
            "SELECT rate, rate_date, fetched_on FROM exchange_rates"
            " WHERE base = 'USD' AND quote = 'INR'"
            " ORDER BY rate_date DESC, fetched_on DESC LIMIT 1"
        ).fetchone()
        if saved and saved["fetched_on"] == today:
            return RateInfo(saved["rate"], saved["rate_date"], False)

        cooling_down = (
            _last_failure is not None
            and time.monotonic() - _last_failure < RETRY_AFTER_FAILURE_SECONDS
        )
        if not cooling_down:
            try:
                rate, rate_date = fetch_usd_inr()
            except CurrencyError:
                _last_failure = time.monotonic()
            else:
                _last_failure = None
                with conn:
                    conn.execute(
                        "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                        " VALUES (?, 'USD', 'INR', ?, ?)"
                        " ON CONFLICT (base, quote, rate_date)"
                        " DO UPDATE SET rate = excluded.rate, fetched_on = excluded.fetched_on",
                        (rate_date, rate, today),
                    )
                return RateInfo(rate, rate_date, False)

        if saved:
            return RateInfo(saved["rate"], saved["rate_date"], True)
        return None


def get_product_detail(product_id, db_path=None):
    """One product as a dict with its ingredients in label order, or None if unknown.

    `ingredients` is a list of {"name", "stated_percent"}; stated_percent is the
    number the brand printed, or None when it printed none. Fields that are
    missing in the database come back as None, and `ingredients` is an empty list
    when the product has none.
    """
    init_db(db_path)  # databases from before compare_group existed get the column
    with closing(get_db(db_path)) as conn:
        loaded = _load_product(conn, product_id)
    if loaded is None:
        return None
    product, ingredients = loaded
    return {
        **product,
        "ingredients": [
            {"name": row["name"], "stated_percent": row["stated_percent"]} for row in ingredients
        ],
    }


def _load_product(conn, product_id):
    """(product row as a dict, ingredient rows with ids in label order), or None if unknown."""
    if isinstance(product_id, bool) or not isinstance(product_id, int) or not 0 < product_id < 2**63:
        return None  # not a usable id (SQLite would raise on integers beyond 64 bits)
    product = conn.execute(
        "SELECT id, name, brand, category, compare_group, size_text, price, price_per_ml"
        " FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    if product is None:
        return None
    ingredients = conn.execute(
        "SELECT i.id AS ingredient_id, i.name, pi.stated_percent FROM product_ingredients pi"
        " JOIN ingredients i ON i.id = pi.ingredient_id"
        " WHERE pi.product_id = ? ORDER BY pi.position",
        (product_id,),
    ).fetchall()
    return dict(product), [dict(row) for row in ingredients]


def escape_like(text):
    """Make %, _ and \\ in user text match literally inside LIKE ... ESCAPE '\\'."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ------------------------------------------------------------------ #
# Compare: groups, dropdown lists and the comparison itself          #
# ------------------------------------------------------------------ #

def list_groups(db_path=None):
    """Comparison groups that have at least two products, by name: [{"name", "products"}]."""
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        rows = conn.execute(
            "SELECT compare_group AS name, COUNT(*) AS products FROM products"
            " WHERE compare_group IS NOT NULL GROUP BY compare_group HAVING COUNT(*) >= 2"
            " ORDER BY compare_group COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def list_brands_in_group(group, db_path=None):
    """Brands that have products in a group, by name: [{"brand", "products"}]."""
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        rows = conn.execute(
            "SELECT brand, COUNT(*) AS products FROM products WHERE compare_group = ?"
            " GROUP BY brand ORDER BY brand COLLATE NOCASE",
            (group,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_products_in_group(group, brand=None, q=None, exclude_id=None, db_path=None):
    """Products for a dropdown, sorted by name.

    Returns {"products": [{"id", "name", "brand", "size_text", "price"}], "total",
    "needs_brand", "capped"}. A group with more than COMPARE_DROPDOWN_MAX products lists
    nothing until a brand is given (needs_brand); no list is longer than that maximum
    (capped says there were more matches). `exclude_id` leaves one product out.
    """
    init_db(db_path)
    q = (q or "").strip()
    with closing(get_db(db_path)) as conn:
        in_group = conn.execute(
            "SELECT COUNT(*) FROM products WHERE compare_group = ?", (group,)
        ).fetchone()[0]
        if in_group > COMPARE_DROPDOWN_MAX and not brand:
            return {"products": [], "total": in_group, "needs_brand": True, "capped": False}
        params = {
            "group": group, "brand": brand or "", "q": q, "like": f"%{escape_like(q)}%",
            "exclude": exclude_id, "limit": COMPARE_DROPDOWN_MAX,
        }
        rows = conn.execute(
            "SELECT id, name, brand, size_text, price FROM products"
            " WHERE compare_group = :group AND (:brand = '' OR brand = :brand)"
            " AND (:exclude IS NULL OR id != :exclude)"
            " AND (:q = '' OR name LIKE :like ESCAPE '\\' OR brand LIKE :like ESCAPE '\\')"
            " ORDER BY name COLLATE NOCASE, brand COLLATE NOCASE, id LIMIT :limit",
            params,
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM products"
            " WHERE compare_group = :group AND (:brand = '' OR brand = :brand)"
            " AND (:exclude IS NULL OR id != :exclude)"
            " AND (:q = '' OR name LIKE :like ESCAPE '\\' OR brand LIKE :like ESCAPE '\\')",
            {k: v for k, v in params.items() if k != "limit"},
        ).fetchone()[0]
    return {
        "products": [dict(row) for row in rows], "total": total,
        "needs_brand": False, "capped": total > len(rows),
    }


def compare_products(a_id, b_id, db_path=None):
    """Compare two products; plain data only (no formatting, no currency).

    Returns {"a", "b", "a_state", "b_state", "status", "comparable", "a_group", "b_group",
    "price_per_ml", "ingredients"}.
    - a, b: the product as in get_product_detail, or None.
    - a_state, b_state: "not chosen" (id None), "unknown" (no such product) or "found".
    - status: "waiting" (a side is not found), "same_product", "no_group" (a product has no
      comparison group), "different_groups" or "ok". comparable is True only for "ok".
    - price_per_ml (comparable only): {"a", "b", "cheaper": "a"/"b"/"equal"/None,
      "percent"}, percent = how much less the cheaper one costs per ml, as a share of
      the dearer one; cheaper and percent are None when either price per ml is missing.
    - ingredients (comparable, both with ingredients, else None): {"shared": [{"name",
      "a_percent", "b_percent"}] in A's label order, "only_a", "only_b" (names), the three
      counts, "total_count" (distinct across both) and "overlap_percent" = shared / total.
    Strengths are the brand's stated numbers (or None), never worked out.
    """
    init_db(db_path)
    with closing(get_db(db_path)) as conn:
        loaded = {"a": _load_product(conn, a_id), "b": _load_product(conn, b_id)}

    def state(side, product_id):
        if product_id is None:
            return "not chosen"
        return "found" if loaded[side] is not None else "unknown"

    states = {"a": state("a", a_id), "b": state("b", b_id)}
    products, rows = {}, {}
    for side in ("a", "b"):
        if loaded[side] is None:
            products[side], rows[side] = None, []
        else:
            product, ingredient_rows = loaded[side]
            rows[side] = ingredient_rows
            products[side] = {
                **product,
                "ingredients": [
                    {"name": r["name"], "stated_percent": r["stated_percent"]} for r in ingredient_rows
                ],
            }
    a, b = products["a"], products["b"]
    result = {
        "a": a, "b": b, "a_state": states["a"], "b_state": states["b"],
        "a_group": a and a["compare_group"], "b_group": b and b["compare_group"],
        "status": None, "comparable": False, "price_per_ml": None, "ingredients": None,
    }
    if a is None or b is None:
        result["status"] = "waiting"
    elif a["id"] == b["id"]:
        result["status"] = "same_product"
    elif a["compare_group"] is None or b["compare_group"] is None:
        result["status"] = "no_group"
    elif a["compare_group"] != b["compare_group"]:
        result["status"] = "different_groups"
    else:
        result["status"] = "ok"
        result["comparable"] = True
        result["price_per_ml"] = _compare_price_per_ml(a["price_per_ml"], b["price_per_ml"])
        result["ingredients"] = _compare_ingredients(rows["a"], rows["b"])
    return result


def _compare_price_per_ml(a_value, b_value):
    out = {"a": a_value, "b": b_value, "cheaper": None, "percent": None}
    if a_value is None or b_value is None:
        return out
    if a_value == b_value:
        out["cheaper"], out["percent"] = "equal", 0.0
        return out
    cheaper, dearer = (a_value, b_value) if a_value < b_value else (b_value, a_value)
    out["cheaper"] = "a" if a_value < b_value else "b"
    out["percent"] = (dearer - cheaper) / dearer * 100
    return out


def _compare_ingredients(a_rows, b_rows):
    if not a_rows or not b_rows:
        return None
    a_by_id = {r["ingredient_id"]: r for r in a_rows}
    b_by_id = {r["ingredient_id"]: r for r in b_rows}
    shared = [
        {"name": r["name"], "a_percent": r["stated_percent"],
         "b_percent": b_by_id[r["ingredient_id"]]["stated_percent"]}
        for r in a_rows if r["ingredient_id"] in b_by_id
    ]
    only_a = [r["name"] for r in a_rows if r["ingredient_id"] not in b_by_id]
    only_b = [r["name"] for r in b_rows if r["ingredient_id"] not in a_by_id]
    total = len(shared) + len(only_a) + len(only_b)
    return {
        "shared": shared, "only_a": only_a, "only_b": only_b,
        "shared_count": len(shared), "only_a_count": len(only_a), "only_b_count": len(only_b),
        "total_count": total, "overlap_percent": len(shared) / total * 100,
    }


def inr_price(price_usd, rate):
    """USD price to whole rupees, halves rounded up; None if either input is missing."""
    if price_usd is None or rate is None:
        return None
    # Decimal on the printed values: float 452.5 rounds half up here, not to even
    exact = Decimal(str(price_usd)) * Decimal(str(rate))
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def inr_per_ml(price_per_ml_usd, rate):
    """USD per ml to INR per ml, rounded to 2 decimals; None if either input is missing."""
    if price_per_ml_usd is None or rate is None:
        return None
    return round(price_per_ml_usd * rate, 2)
