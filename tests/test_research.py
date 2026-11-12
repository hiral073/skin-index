import html as html_lib
import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from content import research as research_content
from database.db import get_db

# Our own wording on the Research page must never use these (PubMed's paper titles are quoted
# verbatim and are not ours, so the check skips the result list).
BANNED = ["safe", "best for", "treats", "cures", "proven", "effective"]

NOTE = ("Listing of published papers. A study existing does not mean a product works. "
        "Source: PubMed (US National Library of Medicine).")


def page(client, url="/research"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def main(html):
    return html.split('class="research-page"', 1)[1].split("</section>", 1)[0]


def chrome(html):
    """The page without PubMed's paper list (titles and journals are quoted, not our wording)."""
    return re.sub(r'<ol class="paper-list">.*?</ol>', "", html, flags=re.S)


def papers(html):
    found = re.findall(r"<li>\s*<a class=\"paper-title\" href=\"([^\"]+)\"[^>]*>(.*?)</a>\s*"
                       r"<div class=\"paper-meta\">(.*?)</div>", html, re.S)
    return [(href, text(title), text(meta)) for href, title, meta in found]


def seed(api):
    api.add(111, "Niacinamide: a review of dermal delivery strategies and clinical evidence.", journal="Drug delivery and translational research",
            year="2024 Dec", types=("Journal Article", "Review", "Research Support, Non-U.S. Gov't"))
    api.add(222, "The effect of niacinamide on reducing cutaneous pigmentation.", journal="The British journal of dermatology",
            year="2002 Jul", types=("Clinical Trial", "Journal Article", "Randomized Controlled Trial"))
    api.add(333, "A study of niacinamide and skin.", journal="Skin pharmacology and physiology", year="2014",
            types=("Journal Article",))


# ---------------------------------------------------------------- the page before a search

def test_the_page_without_a_search_has_the_form_and_quick_links_and_calls_nothing(client, pubmed_api):
    html = page(client)
    body = text(main(html))
    assert "Research" in body and 'name="q"' in html and 'type="checkbox" name="reviews"' in html
    assert ">Search</button>" in html and "Reviews only" in body
    assert "paper-list" not in html and 'id="research-note"' not in html
    assert pubmed_api.calls == []


def test_quick_links_cover_the_six_ingredients(client, pubmed_api):
    html = page(client)
    links = re.findall(r'<a class="btn-ghost" href="([^"]+)">(.*?)</a>', main(html))
    assert [label for _h, label in links] == ["niacinamide", "retinol", "vitamin C", "hyaluronic acid",
                                              "salicylic acid", "ceramides"]
    assert [parse_qs(urlparse(h).query)["q"] for h, _l in links] == [
        ["niacinamide"], ["retinol"], ["vitamin C"], ["hyaluronic acid"], ["salicylic acid"], ["ceramides"]]
    assert all(urlparse(h).path == "/research" for h, _l in links)


def test_quick_links_keep_the_reviews_only_choice(client, pubmed_api):
    links = re.findall(r'<a class="btn-ghost" href="([^"]+)">', main(page(client, "/research?reviews=1")))
    assert links and all(parse_qs(urlparse(h.replace("&amp;", "&")).query).get("reviews") == ["1"] for h in links)
    assert 'name="reviews" value="1" checked' in page(client, "/research?reviews=1&q=retinol")


def test_a_quick_link_runs_a_search(client, pubmed_api):
    seed(pubmed_api)
    link = re.findall(r'<a class="btn-ghost" href="([^"]+)">vitamin C</a>', page(client))[0].replace("&amp;", "&")
    html = page(client, link)
    assert pubmed_api.calls[0][1]["term"] == "vitamin c AND skin" and len(papers(html)) == 3


def test_research_is_in_the_navigation_and_the_ncbi_notice_is_on_the_page(client, pubmed_api):
    for url in ("/", "/products", "/compare", "/insights", "/today", "/research"):
        assert '<a href="/research">Research</a>' in page(client, url)
    html = page(client)
    assert '<a href="https://www.ncbi.nlm.nih.gov/home/about/policies/" rel="noopener">NCBI Disclaimer and Copyright</a>' in html


# ---------------------------------------------------------------- results

def test_results_show_title_journal_year_types_and_a_pubmed_link(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/research?q=niacinamide")
    assert papers(html) == [
        ("https://pubmed.ncbi.nlm.nih.gov/111/", "Niacinamide: a review of dermal delivery strategies and clinical evidence",
         "Review Drug delivery and translational research · 2024"),
        ("https://pubmed.ncbi.nlm.nih.gov/222/", "The effect of niacinamide on reducing cutaneous pigmentation",
         "Randomized Controlled Trial Clinical Trial The British journal of dermatology · 2002"),
        ("https://pubmed.ncbi.nlm.nih.gov/333/", "A study of niacinamide and skin",
         "Journal Article Skin pharmacology and physiology · 2014"),
    ]
    assert html.count('rel="noopener"') == 3 + 1                         # three papers and the NCBI notice link


def test_the_note_appears_once_above_the_results_word_for_word(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/research?q=niacinamide")
    assert research_content.NOTE == NOTE
    assert text(html).count(NOTE) == 1
    assert 'id="research-note"' in html and html.index('id="research-note"') < html.index('class="paper-list"')


def test_the_search_that_was_run_is_shown_and_the_box_keeps_the_text(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/research?q=Vitamin+C")
    assert "PubMed search: vitamin c AND skin" in text(html)
    assert 'value="Vitamin C"' in html and "reviews only" not in text(main(html))


def test_at_most_ten_papers_are_listed(client, pubmed_api):
    for i in range(1, 16):
        pubmed_api.add(1000 + i, f"Paper number {i}")
    html = page(client, "/research?q=retinol")
    assert len(papers(html)) == 10 and papers(html)[0][1] == "Paper number 1"


def test_missing_journal_or_year_say_so(client, pubmed_api):
    pubmed_api.records["5"] = {"uid": "5", "title": "A bare record", "pubtype": []}
    assert papers(page(client, "/research?q=retinol"))[0][2] == "Journal not available · Year not available"


def test_titles_from_pubmed_are_escaped_and_comparison_signs_survive(client, pubmed_api):
    pubmed_api.records["7"] = {"uid": "7", "title": "<script>alert(1)</script> & pH < 5 and > 3", "pubtype": []}
    html = page(client, "/research?q=retinol")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; pH &lt; 5 and &gt; 3" in html
    assert papers(html)[0][1] == "<script>alert(1)</script> & pH < 5 and > 3"             # shown as plain text


def test_titles_are_quoted_verbatim_even_when_they_use_words_we_never_use(client, pubmed_api):
    pubmed_api.add(8, "Efficacy and safety of a retinol cream: an effective treatment?")
    html = page(client, "/research?q=retinol")
    assert papers(html)[0][1] == "Efficacy and safety of a retinol cream: an effective treatment?"
    assert not any(word in text(chrome(html)).lower() for word in BANNED)        # our own wording is clean


# ---------------------------------------------------------------- reviews only

def test_reviews_only_sends_the_review_filter_and_lists_only_reviews(client, pubmed_api):
    pubmed_api.add(1, "A review of retinol", types=("Journal Article", "Review"))
    pubmed_api.add(2, "A delphi consensus study", types=("Journal Article", "Consensus Statement"))
    pubmed_api.add(3, "A retinol trial", types=("Randomized Controlled Trial",))
    html = page(client, "/research?q=retinol&reviews=1")
    assert pubmed_api.calls[0][1]["term"] == "retinol AND skin AND (review[pt] OR systematic review[pt])"
    assert [t for _h, t, _m in papers(html)] == ["A review of retinol"]
    assert "reviews only" in text(main(html)) and 'name="reviews" value="1" checked' in html


def test_without_the_checkbox_all_types_are_listed(client, pubmed_api):
    pubmed_api.add(1, "A review", types=("Review",))
    pubmed_api.add(3, "A trial", types=("Randomized Controlled Trial",))
    html = page(client, "/research?q=retinol")
    assert len(papers(html)) == 2 and 'name="reviews" value="1" checked' not in html


# ---------------------------------------------------------------- no results, errors, saved copies

def test_no_papers_shows_a_friendly_line_and_no_note(client, pubmed_api):
    html = page(client, "/research?q=zzzzqqqxx")
    assert "No papers found for “zzzzqqqxx”." in text(main(html))
    assert 'id="research-note"' not in html and "paper-list" not in html


def test_pubmed_down_with_nothing_saved_says_research_search_is_unavailable(client, pubmed_api):
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/research?q=retinol")
    assert "Research search is unavailable right now." in text(main(html))
    assert 'id="research-note"' not in html and "paper-list" not in html


def test_pubmed_down_shows_the_saved_copy_with_its_date(client, pubmed_api, app):
    seed(pubmed_api)
    page(client, "/research?q=niacinamide")
    with closing(get_db(app.config["DATABASE"])) as conn, conn:          # make the saved copy two days old
        conn.execute("UPDATE pubmed_searches SET fetched_at = '2026-01-05T09:30:00+00:00'")
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/research?q=niacinamide")
    assert "PubMed could not be reached, so these are saved results from 5 Jan 2026." in text(main(html))
    assert len(papers(html)) == 3 and text(html).count(NOTE) == 1
    assert "unavailable right now" not in text(html)


def test_a_repeat_search_uses_the_saved_copy_without_calling_pubmed(client, pubmed_api):
    seed(pubmed_api)
    first = page(client, "/research?q=niacinamide")
    calls = len(pubmed_api.calls)
    second = page(client, "/research?q=niacinamide")
    assert len(pubmed_api.calls) == calls and papers(second) == papers(first)
    assert "saved results from" not in text(second)                      # a fresh copy needs no explanation


@pytest.mark.parametrize("query", ["a", '"retinol"', "retinol[ti]", "http://evil.example", "x" * 61, "a:b"])
def test_unusable_search_text_is_refused_with_a_message_and_no_call(client, pubmed_api, query):
    html = client.get("/research", query_string={"q": query}).get_data(as_text=True)
    assert "Please enter an ingredient name using letters, numbers" in text(main(html))
    assert pubmed_api.calls == [] and "paper-list" not in html


def test_the_search_box_never_echoes_markup(client, pubmed_api):
    html = client.get("/research", query_string={"q": "<b>x</b>"}).get_data(as_text=True)
    assert 'value="&lt;b&gt;x&lt;/b&gt;"' in html and "<b>x</b>" not in html and 'maxlength="60"' in html


def test_a_blank_search_is_just_the_empty_page(client, pubmed_api):
    html = page(client, "/research?q=+++")
    assert "Please enter" not in html and pubmed_api.calls == []


# ---------------------------------------------------------------- wording

def scenario_html(client, pubmed_api, name):
    seed(pubmed_api)
    if name == "results":
        return page(client, "/research?q=niacinamide")
    if name == "reviews":
        return page(client, "/research?q=niacinamide&reviews=1")
    if name == "empty":
        pubmed_api.records.clear()
        return page(client, "/research?q=zzzzqqqxx")
    if name == "unavailable":
        pubmed_api.error["esearch"] = requests.Timeout("slow")
        return page(client, "/research?q=niacinamide")
    if name == "invalid":
        return page(client, "/research?q=%5Bx%5D")
    return page(client, "/research")


@pytest.mark.parametrize("name", ["results", "reviews", "empty", "unavailable", "invalid", "no_search"])
def test_the_research_page_never_uses_the_banned_wording(client, pubmed_api, name):
    html = scenario_html(client, pubmed_api, name)
    body = text(html).lower()                                           # the whole page (the test titles are neutral)
    for word in BANNED:
        assert word not in body, (name, word)
    for word in BANNED:
        assert word not in text(chrome(html)).lower()


def test_the_banned_word_check_would_catch_our_own_wording(client, pubmed_api, monkeypatch):
    monkeypatch.setattr(research_content, "NOTE", NOTE + " This ingredient is safe.")
    seed(pubmed_api)
    html = page(client, "/research?q=niacinamide")
    assert "safe" in text(chrome(html)).lower()


def test_the_saved_copy_message_and_the_other_texts_use_none_of_the_banned_words():
    c = research_content
    texts = [c.TITLE, c.INTRO, c.NOTE, c.QUICK_LINKS_LABEL, c.SEARCH_PLACEHOLDER, c.REVIEWS_ONLY_LABEL, c.QUERY_LINE,
             c.REVIEWS_ONLY_NOTE, c.EMPTY, c.UNAVAILABLE, c.STALE, c.INVALID, c.NCBI_POLICIES_LABEL] + c.QUICK_LINKS
    for text_ in texts:
        for word in BANNED:
            assert word not in text_.lower(), (word, text_)


def test_the_fixed_texts_are_exactly_as_specified():
    c = research_content
    assert c.NOTE == NOTE
    assert c.UNAVAILABLE == "Research search is unavailable right now."
    assert c.QUICK_LINKS == ["niacinamide", "retinol", "vitamin C", "hyaluronic acid", "salicylic acid", "ceramides"]
    assert c.REVIEWS_ONLY_LABEL == "Reviews only"


def test_no_health_claims_beyond_the_note(client, pubmed_api):
    body = text(main(scenario_html(client, pubmed_api, "results"))).lower()
    for phrase in ("works", "helps", "improves", "reduces", "good for", "recommended", "benefit", "evidence shows"):
        assert body.count(phrase) == (1 if phrase == "works" else 0), phrase     # "works" is only in the required note
