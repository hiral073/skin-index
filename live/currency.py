import requests

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
TIMEOUT_SECONDS = 5


class CurrencyError(Exception):
    """The USD to INR rate could not be fetched or read."""


def fetch_usd_inr():
    """Return (rate, rate_date) for 1 USD in INR from Frankfurter (no API key)."""
    try:
        response = requests.get(
            FRANKFURTER_URL,
            params={"base": "USD", "symbols": "INR"},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        rate, rate_date = data["rates"]["INR"], data["date"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise CurrencyError(f"Could not fetch the USD to INR rate: {exc}") from exc

    if data.get("base") != "USD":
        raise CurrencyError("Could not read the USD to INR rate: unexpected base currency")
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0:
        raise CurrencyError(f"Could not read the USD to INR rate: bad value {rate!r}")
    if not isinstance(rate_date, str):
        raise CurrencyError("Could not read the USD to INR rate: missing date")
    return float(rate), rate_date
