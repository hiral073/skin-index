import os
import sys

import pytest

# Make the project root importable when running pytest from any folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from app import app as flask_app  # noqa: E402
from database.db import init_db  # noqa: E402
from database.services import reset_rate_cooldown  # noqa: E402
import live.pubmed  # noqa: E402
import live.weather  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Tests never hit the network: the HTTP call fails like an outage unless a test patches it."""
    def offline(*args, **kwargs):
        raise requests.ConnectionError("network disabled in tests")

    monkeypatch.setattr("live.currency.requests.get", offline)   # the same requests module the weather code uses
    reset_rate_cooldown()
    live.weather.clear_cache()


class FakeResponse:
    def __init__(self, payload, status, headers=None):
        self.payload, self.status, self.headers = payload, status, headers or {}
        self.status_code = status

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


class WeatherClock:
    """Stands in for time.monotonic in live.weather so a test can move time forward."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def weather_clock(monkeypatch):
    clock = WeatherClock()
    monkeypatch.setattr(live.weather, "_clock", clock)
    return clock


class WeatherApi:
    """Stand-in for requests.get that answers like the three Open-Meteo services.

    Each service replies with its payload (a dict) and status, or raises its error. Every call
    is recorded as (service, params, timeout) in `calls`.
    """

    def __init__(self):
        self.calls = []
        self.status = {"geocoding": 200, "forecast": 200, "air": 200}
        self.error = {"geocoding": None, "forecast": None, "air": None}
        self.payload = {
            "geocoding": self.geocoding([self.place("Pune", "Maharashtra", "India", 18.51957, 73.85535)]),
            "forecast": self.forecast(),
            "air": self.air(),
        }

    @staticmethod
    def place(name, region, country, latitude, longitude):
        item = {"id": 1, "name": name, "latitude": latitude, "longitude": longitude,
                "country_code": "XX", "timezone": "Asia/Kolkata", "country": country}
        if region is not None:
            item["admin1"] = region
        return item

    @staticmethod
    def geocoding(places):
        # no match: the "results" key is missing altogether, as the real service does
        return {"results": places, "generationtime_ms": 0.2} if places else {"generationtime_ms": 0.2}

    @staticmethod
    def forecast(uv_now=0.0, uv_max=6.85, humidity=37, temperature=26.7, time="2026-11-12T18:15", hourly=None):
        """`hourly` is None (no hourly data), a list of 24 values (index = hour of the day), or a
        dict {hour: value} (other hours 0). Each value is the average of the hour ending at that hour."""
        current = {"time": time, "interval": 900}
        for key, value in (("temperature_2m", temperature), ("relative_humidity_2m", humidity), ("uv_index", uv_now)):
            if value is not None:
                current[key] = value
        daily = {"time": [time[:10]]}
        if uv_max is not None:
            daily["uv_index_max"] = [uv_max]
        payload = {"latitude": 18.5, "longitude": 73.9, "timezone": "Asia/Kolkata", "current": current, "daily": daily}
        if hourly is not None:
            values = list(hourly) if not isinstance(hourly, dict) else [hourly.get(h, 0.0) for h in range(24)]
            payload["hourly"] = {"time": [f"{time[:10]}T{h:02d}:00" for h in range(len(values))], "uv_index": values}
        return payload

    @staticmethod
    def air(us_aqi=42, pm2_5=8.1, time="2026-11-12T17:30"):
        current = {"time": time, "interval": 3600}
        for key, value in (("us_aqi", us_aqi), ("pm2_5", pm2_5)):
            if value is not None:
                current[key] = value
        return {"latitude": 18.5, "longitude": 73.9, "timezone": "Asia/Kolkata", "current": current}

    def count(self, service):
        return sum(1 for kind, _params, _timeout in self.calls if kind == service)

    def __call__(self, url, params=None, timeout=None, **kwargs):
        service = ("geocoding" if "geocoding-api" in url else "air" if "air-quality-api" in url
                   else "forecast" if "api.open-meteo.com/v1/forecast" in url else None)
        if service is None:                       # any other service (e.g. exchange rates) stays offline
            raise requests.ConnectionError("network disabled in tests")
        self.calls.append((service, dict(params or {}), timeout))
        if self.error[service]:
            raise self.error[service]
        return FakeResponse(self.payload[service], self.status[service])


@pytest.fixture
def weather_api(monkeypatch, weather_clock):
    api = WeatherApi()
    monkeypatch.setattr("live.weather.requests.get", api)
    return api


class PubmedClock:
    """Stands in for time.monotonic and time.sleep in live.pubmed: sleeping just moves the clock, and
    every sleep is recorded, so no test really waits."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def pubmed_clock(monkeypatch):
    monkeypatch.delenv("NCBI_EMAIL", raising=False)         # a developer's own variable must never leak into a test
    clock = PubmedClock()
    monkeypatch.setattr(live.pubmed, "_clock", clock)
    monkeypatch.setattr(live.pubmed, "_sleep", clock.sleep)
    live.pubmed.reset_state()
    return clock


def pubmed_record(pmid, title, journal="Journal of Tests", year="2021 Mar", types=("Journal Article",), source=None):
    """One esummary record in PubMed's shape."""
    return {"uid": str(pmid), "title": title, "fulljournalname": journal, "source": source or journal,
            "pubdate": year, "epubdate": "", "pubtype": list(types)}


class PubmedApi:
    """Stand-in for requests.get that answers like PubMed's esearch and esummary.

    `records` is {pmid: esummary record}; esearch returns the pmids in order (limited by retmax),
    esummary returns the records asked for. Every call is recorded as (service, params, timeout).
    """

    def __init__(self, pubmed_clock):
        self.clock = pubmed_clock
        self.calls = []
        self.times = []                      # fake-clock time of every call
        self.records = {}
        self.search_ids = None               # None: all records in insertion order
        self.status = {"esearch": 200, "esummary": 200}
        self.error = {"esearch": None, "esummary": None}
        self.raw = {"esearch": None, "esummary": None}     # replace the whole reply body
        self.queue = {"esearch": [], "esummary": []}       # one-shot (status, headers) answers, used first
        # count queries (esearch with retmax=0): the first key contained in the query text gives the
        # count, else every count is the number of records; count_error does the same for failures
        self.counts = {}
        self.count_error = {}

    def add(self, pmid, title, **kwargs):
        self.records[str(pmid)] = pubmed_record(pmid, title, **kwargs)

    def count(self, service):
        return sum(1 for kind, _p, _t in self.calls if kind == service)

    def count_queries(self):
        """The query text of every count call (esearch with retmax=0), in order."""
        return [p["term"] for kind, p, _t in self.calls if kind == "esearch" and str(p.get("retmax")) == "0"]

    def __call__(self, url, params=None, timeout=None, **kwargs):
        service = "esearch" if "esearch" in url else "esummary" if "esummary" in url else None
        if service is None:                   # any other service (exchange rates, weather) stays offline
            raise requests.ConnectionError("network disabled in tests")
        params = dict(params or {})
        self.calls.append((service, params, timeout))
        self.times.append(self.clock.now)
        if self.queue[service]:
            status, headers = self.queue[service].pop(0)
            return FakeResponse({}, status, headers)
        if self.error[service]:
            raise self.error[service]
        if self.raw[service] is not None:
            return FakeResponse(self.raw[service], self.status[service])
        if service == "esearch" and str(params.get("retmax")) == "0":
            query = params.get("term", "")
            for key, error in self.count_error.items():
                if key in query:
                    raise error
            count = next((n for key, n in self.counts.items() if key in query), len(self.records))
            return FakeResponse({"header": {"type": "esearch"},
                                 "esearchresult": {"count": str(count), "idlist": []}}, self.status[service])
        if service == "esearch":
            ids = self.search_ids if self.search_ids is not None else list(self.records)
            ids = ids[: int(params.get("retmax", 20))]
            body = {"header": {"type": "esearch"}, "esearchresult": {"count": str(len(ids)), "idlist": ids}}
            if not ids:
                body["esearchresult"]["warninglist"] = {"outputmessages": ["No items found."]}
        else:
            ids = [i for i in params["id"].split(",") if i in self.records]
            body = {"header": {"type": "esummary"}, "result": {"uids": ids, **{i: self.records[i] for i in ids}}}
        return FakeResponse(body, self.status[service])


@pytest.fixture
def pubmed_api(monkeypatch, pubmed_clock):
    api = PubmedApi(pubmed_clock)
    monkeypatch.setattr("live.pubmed.requests.get", api)
    return api
