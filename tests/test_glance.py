import html as html_lib
import pathlib
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
import requests
from conftest import FakeResponse

import live.pubmed
from content import science as science_content
from database.db import get_db, init_db
from database.services import RESEARCH_CONFIG, get_ingredient_glance, search_research
from live.pubmed import PubmedError, count_pubmed

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)

# Our own wording in the box must never use these (the topic words are the counted topics, not claims)
BANNED = ["safe", "best for", "treats", "cures", "proven", "effective", "helps with", "used for"]

NOTE_LINE = ("These numbers show how often topics appear in published papers. They do not show that an ingredient "
             "works or is suitable for anyone. Source: PubMed (US National Library of Medicine).")

TOPICS = ["acne", "hyperpigmentation", "skin aging", "skin barrier", "irritation", "rosacea", "eczema"]
TOPIC_QUERIES = [f'niacinamide AND "{t}"' for t in TOPICS]
BAKUCHIOL_QUERIES = [f'bakuchiol AND "{t}"' for t in TOPICS]   # the page tests use an ingredient with no card

# The three lines that used to open the box: they must be gone
REMOVED_TEXTS = ["Papers found", "Overview papers", "Years of the papers listed below", "Year of the paper listed below"]


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def papers(api, years=("2024 Dec", "2002 Jul", "2014")):
    for i, year in enumerate(years, start=1):
        api.add(100 + i, f"Paper {i}", year=year)


def set_counts(api, **topics):
    """Count answers by topic (underscores stand for spaces); a topic not named has no papers."""
    given = {name.replace("_", " "): n for name, n in topics.items()}
    api.counts = {f'"{topic}"': given.pop(topic, 0) for topic in TOPICS}
    assert not given, given


def glance(db_path, now=NOW):
    return get_ingredient_glance("niacinamide", db_path, now)


# ---------------------------------------------------------------- the service: counts

def test_the_glance_returns_the_topic_counts_as_plain_data(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980)
    assert glance(db_path) == {
        "status": "ok", "term": "niacinamide",
        "topics": [{"topic": "skin aging", "count": 980}, {"topic": "acne", "count": 412}],
        "incomplete": False, "fetched_at": NOW.isoformat(timespec="seconds"),
    }


def test_nothing_but_topic_counts_is_returned_or_asked_for(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=1)
    got = glance(db_path)
    for gone in ("total", "overviews", "year_from", "year_to"):
        assert gone not in got
    assert pubmed_api.count_queries() == TOPIC_QUERIES                # no total count, no overview count


def test_topics_are_sorted_by_count_then_by_the_order_of_the_content_file_and_zero_counts_are_left_out(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, eczema=50, acne=50, rosacea=7, irritation=0, skin_barrier=300)
    topics = glance(db_path)["topics"]
    assert topics == [{"topic": "skin barrier", "count": 300}, {"topic": "acne", "count": 50},
                      {"topic": "eczema", "count": 50}, {"topic": "rosacea", "count": 7}]
    for left_out in ("irritation", "hyperpigmentation", "skin aging"):
        assert left_out not in [t["topic"] for t in topics]


def test_equal_counts_keep_the_order_of_the_content_file_not_alphabetical_order(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, skin_barrier=40, irritation=40, hyperpigmentation=40)
    assert [t["topic"] for t in glance(db_path)["topics"]] == ["hyperpigmentation", "skin barrier", "irritation"]


def test_the_topics_and_their_queries_are_exactly_the_ones_specified(pubmed_api, db_path):
    papers(pubmed_api)
    glance(db_path)
    assert pubmed_api.count_queries() == TOPIC_QUERIES
    assert science_content.GLANCE_TOPICS == TOPICS


def test_the_search_text_is_cleaned_like_a_search(pubmed_api, db_path):
    papers(pubmed_api)
    got = get_ingredient_glance("  Niacinamide ", db_path, NOW)
    assert got["term"] == "niacinamide" and pubmed_api.count_queries() == TOPIC_QUERIES


def test_unusable_text_is_invalid_with_no_call(pubmed_api, db_path):
    got = get_ingredient_glance('"x"', db_path, NOW)
    assert got["status"] == "invalid" and got["topics"] == [] and pubmed_api.calls == []


# ---------------------------------------------------------------- no papers, no topic counts, failures

def test_no_papers_means_no_box_and_no_count_calls(pubmed_api, db_path):
    got = glance(db_path)                                                 # no records at all
    assert got["status"] == "none" and got["topics"] == []
    assert pubmed_api.count_queries() == [] and pubmed_api.count("esearch") == 1


def test_when_no_topic_has_a_paper_there_is_nothing_to_show(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api)
    got = glance(db_path)
    assert got["status"] == "none" and got["topics"] == [] and got["incomplete"] is False
    assert len(pubmed_api.count_queries()) == len(TOPICS)


def test_a_failed_topic_is_left_out_and_the_rest_are_shown(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980, rosacea=5)
    pubmed_api.count_error['"skin aging"'] = requests.Timeout("slow")
    got = glance(db_path)
    assert got["status"] == "ok" and got["incomplete"] is True
    assert got["topics"] == [{"topic": "acne", "count": 412}, {"topic": "rosacea", "count": 5}]
    assert len(pubmed_api.count_queries()) == len(TOPICS)                 # every topic was still tried


def test_an_unreadable_count_reply_is_a_failed_topic_not_a_crash(pubmed_api, db_path, monkeypatch):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, rosacea=3)
    original = type(pubmed_api).__call__

    def unreadable_for_rosacea(self, url, params=None, **kwargs):
        if params and "rosacea" in params.get("term", ""):
            return FakeResponse({"esearchresult": {"count": "many"}}, 200)
        return original(self, url, params, **kwargs)

    monkeypatch.setattr(type(pubmed_api), "__call__", unreadable_for_rosacea)
    got = glance(db_path)
    assert got["status"] == "ok" and [t["topic"] for t in got["topics"]] == ["acne"] and got["incomplete"] is True


def test_two_failures_in_a_row_stop_the_rest(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, skin_barrier=300)
    pubmed_api.count_error['"acne"'] = requests.Timeout("slow")
    pubmed_api.count_error['"hyperpigmentation"'] = requests.Timeout("slow")
    got = glance(db_path)
    assert pubmed_api.count_queries() == TOPIC_QUERIES[:2]
    assert got["status"] == "unavailable" and got["topics"] == [] and got["incomplete"] is True
    assert RESEARCH_CONFIG["max_count_failures"] == 2


def test_failures_that_are_not_in_a_row_do_not_stop_it(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, hyperpigmentation=9, skin_barrier=300, eczema=2)
    for topic in ("acne", "skin aging", "irritation"):
        pubmed_api.count_error[f'"{topic}"'] = requests.Timeout("slow")
    got = glance(db_path)
    assert len(pubmed_api.count_queries()) == len(TOPICS)
    assert [t["topic"] for t in got["topics"]] == ["skin barrier", "hyperpigmentation", "eczema"]


def test_when_every_count_fails_the_status_is_unavailable(pubmed_api, db_path):
    papers(pubmed_api)
    for topic in TOPICS:
        pubmed_api.count_error[f'"{topic}"'] = requests.Timeout("slow")
    got = glance(db_path)
    assert got["status"] == "unavailable" and got["topics"] == [] and got["incomplete"] is True


def test_a_failed_count_does_not_leave_pubmed_blocked_for_other_searches(pubmed_api, db_path):
    papers(pubmed_api)
    pubmed_api.count_error['"acne"'] = requests.Timeout("slow")
    glance(db_path)
    before = pubmed_api.count("esearch")
    assert search_research("retinol", db_path=db_path, now=NOW)["status"] == "ok"
    assert pubmed_api.count("esearch") == before + 1                      # went out at once, not refused for 10 s


def test_pubmed_down_for_the_papers_means_unavailable_with_no_count_calls(pubmed_api, db_path):
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    got = glance(db_path)
    assert got["status"] == "unavailable" and pubmed_api.count_queries() == [] and pubmed_api.count("esearch") == 1


def test_an_old_saved_copy_of_the_papers_means_no_counts_are_tried(pubmed_api, db_path):
    papers(pubmed_api)
    glance(db_path)
    with closing(get_db(db_path)) as conn, conn:
        conn.execute("DELETE FROM pubmed_counts")
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    before = len(pubmed_api.calls)
    got = get_ingredient_glance("niacinamide", db_path, NOW + timedelta(hours=30))
    assert got["status"] == "unavailable" and got["topics"] == []
    assert len(pubmed_api.calls) == before + 1                            # the failed paper search only


# ---------------------------------------------------------------- the 24 hour cache

def test_a_repeat_within_24_hours_makes_no_new_calls(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    first = glance(db_path)
    calls = len(pubmed_api.calls)
    again = glance(db_path, NOW + timedelta(hours=23, minutes=59))
    assert len(pubmed_api.calls) == calls and again == first


def test_after_24_hours_the_counts_are_fetched_again(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    glance(db_path)
    set_counts(pubmed_api, acne=500)
    later = NOW + timedelta(hours=25)
    got = glance(db_path, later)
    assert got["topics"] == [{"topic": "acne", "count": 500}] and got["fetched_at"] == later.isoformat(timespec="seconds")


def test_only_the_failed_count_is_asked_again_on_the_next_view(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980)
    pubmed_api.count_error['"skin aging"'] = requests.Timeout("slow")
    glance(db_path)
    pubmed_api.count_error.clear()
    pubmed_api.calls.clear()
    got = glance(db_path, NOW + timedelta(minutes=5))
    assert pubmed_api.count_queries() == ['niacinamide AND "skin aging"']
    assert [t["topic"] for t in got["topics"]] == ["skin aging", "acne"] and got["incomplete"] is False


def test_zero_counts_are_saved_too_so_they_are_not_asked_again(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=0)
    glance(db_path)
    calls = len(pubmed_api.calls)
    glance(db_path, NOW + timedelta(hours=1))
    assert len(pubmed_api.calls) == calls


def test_a_different_ingredient_has_its_own_counts(pubmed_api, db_path):
    papers(pubmed_api)
    glance(db_path)
    pubmed_api.calls.clear()
    get_ingredient_glance("retinol", db_path, NOW)
    assert pubmed_api.count_queries()[0] == 'retinol AND "acne"'


def rows(db_path):
    with closing(get_db(db_path)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM pubmed_counts ORDER BY query")]


def test_the_saved_counts_hold_only_the_query_the_count_and_the_time(pubmed_api, db_path):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    glance(db_path)
    saved = rows(db_path)
    assert len(saved) == len(TOPICS) and set(saved[0]) == {"query", "paper_count", "fetched_at"}
    assert {r["query"]: r["paper_count"] for r in saved}['niacinamide AND "acne"'] == 412
    assert all(r["fetched_at"] == NOW.isoformat(timespec="seconds") for r in saved)


def test_old_saved_counts_are_deleted_after_30_days(pubmed_api, db_path):
    papers(pubmed_api)
    glance(db_path)
    get_ingredient_glance("retinol", db_path, NOW + timedelta(days=31))
    assert all(r["query"].startswith("retinol") for r in rows(db_path))


def test_the_saved_counts_are_capped_oldest_first(pubmed_api, db_path, monkeypatch):
    papers(pubmed_api)
    monkeypatch.setitem(RESEARCH_CONFIG, "max_count_rows", 3)
    glance(db_path)
    assert len(rows(db_path)) == 3


def test_the_default_cap_is_5000_rows():
    assert RESEARCH_CONFIG["max_count_rows"] == 5000 and RESEARCH_CONFIG["cache_hours"] == 24


def test_the_rate_limit_holds_across_all_the_calls(pubmed_api, db_path):
    papers(pubmed_api)
    glance(db_path)
    gaps = [b - a for a, b in zip(pubmed_api.times, pubmed_api.times[1:])]
    assert len(pubmed_api.times) == 2 + len(TOPICS) and all(g >= 0.4 - 1e-9 for g in gaps)


# ---------------------------------------------------------------- count_pubmed

def test_count_pubmed_asks_for_the_count_only_and_returns_a_number(pubmed_api):
    pubmed_api.counts = {"acne": 42}
    assert count_pubmed("niacinamide AND acne") == 42
    (service, params, timeout), = pubmed_api.calls
    assert service == "esearch" and params["retmax"] == 0 and params["term"] == "niacinamide AND acne"
    assert params["tool"] == "skin-index" and params["db"] == "pubmed" and timeout == 5


@pytest.mark.parametrize("count, expected", [("0", 0), ("12345", 12345), (7, 7)])
def test_count_pubmed_reads_text_or_numbers(pubmed_api, count, expected):
    pubmed_api.raw["esearch"] = {"esearchresult": {"count": count, "idlist": []}}
    assert count_pubmed("x") == expected


@pytest.mark.parametrize("body", [{}, {"esearchresult": {}}, {"esearchresult": {"count": "many"}},
                                   {"esearchresult": {"count": "-1"}}, {"esearchresult": {"count": True}},
                                   {"esearchresult": {"count": None}}, {"esearchresult": []}, []])
def test_count_pubmed_refuses_unreadable_replies(pubmed_api, body):
    pubmed_api.raw["esearch"] = body
    with pytest.raises(PubmedError):
        count_pubmed("x")


def test_count_pubmed_errors_do_not_start_the_ten_second_wait(pubmed_api):
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    with pytest.raises(PubmedError):
        count_pubmed("x")
    pubmed_api.error["esearch"] = None
    assert live.pubmed._failure is None and count_pubmed("x") == 0


def test_count_pubmed_sends_the_email_only_when_set(pubmed_api, monkeypatch):
    count_pubmed("x")
    monkeypatch.setenv("NCBI_EMAIL", "contact@example.org")
    count_pubmed("x")
    assert "email" not in pubmed_api.calls[0][1] and pubmed_api.calls[1][1]["email"] == "contact@example.org"


def test_a_429_on_a_count_is_retried_once(pubmed_api):
    pubmed_api.queue["esearch"].append((429, {"Retry-After": "1"}))
    assert count_pubmed("x") == 0 and pubmed_api.count("esearch") == 2


def test_the_code_that_only_produced_the_removed_numbers_is_gone():
    assert not hasattr(live.pubmed, "total_query") and not hasattr(live.pubmed, "overview_query")
    assert "overview_filter" not in live.pubmed.PUBMED_CONFIG
    for name in ("GLANCE_TOTAL_LABEL", "GLANCE_OVERVIEW_LABEL", "GLANCE_YEARS_LABEL", "GLANCE_YEAR_LABEL"):
        assert not hasattr(science_content, name), name


# ---------------------------------------------------------------- the page

def page(client, url="/science?q=bakuchiol"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def box(html):
    found = re.search(r'<section class="glance" id="glance" data-kind="counts">(.*?)</section>', html, re.S)
    return found.group(1) if found else None


def test_the_box_shows_only_the_topic_counts_above_the_papers(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980, eczema=1)
    html = page(client)
    assert text(box(html)) == ("At a glance Often mentioned together with skin aging 980 papers acne 412 papers "
                               "eczema 1 paper " + NOTE_LINE)
    assert html.index('id="labels-line"') < html.index('id="glance"') < html.index("paper-group-title")


def test_the_three_removed_lines_are_not_on_the_page(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    html = page(client)
    for removed in REMOVED_TEXTS:                                         # ("Overview papers" is still the checkbox and a group name)
        assert removed not in box(html) and f"{removed}:" not in text(html), removed
    assert "Years of the paper" not in html and "<strong>" not in box(html)
    assert "glance-facts" not in html and "glance-facts" not in pathlib.Path("static/css/style.css").read_text(encoding="utf-8")
    assert pubmed_api.count_queries() == BAKUCHIOL_QUERIES                    # and nothing is counted for them


def test_the_line_under_the_box_is_exactly_as_specified_and_appears_once(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    html = page(client)
    assert science_content.GLANCE_NOTE == NOTE_LINE and text(html).count(NOTE_LINE) == 1
    assert text(box(html)).endswith(NOTE_LINE)


def test_the_whole_box_is_hidden_when_no_topic_has_a_paper(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api)
    html = page(client)
    assert box(html) is None and "At a glance" not in html and NOTE_LINE not in text(html)
    assert "Often mentioned together with" not in html and "paper-card" in html      # the papers still show


def test_the_whole_box_is_hidden_when_every_topic_count_fails(client, pubmed_api):
    papers(pubmed_api)
    for topic in TOPICS:
        pubmed_api.count_error[f'"{topic}"'] = requests.Timeout("slow")
    html = page(client)
    assert box(html) is None and NOTE_LINE not in text(html) and "paper-card" in html


def test_the_box_is_hidden_when_there_are_no_papers(client, pubmed_api):
    html = page(client, "/science?q=zzzzqqqxx")
    assert box(html) is None and "At a glance" not in html and pubmed_api.count_queries() == []


def test_the_box_is_hidden_for_a_blank_or_unusable_search(client, pubmed_api):
    assert box(page(client, "/science")) is None and box(page(client, "/science?q=%5Bx%5D")) is None
    assert pubmed_api.calls == []


def test_a_failed_topic_is_skipped_on_the_page_and_the_rest_show(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980)
    pubmed_api.count_error['"skin aging"'] = requests.Timeout("slow")
    body = text(box(page(client)))
    assert "acne 412 papers" in body and "skin aging" not in body and NOTE_LINE in body


def test_the_second_view_makes_no_new_calls(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    first = page(client)
    calls = len(pubmed_api.calls)
    second = page(client)
    assert len(pubmed_api.calls) == calls and text(box(second)) == text(box(first))


def test_the_counts_do_not_depend_on_the_reviews_only_box(client, pubmed_api):
    pubmed_api.add(1, "A review", types=("Review",))
    set_counts(pubmed_api, acne=7)
    first = text(box(page(client)))
    count_calls = len(pubmed_api.count_queries())
    reviews = page(client, "/science?q=bakuchiol&reviews=1")
    assert len(pubmed_api.count_queries()) == count_calls                 # the counts came from the saved copy
    assert text(box(reviews)) == first and "acne 7 papers" in first


def test_no_box_when_pubmed_is_down_and_only_an_old_copy_is_shown(client, pubmed_api, app):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    page(client)
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        conn.execute("UPDATE pubmed_searches SET fetched_at = '2026-01-05T09:30:00+00:00'")
        conn.execute("DELETE FROM pubmed_counts")
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client)
    assert "saved results from 5 Jan 2026" in text(html) and box(html) is None and "paper-card" in html


# ---------------------------------------------------------------- wording

def our_texts():
    c = science_content
    return [c.GLANCE_TITLE, c.GLANCE_TOPICS_HEADING, c.GLANCE_NOTE, c.LABELS_LINE, c.REVIEWS_ONLY_LABEL,
            c.REVIEWS_ONLY_NOTE, c.OTHER_LABEL] + [label for label, _types in c.PAPER_LABELS]


def test_our_own_glance_text_uses_none_of_the_banned_words():
    for text_ in our_texts():
        for word in BANNED:
            assert word not in text_.lower(), (word, text_)


def test_the_heading_says_mentioned_together_with_not_helps_with_or_used_for():
    assert science_content.GLANCE_TOPICS_HEADING == "Often mentioned together with"
    page_template = pathlib.Path("templates/science.html").read_text(encoding="utf-8").lower()
    for phrase in ("helps with", "used for", "good for", "treats"):
        assert phrase not in page_template


def test_the_banned_word_check_would_catch_a_claim(monkeypatch):
    monkeypatch.setattr(science_content, "GLANCE_NOTE", NOTE_LINE + " It is proven.")
    assert any(word in science_content.GLANCE_NOTE.lower() for word in BANNED)


def test_the_box_makes_no_claim_beyond_counts(client, pubmed_api):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412)
    body = text(box(page(client))).lower()
    for phrase in ("helps", "improves", "reduces", "good for", "recommended", "benefit", "evidence", "cause", "cure"):
        assert phrase not in body, phrase
    assert body.count("works") == 1                                      # only the required line


@pytest.mark.parametrize("scenario", ["results", "reviews", "failed_topic", "no_topics"])
def test_the_whole_page_with_the_box_uses_none_of_the_banned_words(client, pubmed_api, scenario):
    papers(pubmed_api)
    set_counts(pubmed_api, acne=412, skin_aging=980)
    if scenario == "failed_topic":
        pubmed_api.count_error['"acne"'] = requests.Timeout("slow")
    if scenario == "no_topics":
        set_counts(pubmed_api)
    url = "/science?q=bakuchiol&reviews=1" if scenario == "reviews" else "/science?q=bakuchiol"
    body = text(re.sub(r'<ul class="paper-list">.*?</ul>', "", page(client, url), flags=re.S)).lower()
    for word in BANNED:
        assert word not in body, (scenario, word)


def test_the_topic_words_are_only_in_the_content_file_and_the_tests():
    for name in ("templates/science.html", "app.py", "database/services.py", "live/pubmed.py"):
        source = pathlib.Path(name).read_text(encoding="utf-8").lower()
        for topic in ("acne", "rosacea", "eczema", "hyperpigmentation"):
            assert topic not in source, (name, topic)
