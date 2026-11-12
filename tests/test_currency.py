import pytest
import requests

from live.currency import CurrencyError, fetch_usd_inr


def test_fetch_usd_inr_parses_rate_and_date(rate_api):
    assert fetch_usd_inr() == (93.69, "2026-11-11")


def test_fetch_usd_inr_asks_for_usd_to_inr_with_5_second_timeout(rate_api):
    fetch_usd_inr()
    (url, kwargs), = rate_api.calls
    assert url == "https://api.frankfurter.dev/v1/latest"
    assert kwargs["params"] == {"base": "USD", "symbols": "INR"}
    assert kwargs["timeout"] == 5


@pytest.mark.parametrize("error", [
    requests.Timeout("timed out"),
    requests.ConnectionError("no route"),
])
def test_fetch_usd_inr_network_errors_become_currency_error(rate_api, error):
    rate_api.error = error
    with pytest.raises(CurrencyError, match="Could not fetch the USD to INR rate"):
        fetch_usd_inr()


def test_fetch_usd_inr_http_error_status(rate_api):
    rate_api.status = 500
    with pytest.raises(CurrencyError, match="500"):
        fetch_usd_inr()


@pytest.mark.parametrize("payload", [
    ValueError("not json"),
    {},
    {"base": "USD", "date": "2026-11-11", "rates": {}},
    {"base": "USD", "date": "2026-11-11", "rates": {"INR": "93.69"}},
    {"base": "USD", "date": "2026-11-11", "rates": {"INR": 0}},
    {"base": "USD", "date": "2026-11-11", "rates": {"INR": -5}},
    {"base": "USD", "date": "2026-11-11", "rates": {"INR": True}},
    {"base": "EUR", "date": "2026-11-11", "rates": {"INR": 93.69}},
    {"base": "USD", "rates": {"INR": 93.69}},
])
def test_fetch_usd_inr_rejects_unusable_replies(rate_api, payload):
    rate_api.payload = payload
    with pytest.raises(CurrencyError):
        fetch_usd_inr()
