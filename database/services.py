import time
from collections import namedtuple
from contextlib import closing
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from database.db import get_db, init_db
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
    with closing(get_db(db_path)) as conn:
        product = conn.execute(
            "SELECT id, name, brand, category, size_text, price, price_per_ml"
            " FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
        if product is None:
            return None
        ingredients = conn.execute(
            "SELECT i.name, pi.stated_percent FROM product_ingredients pi"
            " JOIN ingredients i ON i.id = pi.ingredient_id"
            " WHERE pi.product_id = ? ORDER BY pi.position",
            (product_id,),
        ).fetchall()
    return {
        **product,
        "ingredients": [
            {"name": row["name"], "stated_percent": row["stated_percent"]} for row in ingredients
        ],
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
