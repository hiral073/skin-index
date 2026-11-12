import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
import requests

import live.pubmed as pubmed
from database.db import get_db, init_db
from database.load_data import load_products
from database.services import RESEARCH_CONFIG, clean_search_text, search_research
from live.pubmed import PubmedError, search_pubmed

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def three(api):
    api.add(111, "Niacinamide: a review of dermal delivery.", year="2024 Dec", types=("Journal Article", "Review"))
    api.add(222, "Effect of niacinamide on pigmentation.", journal="The British journal of dermatology",
            year="2002 Jul", types=("Clinical Trial", "Journal Article", "Randomized Controlled Trial"))
    api.add(333, "Niacinamide in acne.", year="2014", types=("Journal Article",))


# ---------------------------------------------------------------- the PubMed module

def test_search_returns_papers_in_pubmeds_relevance_order_with_clean_fields(pubmed_api):
    three(pubmed_api)
    pubmed_api.search_ids = ["222", "333", "111"]                       # PubMed's order, not the records' order
    papers = search_pubmed("niacinamide")
    assert [p["pmid"] for p in papers] == ["222", "333", "111"]
    assert papers[0] == {
        "pmid": "222", "title": "Effect of niacinamide on pigmentation",       # trailing full stop removed
        "journal": "The British journal of dermatology", "year": 2002,
        "types": ["Randomized Controlled Trial", "Clinical Trial"],            # informative types, "Journal Article" dropped
        "url": "https://pubmed.ncbi.nlm.nih.gov/222/",
    }
    assert papers[1]["types"] == ["Journal Article"] and papers[1]["year"] == 2014
    assert papers[2]["types"] == ["Review"] and papers[2]["year"] == 2024


def test_the_requests_are_what_pubmed_expects(pubmed_api):
    three(pubmed_api)
    search_pubmed("niacinamide")
    (s1, p1, t1), (s2, p2, t2) = pubmed_api.calls
    assert (s1, t1, s2, t2) == ("esearch", 5, "esummary", 5)
    assert p1 == {"tool": "skin-index", "db": "pubmed", "term": "niacinamide AND skin", "retmax": 10,
                  "retmode": "json", "sort": "relevance"}
    assert p2 == {"tool": "skin-index", "db": "pubmed", "id": "111,222,333", "retmode": "json"}


def test_no_email_is_sent_when_ncbi_email_is_not_set(pubmed_api, monkeypatch):
    three(pubmed_api)
    monkeypatch.delenv("NCBI_EMAIL", raising=False)
    search_pubmed("a1")
    assert len(pubmed_api.calls) == 2
    assert all("email" not in params for _s, params, _t in pubmed_api.calls)
    assert all(params["tool"] == "skin-index" for _s, params, _t in pubmed_api.calls)      # the rest is unchanged


def test_the_email_from_ncbi_email_is_sent_on_both_requests(pubmed_api, monkeypatch):
    three(pubmed_api)
    monkeypatch.setenv("NCBI_EMAIL", "contact@example.org")
    search_pubmed("a1")
    assert [params["email"] for _s, params, _t in pubmed_api.calls] == ["contact@example.org"] * 2


def test_the_variable_is_read_at_search_time_so_changing_it_changes_the_next_search(pubmed_api, monkeypatch, pubmed_clock):
    three(pubmed_api)
    monkeypatch.setenv("NCBI_EMAIL", "first@example.org")
    search_pubmed("a1")
    pubmed_clock.advance(60)
    monkeypatch.delenv("NCBI_EMAIL")
    search_pubmed("a2")
    assert pubmed_api.calls[0][1]["email"] == "first@example.org" and "email" not in pubmed_api.calls[2][1]


@pytest.mark.parametrize("value", ["", "   ", "not an address", "a@b", "two@@example.org", "sp ace@example.org", "@example.org"])
def test_a_blank_or_malformed_ncbi_email_is_ignored(pubmed_api, monkeypatch, value):
    three(pubmed_api)
    monkeypatch.setenv("NCBI_EMAIL", value)
    assert pubmed.contact_email() is None
    search_pubmed("a1")
    assert all("email" not in params for _s, params, _t in pubmed_api.calls)


def test_surrounding_spaces_are_trimmed_from_the_email(monkeypatch):
    monkeypatch.setenv("NCBI_EMAIL", "  contact@example.org \t")
    assert pubmed.contact_email() == "contact@example.org"


def test_no_email_address_is_written_in_the_code_or_the_config():
    assert "email" not in pubmed.PUBMED_CONFIG
    source = open(pubmed.__file__, encoding="utf-8").read()
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", source)


def test_the_research_page_sends_the_email_when_the_variable_is_set(client, pubmed_api, monkeypatch):
    three(pubmed_api)
    monkeypatch.setenv("NCBI_EMAIL", "contact@example.org")
    assert client.get("/research?q=retinol").status_code == 200
    assert all(params["email"] == "contact@example.org" for _s, params, _t in pubmed_api.calls)
    monkeypatch.delenv("NCBI_EMAIL")
    assert client.get("/research?q=niacinamide").status_code == 200
    assert all("email" not in params for _s, params, _t in pubmed_api.calls[2:])


def test_only_the_ten_most_relevant_are_listed(pubmed_api):
    for i in range(1, 16):
        pubmed_api.add(1000 + i, f"Paper {i}")
    papers = search_pubmed("niacinamide")
    assert len(papers) == 10 and papers[0]["pmid"] == "1001"
    assert pubmed_api.calls[0][1]["retmax"] == 10


def test_reviews_only_adds_pubmeds_review_filter_and_keeps_real_reviews(pubmed_api):
    pubmed_api.add(1, "A review", types=("Journal Article", "Review"))
    pubmed_api.add(2, "A consensus study", types=("Journal Article", "Consensus Statement"))   # lets through PubMed's filter
    pubmed_api.add(3, "A systematic review", types=("Systematic Review", "Journal Article"))
    pubmed_api.add(4, "A trial", types=("Randomized Controlled Trial",))
    papers = search_pubmed("niacinamide", reviews_only=True)
    assert [p["pmid"] for p in papers] == ["1", "3"]
    params = pubmed_api.calls[0][1]
    assert params["term"] == "niacinamide AND skin AND (review[pt] OR systematic review[pt])"
    assert params["retmax"] == 20                                       # look at 20 so ten real reviews can be found


def test_reviews_only_still_lists_at_most_ten(pubmed_api):
    for i in range(1, 16):
        pubmed_api.add(i, f"Review {i}", types=("Review",))
    assert len(search_pubmed("niacinamide", reviews_only=True)) == 10


def test_a_search_with_no_match_is_an_empty_list_and_asks_for_no_details(pubmed_api):
    assert search_pubmed("zzzzqqqxx") == []
    assert pubmed_api.count("esearch") == 1 and pubmed_api.count("esummary") == 0


@pytest.mark.parametrize("record, year", [
    ({"pubdate": "2024 Dec"}, 2024), ({"pubdate": "2014"}, 2014), ({"pubdate": "2002 Jul 15"}, 2002),
    ({"pubdate": "", "epubdate": "2020 May 1"}, 2020), ({"pubdate": "Spring 1999"}, 1999),
    ({"pubdate": "2025 Jan", "epubdate": "2024 Dec 30"}, 2025),      # the issue date wins over the online date
    ({"pubdate": "", "epubdate": ""}, None), ({"pubdate": "n.d."}, None), ({}, None),
])
def test_year_comes_from_the_publication_date_text(pubmed_api, record, year):
    pubmed_api.records["1"] = {"uid": "1", "title": "T", "pubtype": [], **record}
    assert search_pubmed("x")[0]["year"] == year


@pytest.mark.parametrize("raw, shown", [
    (["Journal Article", "Review", "Research Support, Non-U.S. Gov't"], ["Review"]),
    (["Clinical Trial", "Journal Article", "Randomized Controlled Trial"], ["Randomized Controlled Trial", "Clinical Trial"]),
    (["Meta-Analysis", "Journal Article", "Systematic Review", "Review"], ["Systematic Review", "Meta-Analysis", "Review"]),
    (["Journal Article"], ["Journal Article"]),
    (["Journal Article", "Research Support, N.I.H., Extramural"], ["Journal Article"]),
    (["Research Support, Non-U.S. Gov't"], []),
    ([], []), (["Zebra Study", "Case Reports", "Alpha Study"], ["Case Reports", "Alpha Study", "Zebra Study"]),
])
def test_publication_types_are_ordered_and_the_generic_one_only_shows_alone(pubmed_api, raw, shown):
    pubmed_api.records["1"] = {"uid": "1", "title": "T", "pubtype": raw}
    assert search_pubmed("x")[0]["types"] == shown


def test_the_journal_falls_back_to_the_short_name_or_is_missing(pubmed_api):
    pubmed_api.records["1"] = {"uid": "1", "title": "A", "source": "Br J Dermatol", "pubtype": []}
    pubmed_api.records["2"] = {"uid": "2", "title": "B", "pubtype": []}
    first, second = search_pubmed("x")
    assert first["journal"] == "Br J Dermatol" and second["journal"] is None


def test_titles_are_cleaned_of_markup_and_spacing_and_unusable_records_are_skipped(pubmed_api):
    pubmed_api.records.update({
        "1": {"uid": "1", "title": "  Effects of <i>retinol</i>   on skin.  ", "pubtype": []},
        "2": {"uid": "2", "title": "", "pubtype": []},                   # no title
        "3": {"uid": "3", "pubtype": []},
        "4": {"uid": "4", "title": 42, "pubtype": []},
        "5": "not a record",
        "6": {"uid": "6", "title": "Fine", "pubtype": "not a list"},
        "9": {"uid": "9", "title": "pH < 5 and > 3: H<sub>2</sub>O effects", "pubtype": []},   # not markup: kept as written
        "10": {"uid": "10", "title": "<script>alert(1)</script> retinol", "pubtype": []},      # left for the page to escape
    })
    pubmed_api.search_ids = ["1", "2", "3", "4", "5", "6", "x7", "8", "9", "10"]    # 8 has no record; x7 is not an id
    papers = search_pubmed("x")
    assert [(p["pmid"], p["title"], p["types"]) for p in papers] == [
        ("1", "Effects of retinol on skin", []), ("6", "Fine", []),
        ("9", "pH < 5 and > 3: H2O effects", []), ("10", "<script>alert(1)</script> retinol", [])]


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_network_errors_become_pubmed_errors(pubmed_api, error):
    pubmed_api.error["esearch"] = error
    with pytest.raises(PubmedError, match="Could not reach PubMed"):
        search_pubmed("x")


def test_a_failing_details_call_is_an_error_too(pubmed_api):
    three(pubmed_api)
    pubmed_api.error["esummary"] = requests.Timeout("slow")
    with pytest.raises(PubmedError):
        search_pubmed("x")


@pytest.mark.parametrize("service, setup", [
    ("esearch", {"status": 500}), ("esearch", {"raw": ["a", "list"]}), ("esearch", {"raw": {"nothing": 1}}),
    ("esearch", {"raw": {"esearchresult": {"count": "1"}}}),             # no idlist at all
    ("esearch", {"raw": {"esearchresult": {"idlist": "12345"}}}),
    ("esummary", {"status": 503}), ("esummary", {"raw": {"header": {}}}), ("esummary", {"raw": ["x"]}),
])
def test_unusable_replies_are_pubmed_errors(pubmed_api, service, setup):
    three(pubmed_api)
    if "status" in setup:
        pubmed_api.status[service] = setup["status"]
    if "raw" in setup:
        pubmed_api.raw[service] = setup["raw"]
    with pytest.raises(PubmedError):
        search_pubmed("x")


# ---------------------------------------------------------------- staying under 3 requests per second

def test_requests_are_spaced_at_least_0_4_seconds_apart(pubmed_api, pubmed_clock):
    three(pubmed_api)
    for term in ("a1", "a2", "a3"):
        search_pubmed(term)                                              # 6 requests back to back
    gaps = [b - a for a, b in zip(pubmed_api.times, pubmed_api.times[1:])]
    assert len(gaps) == 5 and all(gap >= 0.4 - 1e-9 for gap in gaps)
    assert max(sum(1 for t in pubmed_api.times if start <= t < start + 1.0) for start in pubmed_api.times) <= 3


def test_no_waiting_when_enough_time_has_passed(pubmed_api, pubmed_clock):
    three(pubmed_api)
    search_pubmed("a1")
    pubmed_clock.advance(5)
    pubmed_clock.sleeps.clear()
    search_pubmed("a2")
    assert pubmed_clock.sleeps == [pytest.approx(0.4)]                  # only the gap between its own two calls


def test_a_429_is_retried_once_after_the_retry_after_delay(pubmed_api, pubmed_clock):
    three(pubmed_api)
    pubmed_api.queue["esearch"].append((429, {"Retry-After": "1"}))
    assert len(search_pubmed("x")) == 3
    assert pubmed_api.count("esearch") == 2 and 1 in pubmed_clock.sleeps


def test_a_long_retry_after_is_capped_and_a_bad_one_defaults_to_one_second(pubmed_api, pubmed_clock):
    three(pubmed_api)
    pubmed_api.queue["esearch"].append((429, {"Retry-After": "300"}))
    search_pubmed("x")
    assert 2 in pubmed_clock.sleeps and 300 not in pubmed_clock.sleeps
    pubmed_clock.sleeps.clear()
    pubmed_clock.advance(60)
    pubmed_api.queue["esearch"].append((429, {"Retry-After": "soon"}))
    search_pubmed("y")
    assert 1.0 in pubmed_clock.sleeps


def test_two_429s_in_a_row_are_an_error(pubmed_api):
    three(pubmed_api)
    pubmed_api.queue["esearch"] += [(429, {"Retry-After": "1"}), (429, {"Retry-After": "1"})]
    with pytest.raises(PubmedError):
        search_pubmed("x")
    assert pubmed_api.count("esearch") == 2                              # one retry, no more


def test_after_a_failure_pubmed_is_left_alone_for_ten_seconds(pubmed_api, pubmed_clock):
    three(pubmed_api)
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    for _ in range(3):
        with pytest.raises(PubmedError):
            search_pubmed("x")
    assert pubmed_api.count("esearch") == 1
    pubmed_clock.advance(11)
    pubmed_api.error["esearch"] = None
    assert len(search_pubmed("x")) == 3


# ---------------------------------------------------------------- search text

@pytest.mark.parametrize("raw, cleaned", [
    ("Niacinamide", "niacinamide"), ("  Vitamin   C ", "vitamin c"), ("L-Ascorbic Acid", "l-ascorbic acid"),
    ("alpha-hydroxy acid", "alpha-hydroxy acid"), ("niacinamide AND skin", "niacinamide and skin"),
    ("Coenzyme Q10", "coenzyme q10"), ("retinol, retinal", "retinol, retinal"),
])
def test_search_text_is_cleaned_and_lowercased(raw, cleaned):
    assert clean_search_text(raw) == cleaned


@pytest.mark.parametrize("raw", [
    "", " ", "a", "x" * 61, None, 5, '"niacinamide"', "niacinamide[ti]", "a:b", "(a)", "a*", "http://x.example",
    "www.evil.example", "a/b", "<script>", "a%20b", "a;b", "a&b", "a=b", "?",
])
def test_search_text_with_odd_characters_is_refused(raw):
    assert clean_search_text(raw) is None


# ---------------------------------------------------------------- research: saved searches (24 hours)

def rows(db_path):
    with closing(get_db(db_path)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM pubmed_searches ORDER BY term, reviews_only")]


def test_a_search_returns_plain_data_and_saves_the_parsed_papers(pubmed_api, db_path):
    three(pubmed_api)
    got = search_research("  Niacinamide ", db_path=db_path, now=NOW)
    assert got["status"] == "ok" and got["source"] == "live" and got["fetched_at"] == "2026-11-12T10:00:00+00:00"
    assert got["term"] == "niacinamide" and got["query"] == "niacinamide AND skin" and got["reviews_only"] is False
    assert [p["pmid"] for p in got["papers"]] == ["111", "222", "333"]
    assert set(got) == {"status", "term", "query", "reviews_only", "papers", "source", "fetched_at"}
    saved = rows(db_path)
    assert len(saved) == 1 and (saved[0]["term"], saved[0]["reviews_only"]) == ("niacinamide", 0)
    assert json.loads(saved[0]["papers_json"]) == got["papers"]
    assert set(json.loads(saved[0]["papers_json"])[0]) == {"pmid", "title", "journal", "year", "types", "url"}   # no raw PubMed data


def test_a_repeat_within_24_hours_uses_the_saved_copy_with_no_call(pubmed_api, db_path):
    three(pubmed_api)
    first = search_research("niacinamide", db_path=db_path, now=NOW)
    calls = len(pubmed_api.calls)
    again = search_research("Niacinamide", db_path=db_path, now=NOW + timedelta(hours=23, minutes=59))
    assert len(pubmed_api.calls) == calls
    assert again["source"] == "cache" and again["papers"] == first["papers"] and again["status"] == "ok"
    assert again["fetched_at"] == first["fetched_at"]


def test_after_24_hours_it_asks_pubmed_again_and_refreshes_the_copy(pubmed_api, db_path):
    three(pubmed_api)
    search_research("niacinamide", db_path=db_path, now=NOW)
    later = NOW + timedelta(hours=24)
    pubmed_api.records.pop("333")
    got = search_research("niacinamide", db_path=db_path, now=later)
    assert got["source"] == "live" and [p["pmid"] for p in got["papers"]] == ["111", "222"]
    assert rows(db_path)[0]["fetched_at"] == later.isoformat(timespec="seconds") and len(rows(db_path)) == 1


def test_reviews_only_and_other_terms_are_saved_separately(pubmed_api, db_path):
    three(pubmed_api)
    search_research("niacinamide", db_path=db_path, now=NOW)
    search_research("niacinamide", reviews_only=True, db_path=db_path, now=NOW)
    search_research("retinol", db_path=db_path, now=NOW)
    assert [(r["term"], r["reviews_only"]) for r in rows(db_path)] == [("niacinamide", 0), ("niacinamide", 1), ("retinol", 0)]
    calls = len(pubmed_api.calls)
    search_research("niacinamide", reviews_only=True, db_path=db_path, now=NOW)
    assert len(pubmed_api.calls) == calls


def test_no_papers_is_an_empty_status_and_is_saved_too(pubmed_api, db_path):
    got = search_research("zzzzqqqxx", db_path=db_path, now=NOW)
    assert got["status"] == "empty" and got["papers"] == [] and got["source"] == "live"
    calls = len(pubmed_api.calls)
    again = search_research("zzzzqqqxx", db_path=db_path, now=NOW + timedelta(hours=1))
    assert again["status"] == "empty" and again["source"] == "cache" and len(pubmed_api.calls) == calls


@pytest.mark.parametrize("raw", ["", "  ", "a", '"x"', "a[b]", "http://x.example", "x" * 61, None])
def test_unusable_search_text_is_invalid_and_calls_and_saves_nothing(pubmed_api, db_path, raw):
    got = search_research(raw, db_path=db_path, now=NOW)
    assert got["status"] == "invalid" and got["papers"] == [] and got["term"] is None and got["query"] is None
    assert pubmed_api.calls == [] and rows(db_path) == []


def test_pubmed_down_with_a_saved_copy_shows_the_saved_copy(pubmed_api, db_path):
    three(pubmed_api)
    first = search_research("niacinamide", db_path=db_path, now=NOW)
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    got = search_research("niacinamide", db_path=db_path, now=NOW + timedelta(days=3))
    assert got["status"] == "ok" and got["source"] == "stale_cache" and got["papers"] == first["papers"]
    assert got["fetched_at"] == first["fetched_at"]
    assert rows(db_path)[0]["fetched_at"] == first["fetched_at"]          # the failed refresh did not overwrite it


def test_pubmed_down_with_no_saved_copy_is_unavailable_and_saves_nothing(pubmed_api, db_path):
    pubmed_api.error["esearch"] = requests.ConnectionError("down")
    got = search_research("niacinamide", db_path=db_path, now=NOW)
    assert got["status"] == "unavailable" and got["papers"] == [] and got["source"] is None and got["fetched_at"] is None
    assert rows(db_path) == []


def test_a_saved_copy_made_fresh_is_not_replaced_by_an_outage_later(pubmed_api, db_path):
    three(pubmed_api)
    search_research("niacinamide", db_path=db_path, now=NOW)
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    pubmed_api.calls.clear()
    got = search_research("niacinamide", db_path=db_path, now=NOW + timedelta(hours=1))
    assert got["source"] == "cache" and pubmed_api.calls == []           # still fresh: PubMed is not even tried


def test_recovery_after_an_outage_refreshes_the_copy(pubmed_api, db_path, pubmed_clock):
    three(pubmed_api)
    search_research("niacinamide", db_path=db_path, now=NOW)
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    assert search_research("niacinamide", db_path=db_path, now=NOW + timedelta(days=2))["source"] == "stale_cache"
    pubmed_api.error["esearch"] = None
    pubmed_clock.advance(11)
    got = search_research("niacinamide", db_path=db_path, now=NOW + timedelta(days=2, minutes=1))
    assert got["source"] == "live" and got["fetched_at"].startswith("2026-11-14")


@pytest.mark.parametrize("fetched_at, papers_json", [
    ("not a date", "[]"), ("2026-11-12T09:00:00", "[]"),                 # no time zone
    ("2026-11-12T09:00:00+00:00", "not json"), ("2026-11-12T09:00:00+00:00", '{"a": 1}'),
])
def test_an_unreadable_saved_copy_is_ignored_and_replaced(pubmed_api, db_path, fetched_at, papers_json):
    three(pubmed_api)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("INSERT INTO pubmed_searches VALUES ('niacinamide', 0, ?, ?)", (fetched_at, papers_json))
    got = search_research("niacinamide", db_path=db_path, now=NOW)
    assert got["source"] == "live" and len(got["papers"]) == 3


def test_old_saved_searches_are_deleted_after_30_days(pubmed_api, db_path):
    three(pubmed_api)
    search_research("old term", db_path=db_path, now=NOW - timedelta(days=31))
    search_research("recent term", db_path=db_path, now=NOW - timedelta(days=5))
    assert {r["term"] for r in rows(db_path)} == {"old term", "recent term"}
    search_research("new term", db_path=db_path, now=NOW)               # saving prunes
    assert {r["term"] for r in rows(db_path)} == {"recent term", "new term"}


def test_the_default_limits_are_24_hours_30_days_and_1000_saved_searches():
    assert RESEARCH_CONFIG["cache_hours"] == 24 and RESEARCH_CONFIG["prune_days"] == 30
    assert RESEARCH_CONFIG["max_rows"] == 1000 and RESEARCH_CONFIG["max_term_length"] == 60


def test_pubmed_settings_match_ncbis_guidance():
    config = pubmed.PUBMED_CONFIG
    assert config["tool"] == "skin-index" and "email" not in config
    assert config["timeout_seconds"] == 5 and config["min_gap_seconds"] >= 1 / 3     # under 3 requests per second
    assert config["show"] == 10 and config["fetch_for_reviews"] == 20
    assert config["skin_filter"] == "skin" and config["review_filter"] == "(review[pt] OR systematic review[pt])"


def test_the_table_is_capped_oldest_first(pubmed_api, db_path, monkeypatch):
    three(pubmed_api)
    monkeypatch.setitem(RESEARCH_CONFIG, "max_rows", 3)
    for i in range(5):
        search_research(f"term {i}", db_path=db_path, now=NOW + timedelta(minutes=i))
    assert [r["term"] for r in rows(db_path)] == ["term 2", "term 3", "term 4"]


def test_an_older_database_gets_the_table(pubmed_api, tmp_path):
    three(pubmed_api)
    path = str(tmp_path / "old.db")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL)")
    assert search_research("niacinamide", db_path=path, now=NOW)["status"] == "ok"


def test_reloading_the_products_leaves_saved_searches_alone(pubmed_api, db_path):
    three(pubmed_api)
    search_research("niacinamide", db_path=db_path, now=NOW)
    load_products([], db_path)
    assert len(rows(db_path)) == 1


def test_the_saved_table_holds_only_search_text_and_results(db_path):
    with closing(get_db(db_path)) as conn:
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(pubmed_searches)")]
    assert columns == ["term", "reviews_only", "fetched_at", "papers_json"]
