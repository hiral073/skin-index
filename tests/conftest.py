import os
import sys

import pytest

# Make the project root importable when running pytest from any folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from app import app as flask_app  # noqa: E402
from database.db import init_db  # noqa: E402
from database.services import reset_rate_cooldown  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Tests never hit the network: the HTTP call fails like an outage unless a test patches it."""
    def offline(*args, **kwargs):
        raise requests.ConnectionError("network disabled in tests")

    monkeypatch.setattr("live.currency.requests.get", offline)
    reset_rate_cooldown()


class FakeResponse:
    def __init__(self, payload, status):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class RateApi:
    """Stand-in for requests.get: records calls, replies with `payload`/`status` or raises `error`."""

    def __init__(self):
        self.calls = []
        self.payload = {"amount": 1.0, "base": "USD", "date": "2026-11-11", "rates": {"INR": 93.69}}
        self.status = 200
        self.error = None

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return FakeResponse(self.payload, self.status)


@pytest.fixture
def rate_api(monkeypatch):
    api = RateApi()
    monkeypatch.setattr("live.currency.requests.get", api)
    return api


@pytest.fixture
def app(tmp_path):
    # Every test gets its own empty database, never the real skin_index.db
    db = str(tmp_path / "test.db")
    init_db(db)
    flask_app.config.update(TESTING=True, DATABASE=db)
    return flask_app
