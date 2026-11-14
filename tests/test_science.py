import html as html_lib
import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from content import science as science_content
from database.db import get_db
from database.services import group_papers, paper_label

# Our own wording on the Ingredient Science page must never use these (PubMed's paper titles are quoted
# verbatim and are not ours, so the check skips the result list).
BANNED = ["safe", "best for", "treats", "cures", "proven", "effective"]

NOTE = ("Listing of published papers. A study existing does not mean a product works. "
        "Source: PubMed (US National Library of Medicine).")

LABELS_LINE = ("Papers are grouped by kind, using the type PubMed records for each one: overview papers, "
               "studies combined into one analysis, trials with people and other research papers. "
               "The groups are not our summary of what a paper found.")

OVERVIEW, COMBINED, TRIAL, PAPER = (
    "Start here: overview papers", "Studies combined into one analysis", "Trials with people",
    "Other research papers",
)


def page(client, url="/science"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def main(html):
    return html.split('class="science-page"', 1)[1].split("</section>", 1)[0]


def chrome(html):
    """The page without PubMed's paper cards (titles and journals are quoted, not our wording)."""
    return re.sub(r'<ul class="paper-list">.*?</ul>', "", html, flags=re.S)


CARD = re.compile(
    r'<li class="paper-card">\s*<p class="paper-title" title="([^"]*)">(.*?)</p>\s*'
    r'<p class="paper-meta">(.*?)</p>\s*<a class="btn-ghost paper-link" href="([^"]+)" rel="noopener">(.*?)</a>\s*</li>',
    re.S)


def cards(html):
    """(full title from the hover text, shown title, journal and year, link, link text) per card."""
    return [(html_lib.unescape(full), html_lib.unescape(shown), text(meta), href, link)
            for full, shown, meta, href, link in CARD.findall(html)]


def groups(html):
    """[(group label, [shown titles])] in page order."""
    found = []
    for part in html.split('<h2 class="section-title paper-group-title">')[1:]:
        label, rest = part.split("</h2>", 1)
        found.append((label, [shown for _f, shown, _m, _h, _l in cards(rest.split("</ul>", 1)[0])]))
    return found


def seed(api):
    api.add(111, "Niacinamide: a review of dermal delivery strategies and clinical evidence.", journal="Drug delivery and translational research",
            year="2024 Dec", types=("Journal Article", "Review", "Research Support, Non-U.S. Gov't"))
    api.add(222, "The effect of niacinamide on reducing cutaneous pigmentation.", journal="The British journal of dermatology",
            year="2002 Jul", types=("Clinical Trial", "Journal Article", "Randomized Controlled Trial"))
    api.add(333, "A study of niacinamide and skin.", journal="Skin pharmacology and physiology", year="2014",
            types=("Journal Article",))


def seed_every_label(api):
    seed(api)
    api.add(444, "A systematic look at niacinamide.", journal="Journal A", year="2020",
            types=("Journal Article", "Systematic Review", "Review"))
    api.add(555, "A small niacinamide group study.", journal="Journal B", year="2019", types=("Clinical Trial",))
    api.add(666, "Pooled niacinamide results.", journal="Journal C", year="2021", types=("Meta-Analysis",))


# ---------------------------------------------------------------- the page before a search

def test_the_page_without_a_search_has_the_form_and_quick_links_and_calls_nothing(client, pubmed_api):
    html = page(client)
    body = text(main(html))
    assert "Ingredient Science" in body and 'name="q"' in html and 'type="checkbox" name="reviews"' in html
    assert ">Search</button>" in html and "Overview papers and combined analyses only" in body
    assert "paper-list" not in html and 'id="research-note"' not in html and 'id="labels-line"' not in html
    assert pubmed_api.calls == []


def test_the_page_title_is_ingredient_science(client):
    assert "<title>Ingredient Science · Skin Index</title>" in page(client)
    assert "<h1 class=\"page-title\">Ingredient Science</h1>" in page(client)


def test_quick_links_cover_the_six_ingredients(client, pubmed_api):
    html = page(client)
    links = re.findall(r'<a class="btn-ghost" href="([^"]+)">(.*?)</a>', main(html))
    assert [label for _h, label in links] == ["niacinamide", "retinol", "vitamin C", "hyaluronic acid",
                                              "salicylic acid", "ceramides"]
    assert [parse_qs(urlparse(h).query)["q"] for h, _l in links] == [
        ["niacinamide"], ["retinol"], ["vitamin C"], ["hyaluronic acid"], ["salicylic acid"], ["ceramides"]]
    assert all(urlparse(h).path == "/science" for h, _l in links)


def test_quick_links_keep_the_reviews_only_choice(client, pubmed_api):
    links = re.findall(r'<a class="btn-ghost" href="([^"]+)">', main(page(client, "/science?reviews=1")))
    assert links and all(parse_qs(urlparse(h.replace("&amp;", "&")).query).get("reviews") == ["1"] for h in links)
    assert 'name="reviews" value="1" checked' in page(client, "/science?reviews=1&q=retinol")


def test_a_quick_link_runs_a_search(client, pubmed_api):
    seed(pubmed_api)
    link = re.findall(r'<a class="btn-ghost" href="([^"]+)">vitamin C</a>', page(client))[0].replace("&amp;", "&")
    html = page(client, link)
    assert pubmed_api.calls[0][1]["term"] == "vitamin c AND skin" and len(cards(html)) == 3


# ---------------------------------------------------------------- navigation, footer, old address

PAGES = ["/", "/products", "/compare", "/insights", "/today", "/science"]


def test_ingredient_science_is_not_in_the_top_navigation(client, pubmed_api):
    for url in PAGES:
        nav = page(client, url).split('<nav class="navbar">')[1].split("</nav>")[0]
        assert "Research" not in nav and "Ingredient Science" not in nav and "/science" not in nav, url
        assert ">Products</a>" in nav and ">Today</a>" in nav


def test_the_footer_has_a_learn_more_heading_with_the_ingredient_science_link(client, pubmed_api):
    for url in PAGES:
        footer = page(client, url).split('<footer class="footer">')[1].split("</footer>")[0]
        assert '<p class="footer-heading">Learn more</p>' in footer, url
        assert '<a class="footer-link" href="/science">Ingredient Science</a>' in footer, url
        assert footer.index("Learn more") < footer.index("Ingredient Science")


def test_the_ncbi_notice_is_on_the_page(client, pubmed_api):
    html = page(client)
    assert '<a href="https://www.ncbi.nlm.nih.gov/home/about/policies/" rel="noopener">NCBI Disclaimer and Copyright</a>' in html


def test_the_old_research_address_redirects_for_good(client, pubmed_api):
    response = client.get("/research")
    assert response.status_code == 301 and urlparse(response.headers["Location"]).path == "/science"
    assert urlparse(response.headers["Location"]).query == ""


def test_the_redirect_keeps_the_search_and_the_reviews_choice(client, pubmed_api):
    response = client.get("/research?q=vitamin+C&reviews=1")
    location = urlparse(response.headers["Location"])
    assert response.status_code == 301 and location.path == "/science"
    assert parse_qs(location.query) == {"q": ["vitamin C"], "reviews": ["1"]}
    assert parse_qs(urlparse(client.get("/research?q=retinol").headers["Location"]).query) == {"q": ["retinol"]}
    assert pubmed_api.calls == []                                           # a redirect searches nothing


def test_the_redirect_drops_other_parameters_and_follows_to_the_page(client, pubmed_api):
    location = client.get("/research?q=retinol&evil=1").headers["Location"]
    assert parse_qs(urlparse(location).query) == {"q": ["retinol"]}
    seed(pubmed_api)
    followed = client.get("/research?q=niacinamide", follow_redirects=True)
    assert followed.status_code == 200 and len(cards(followed.get_data(as_text=True))) == 3


# ---------------------------------------------------------------- results as cards

def test_each_paper_is_a_card_with_title_journal_year_and_a_pubmed_link(client, pubmed_api):
    seed(pubmed_api)
    found = cards(page(client, "/science?q=niacinamide"))
    assert [(full, journal, href, link) for full, _s, journal, href, link in found] == [
        ("Niacinamide: a review of dermal delivery strategies and clinical evidence",
         "Drug delivery and translational research · 2024", "https://pubmed.ncbi.nlm.nih.gov/111/", "Read on PubMed"),
        ("The effect of niacinamide on reducing cutaneous pigmentation",
         "The British journal of dermatology · 2002", "https://pubmed.ncbi.nlm.nih.gov/222/", "Read on PubMed"),
        ("A study of niacinamide and skin",
         "Skin pharmacology and physiology · 2014", "https://pubmed.ncbi.nlm.nih.gov/333/", "Read on PubMed"),
    ]


def test_technical_publication_types_authors_and_codes_are_not_shown(client, pubmed_api):
    seed_every_label(pubmed_api)
    body = text(main(page(client, "/science?q=niacinamide")))
    for technical in ("Randomized Controlled Trial", "Journal Article", "Meta-Analysis", "Systematic Review",
                      "Research Support", "PMID", "pubmed.ncbi", "doi", "Author"):
        assert technical not in body, technical
    assert "Clinical Trial" not in body and not re.search(r"\b\d{3}\b/", body)


def test_papers_are_grouped_under_plain_labels_summaries_first(client, pubmed_api):
    seed_every_label(pubmed_api)
    assert groups(page(client, "/science?q=niacinamide")) == [
        (OVERVIEW, ["Niacinamide: a review of dermal delivery strategies and clinical evidence"]),
        (COMBINED, ["A systematic look at niacinamide", "Pooled niacinamide results"]),
        (TRIAL, ["The effect of niacinamide on reducing cutaneous pigmentation", "A small niacinamide group study"]),
        (PAPER, ["A study of niacinamide and skin"]),
    ]


def test_empty_groups_are_left_out_and_order_inside_a_group_is_pubmeds(client, pubmed_api):
    pubmed_api.add(1, "First paper", types=("Journal Article",))
    pubmed_api.add(2, "Second paper", types=("Journal Article",))
    pubmed_api.add(3, "A review", types=("Review",))
    assert groups(page(client, "/science?q=retinol")) == [(OVERVIEW, ["A review"]), (PAPER, ["First paper", "Second paper"])]


def test_the_label_explanation_sits_below_the_note_and_above_the_groups(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/science?q=niacinamide")
    assert science_content.LABELS_LINE == LABELS_LINE and text(html).count(LABELS_LINE) == 1
    assert html.index('id="research-note"') < html.index('id="labels-line"') < html.index("paper-group-title")
    pubmed_api.records.clear()
    assert "labels-line" not in page(client, "/science?q=zzzzqqqxx")


def test_long_titles_are_shortened_with_the_full_title_on_hover(client, pubmed_api):
    long_title = " ".join(f"word{i:02d}" for i in range(40))                  # 279 characters
    pubmed_api.add(9, long_title)
    pubmed_api.add(10, "A short title")
    html = page(client, "/science?q=retinol")
    (full, shown, _m, _h, _l), (full2, shown2, *_rest) = cards(html)
    assert full == long_title and shown.endswith("…") and 100 <= len(shown) <= 121
    assert long_title.startswith(shown[:-1]) and long_title[len(shown) - 1] == " "         # cut at a word boundary
    assert full2 == shown2 == "A short title"
    assert 'title="A short title">A short title</p>' in html and "…" not in shown2


def test_a_title_of_exactly_the_limit_is_not_cut(client, pubmed_api):
    exact = "a " * 59 + "a"                                                    # 119 characters
    pubmed_api.add(11, exact + "b")                                             # exactly 120
    (_full, shown, *_rest), = cards(page(client, "/science?q=retinol"))
    assert len(exact + "b") == science_content.TITLE_MAX_LENGTH and shown == exact + "b"


def test_trailing_punctuation_is_dropped_before_the_ellipsis(client, pubmed_api):
    pubmed_api.add(13, "a" * 115 + ", " + "b" * 40)
    (_full, shown, *_rest), = cards(page(client, "/science?q=retinol"))
    assert shown == "a" * 115 + "…"


def test_a_long_title_without_spaces_is_cut_at_the_limit(client, pubmed_api):
    pubmed_api.add(12, "x" * 300)
    (_full, shown, *_rest), = cards(page(client, "/science?q=retinol"))
    assert shown == "x" * 120 + "…"


def test_the_note_appears_once_above_the_results_word_for_word(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/science?q=niacinamide")
    assert science_content.NOTE == NOTE
    assert text(html).count(NOTE) == 1
    assert 'id="research-note"' in html and html.index('id="research-note"') < html.index("paper-group-title")


def test_the_search_that_was_run_is_shown_and_the_box_keeps_the_text(client, pubmed_api):
    seed(pubmed_api)
    html = page(client, "/science?q=Vitamin+C")
    assert "PubMed search: vitamin c AND skin" in text(html)
    assert 'value="Vitamin C"' in html and "· overview papers and combined analyses only" not in text(main(html))


def test_at_most_ten_papers_are_listed(client, pubmed_api):
    for i in range(1, 16):
        pubmed_api.add(1000 + i, f"Paper number {i}")
    found = cards(page(client, "/science?q=retinol"))
    assert len(found) == 10 and found[0][1] == "Paper number 1"


def test_missing_journal_or_year_say_so(client, pubmed_api):
    pubmed_api.records["5"] = {"uid": "5", "title": "A bare record", "pubtype": []}
    assert cards(page(client, "/science?q=retinol"))[0][2] == "Journal not available · Year not available"


def test_titles_from_pubmed_are_escaped_and_comparison_signs_survive(client, pubmed_api):
    pubmed_api.records["7"] = {"uid": "7", "title": "<script>alert(1)</script> & pH < 5 and > 3", "pubtype": []}
    html = page(client, "/science?q=retinol")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; pH &lt; 5 and &gt; 3" in html
    full, shown, *_rest = cards(html)[0]
    assert full == shown == "<script>alert(1)</script> & pH < 5 and > 3"      # the hover text is escaped too


def test_a_quote_in_a_title_cannot_break_out_of_the_hover_text(client, pubmed_api):
    pubmed_api.records["8"] = {"uid": "8", "title": 'Say "hi" onmouseover="alert(1)"', "pubtype": []}
    html = page(client, "/science?q=retinol")
    assert 'onmouseover="alert(1)"' not in html and "&#34;hi&#34;" in html
    assert cards(html)[0][0] == 'Say "hi" onmouseover="alert(1)"'


def test_titles_are_quoted_verbatim_even_when_they_use_words_we_never_use(client, pubmed_api):
    pubmed_api.add(8, "Efficacy and safety of a retinol cream: an effective treatment?")
    html = page(client, "/science?q=retinol")
    assert cards(html)[0][1] == "Efficacy and safety of a retinol cream: an effective treatment?"
    assert not any(word in text(chrome(html)).lower() for word in BANNED)        # our own wording is clean


# ---------------------------------------------------------------- plain labels

@pytest.mark.parametrize("types, label", [
    (["Review"], OVERVIEW),
    (["Systematic Review"], COMBINED),
    (["Meta-Analysis"], COMBINED),
    (["Review", "Systematic Review"], COMBINED),                  # the more specific label wins
    (["Review", "Meta-Analysis"], COMBINED),
    (["Randomized Controlled Trial"], TRIAL),
    (["Clinical Trial", "Randomized Controlled Trial"], TRIAL),
    (["Clinical Trial"], TRIAL),
    (["Review", "Randomized Controlled Trial"], OVERVIEW),
    (["Journal Article"], PAPER),
    (["Comparative Study", "Case Reports"], PAPER),
    (["Clinical Trial, Phase II"], PAPER),                        # only the listed types are mapped
    ([], PAPER),
    (None, PAPER),
])
def test_publication_types_become_plain_labels(types, label):
    assert paper_label(types) == label


def test_group_papers_orders_the_groups_and_keeps_pubmeds_order_inside(client):
    papers = [{"title": "t1", "types": ["Clinical Trial"]}, {"title": "t2", "types": ["Review"]},
              {"title": "t3", "types": []}, {"title": "t4", "types": ["Review"]}]
    assert [(g["label"], [p["title"] for p in g["papers"]]) for g in group_papers(papers)] == [
        (OVERVIEW, ["t2", "t4"]), (TRIAL, ["t1"]), (PAPER, ["t3"])]
    assert group_papers([]) == []


def test_the_labels_and_their_order_are_exactly_as_specified():
    c = science_content
    assert c.PAPER_LABELS == [
        ("Studies combined into one analysis", ["Systematic Review", "Meta-Analysis"]),
        ("Start here: overview papers", ["Review"]),
        ("Trials with people", ["Randomized Controlled Trial", "Clinical Trial"]),
    ]
    assert c.OTHER_LABEL == "Other research papers"
    assert c.GROUP_ORDER == [OVERVIEW, COMBINED, TRIAL, PAPER]
    assert c.TITLE_MAX_LENGTH == 120 and c.READ_LINK_LABEL == "Read on PubMed" and c.LABELS_LINE == LABELS_LINE


# ---------------------------------------------------------------- reviews only

def test_reviews_only_sends_the_review_filter_and_lists_only_reviews(client, pubmed_api):
    pubmed_api.add(1, "A review of retinol", types=("Journal Article", "Review"))
    pubmed_api.add(2, "A delphi consensus study", types=("Journal Article", "Consensus Statement"))
    pubmed_api.add(3, "A retinol trial", types=("Randomized Controlled Trial",))
    html = page(client, "/science?q=retinol&reviews=1")
    assert pubmed_api.calls[0][1]["term"] == "retinol AND skin AND (review[pt] OR systematic review[pt])"
    assert [t for _f, t, *_rest in cards(html)] == ["A review of retinol"]
    assert "overview papers and combined analyses only" in text(main(html)) and 'name="reviews" value="1" checked' in html


def test_without_the_checkbox_all_types_are_listed(client, pubmed_api):
    pubmed_api.add(1, "A review", types=("Review",))
    pubmed_api.add(3, "A trial", types=("Randomized Controlled Trial",))
    html = page(client, "/science?q=retinol")
    assert len(cards(html)) == 2 and 'name="reviews" value="1" checked' not in html


# ---------------------------------------------------------------- no results, errors, saved copies

def test_no_papers_shows_a_friendly_line_and_no_note(client, pubmed_api):
    html = page(client, "/science?q=zzzzqqqxx")
    assert "No papers found for “zzzzqqqxx”." in text(main(html))
    assert 'id="research-note"' not in html and "paper-list" not in html


def test_pubmed_down_with_nothing_saved_says_research_search_is_unavailable(client, pubmed_api):
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/science?q=retinol")
    assert "Research search is unavailable right now." in text(main(html))
    assert 'id="research-note"' not in html and "paper-list" not in html


def test_pubmed_down_shows_the_saved_copy_with_its_date(client, pubmed_api, app):
    seed(pubmed_api)
    page(client, "/science?q=niacinamide")
    with closing(get_db(app.config["DATABASE"])) as conn, conn:          # make the saved copy two days old
        conn.execute("UPDATE pubmed_searches SET fetched_at = '2026-01-05T09:30:00+00:00'")
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/science?q=niacinamide")
    assert "PubMed could not be reached, so these are saved results from 5 Jan 2026." in text(main(html))
    assert len(cards(html)) == 3 and text(html).count(NOTE) == 1
    assert "unavailable right now" not in text(html)


def test_a_saved_copy_is_grouped_like_a_live_one(client, pubmed_api, app):
    seed(pubmed_api)
    first = groups(page(client, "/science?q=niacinamide"))
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    assert groups(page(client, "/science?q=niacinamide")) == first and len(first) == 3


def test_a_repeat_search_uses_the_saved_copy_without_calling_pubmed(client, pubmed_api):
    seed(pubmed_api)
    first = page(client, "/science?q=niacinamide")
    calls = len(pubmed_api.calls)
    second = page(client, "/science?q=niacinamide")
    assert len(pubmed_api.calls) == calls and cards(second) == cards(first)
    assert "saved results from" not in text(second)                      # a fresh copy needs no explanation


@pytest.mark.parametrize("query", ["a", '"retinol"', "retinol[ti]", "http://evil.example", "x" * 61, "a:b"])
def test_unusable_search_text_is_refused_with_a_message_and_no_call(client, pubmed_api, query):
    html = client.get("/science", query_string={"q": query}).get_data(as_text=True)
    assert "Please enter an ingredient name using letters, numbers" in text(main(html))
    assert pubmed_api.calls == [] and "paper-list" not in html


def test_the_search_box_never_echoes_markup(client, pubmed_api):
    html = client.get("/science", query_string={"q": "<b>x</b>"}).get_data(as_text=True)
    assert 'value="&lt;b&gt;x&lt;/b&gt;"' in html and "<b>x</b>" not in html and 'maxlength="60"' in html


def test_a_blank_search_is_just_the_empty_page(client, pubmed_api):
    html = page(client, "/science?q=+++")
    assert "Please enter" not in html and pubmed_api.calls == []


# ---------------------------------------------------------------- wording

def scenario_html(client, pubmed_api, name):
    seed_every_label(pubmed_api)
    if name == "results":
        return page(client, "/science?q=niacinamide")
    if name == "reviews":
        return page(client, "/science?q=niacinamide&reviews=1")
    if name == "empty":
        pubmed_api.records.clear()
        return page(client, "/science?q=zzzzqqqxx")
    if name == "unavailable":
        pubmed_api.error["esearch"] = requests.Timeout("slow")
        return page(client, "/science?q=niacinamide")
    if name == "invalid":
        return page(client, "/science?q=%5Bx%5D")
    return page(client, "/science")


@pytest.mark.parametrize("name", ["results", "reviews", "empty", "unavailable", "invalid", "no_search"])
def test_the_science_page_never_uses_the_banned_wording(client, pubmed_api, name):
    html = scenario_html(client, pubmed_api, name)
    body = text(html).lower()                                           # the whole page (the test titles are neutral)
    for word in BANNED:
        assert word not in body, (name, word)
    for word in BANNED:
        assert word not in text(chrome(html)).lower()


def test_the_banned_word_check_would_catch_our_own_wording(client, pubmed_api, monkeypatch):
    monkeypatch.setattr(science_content, "NOTE", NOTE + " This ingredient is safe.")
    seed(pubmed_api)
    html = page(client, "/science?q=niacinamide")
    assert "safe" in text(chrome(html)).lower()


def test_the_labels_and_the_other_texts_use_none_of_the_banned_words():
    c = science_content
    texts = [c.TITLE, c.INTRO, c.NOTE, c.LABELS_LINE, c.QUICK_LINKS_LABEL, c.SEARCH_PLACEHOLDER, c.REVIEWS_ONLY_LABEL,
             c.QUERY_LINE, c.REVIEWS_ONLY_NOTE, c.EMPTY, c.UNAVAILABLE, c.STALE, c.INVALID, c.NCBI_POLICIES_LABEL,
             c.READ_LINK_LABEL, c.OTHER_LABEL] + c.QUICK_LINKS + [label for label, _types in c.PAPER_LABELS]
    for text_ in texts:
        for word in BANNED:
            assert word not in text_.lower(), (word, text_)


def test_the_fixed_texts_are_exactly_as_specified():
    c = science_content
    assert c.NOTE == NOTE and c.TITLE == "Ingredient Science"
    assert c.UNAVAILABLE == "Research search is unavailable right now."
    assert c.QUICK_LINKS == ["niacinamide", "retinol", "vitamin C", "hyaluronic acid", "salicylic acid", "ceramides"]
    assert c.REVIEWS_ONLY_LABEL == "Overview papers and combined analyses only"


def test_no_health_claims_beyond_the_note(client, pubmed_api):
    body = text(main(scenario_html(client, pubmed_api, "results"))).lower()
    for phrase in ("works", "helps", "improves", "reduces", "good for", "recommended", "benefit", "evidence shows",
                   "found that", "shows that", "suggests", "results show"):
        # "works" is only in the required note (niacinamide has a card, which has no such line)
        assert body.count(phrase) == (1 if phrase == "works" else 0), phrase


# ---------------------------------------------------------------- the link from a product page

def product_page(app, client, name, ingredients):
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, 'Dew Labs', 'Face Serums', 20, '100 mL', 0.2, 'Face Serums')", (name,)).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return page(client, f"/products/{pid}")


def science_links(html):
    return re.findall(r'<a class="btn-ghost" href="(/science[^"]*)">(.*?)</a>', html)


def test_a_product_with_a_main_ingredient_links_to_studies_on_it(app, client):
    html = product_page(app, client, "Bravo Serum", ["Water", "Niacinamide"])
    assert science_links(html) == [("/science?q=niacinamide", "Studies on niacinamide")]


def test_a_product_in_several_main_groups_gets_a_link_for_each(app, client):
    html = product_page(app, client, "Duo Serum", ["Water", "Niacinamide", "Glycolic Acid"])
    assert science_links(html) == [("/science?q=niacinamide", "Studies on niacinamide"),
                                   ("/science?q=glycolic+acid", "Studies on glycolic acid")]


def test_a_product_in_no_main_group_has_no_studies_link(app, client):
    html = product_page(app, client, "Plain Serum", ["Water", "Glycerin"])
    assert science_links(html) == [] and "Studies on" not in html


def test_the_studies_link_uses_the_same_first_ten_rule_as_compare(app, client):
    html = product_page(app, client, "Deep Serum", [f"Filler {i}" for i in range(10)] + ["Niacinamide"])
    assert "Studies on" not in html


def test_the_studies_link_leads_to_a_search_with_the_science_term(app, client, pubmed_api):
    seed(pubmed_api)
    html = product_page(app, client, "Vit Serum", ["Ascorbic Acid"])
    (href, label), = science_links(html)
    assert label == "Studies on ascorbic acid" and parse_qs(urlparse(href).query) == {"q": ["ascorbic acid"]}
    assert len(cards(page(client, href))) == 3 and pubmed_api.calls[0][1]["term"] == "ascorbic acid AND skin"
