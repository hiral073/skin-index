import html as html_lib
import re
from datetime import date
from urllib.parse import urlparse

import pytest
import requests

from content import ingredient_cards as cards_content
from database.services import get_ingredient_card

# Our own card text must never use these, and never names a skin type
BANNED = ["safe", "best for", "treats", "cures", "proven", "effective", "helps", "is for", "recommend", "suitable",
          "should", "improves", "reduces"]
SKIN_TYPES = ["skin type", "oily", "dry skin", "sensitive skin", "acne-prone", "combination skin", "normal skin",
              "dry or", "skin concern"]

NOTE = "General information from the sources named. Not medical advice."

NAMES = ["niacinamide", "retinol", "retinal", "vitamin c", "hyaluronic acid", "salicylic acid", "ceramides"]

# What the page shows for each card, in full: the lines, their topics and their sources
EXPECTED_BOX = {
    "niacinamide": (
        "At a glance What it is A form of vitamin B3. Source: ChEBI (EMBL-EBI) "
        "Often discussed in relation to the digestive system, skin and nerves (as described for niacin (vitamin B3)). "
        "Source: MedlinePlus: Niacin " + NOTE),
    "retinol": (
        "At a glance What it is A form of vitamin A, found in animal liver and whole milk. "
        "Source: MedlinePlus: Vitamin A "
        "Often discussed in relation to uneven skin tone, pigmentation and texture. "
        "Source: American Academy of Dermatology: Retinoid or retinol? " + NOTE),
    "retinal": (
        "At a glance What it is A vitamin A derivative that is the active component of the visual cycle. "
        "Source: NLM MeSH: Retinaldehyde Often discussed in relation to the visual cycle (vision). "
        "Source: NLM MeSH: Retinaldehyde " + NOTE),
    "vitamin c": (
        "At a glance What it is A water-soluble vitamin found in fruits and vegetables. Source: MedlinePlus: Vitamin C "
        "Often discussed in relation to collagen formation, wound healing and antioxidants. "
        "Source: MedlinePlus: Vitamin C " + NOTE),
    "hyaluronic acid": (
        "At a glance What it is A sugar-based molecule found in the connective tissues of vertebrates. "
        "Source: ChEBI (EMBL-EBI) Often discussed in relation to hydration, skin texture and fine lines. "
        "Source: American Academy of Dermatology: A dermatologist's guide to skincare " + NOTE),
    "salicylic acid": (
        "At a glance What it is Obtained from the bark of the white willow and wintergreen leaves. "
        "Source: ChEBI (EMBL-EBI) Often discussed in relation to acne, scaling skin conditions and warts and calluses. "
        "Source: MedlinePlus: Salicylic Acid Topical " + NOTE),
    "ceramides": (
        "At a glance What it is Fats (lipids) that make up about half of the epidermis, the outer layer of skin. "
        "Source: Cleveland Clinic: What Do Ceramides Do for Your Skin? "
        "Often discussed in relation to the skin barrier, moisture and eczema. "
        "Source: Cleveland Clinic: What Do Ceramides Do for Your Skin? " + NOTE),
}


def all_texts():
    """Every piece of our own text in the content file."""
    c = cards_content
    texts = [c.CARD_TITLE, c.CARD_WHAT_LABEL, c.CARD_DISCUSSED_LABEL, c.CARD_SOURCE_LABEL, c.CARD_NOTE]
    for card in c.CARDS:
        for part in (card["what"], card["discussed"]):
            if not part:
                continue
            texts += [part.get("text") or "", part.get("context") or "", part["source"]["name"]] + part.get("topics", [])
    return [t for t in texts if t]


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def box(html):
    found = re.search(r'<section class="glance" id="glance" data-kind="(card|counts)">(.*?)</section>', html, re.S)
    return (found.group(1), found.group(2)) if found else None


def papers(api):
    api.add(1, "A paper", year="2020")


# ---------------------------------------------------------------- the content file

def test_there_is_a_card_for_each_of_the_seven_ingredients_in_order():
    assert [c["key"] for c in cards_content.CARDS] == NAMES


def test_every_entry_has_at_least_one_source_with_a_name_and_a_link():
    for card in cards_content.CARDS:
        lines = [card[k] for k in ("what", "discussed") if card[k]]
        assert lines, card["key"]
        for line in lines:
            source = line["source"]
            assert source["name"].strip(), card["key"]
            parsed = urlparse(source["url"])
            assert parsed.scheme == "https" and parsed.netloc and "." in parsed.netloc, (card["key"], source)


def test_every_line_has_its_own_source_and_only_the_two_lines_exist():
    for card in cards_content.CARDS:
        assert set(card) == {"key", "names", "checked", "what", "discussed"}
        assert set(card["what"]) == {"text", "source"}
        assert set(card["discussed"]) == {"topics", "context", "source"}


def test_the_topics_are_one_to_three_and_the_lines_are_short():
    for card in cards_content.CARDS:
        assert 1 <= len(card["discussed"]["topics"]) <= 3, card["key"]
        assert len(card["what"]["text"]) <= 100 and card["what"]["text"].endswith("."), card["key"]
        assert all(0 < len(t) <= 40 for t in card["discussed"]["topics"]), card["key"]


def test_the_sources_are_the_ones_read_and_named():
    hosts = {urlparse(c[k]["source"]["url"]).netloc for c in cards_content.CARDS for k in ("what", "discussed")}
    assert hosts == {"www.ebi.ac.uk", "medlineplus.gov", "meshb.nlm.nih.gov", "www.aad.org", "health.clevelandclinic.org"}


def test_names_are_lower_case_unique_and_include_the_ingredient_itself():
    seen = []
    for card in cards_content.CARDS:
        assert card["key"] in card["names"]
        assert all(n == n.lower() and n == n.strip() for n in card["names"])
        seen += card["names"]
    assert len(seen) == len(set(seen))


def test_each_entry_has_a_checked_date():
    for card in cards_content.CARDS:
        assert date.fromisoformat(card["checked"]) <= date.today()


def test_the_note_and_labels_are_exactly_as_specified():
    c = cards_content
    assert c.CARD_NOTE == NOTE and c.CARD_TITLE == "At a glance"
    assert (c.CARD_WHAT_LABEL, c.CARD_DISCUSSED_LABEL, c.CARD_SOURCE_LABEL) == (
        "What it is", "Often discussed in relation to", "Source")


def test_the_card_text_uses_none_of_the_banned_words_or_skin_types():
    for text_ in all_texts():
        low = text_.lower()
        for word in BANNED + SKIN_TYPES:
            assert not re.search(rf"\b{re.escape(word)}", low), (word, text_)


def test_the_banned_word_check_would_catch_wording_we_never_use(monkeypatch):
    monkeypatch.setitem(cards_content.CARDS[0]["what"], "text", "A form of vitamin B3 that helps skin.")
    assert any(re.search(rf"\b{re.escape(w)}", t.lower()) for t in all_texts() for w in BANNED)
    monkeypatch.setitem(cards_content.CARDS[0]["what"], "text", "Good for oily skin.")
    assert any(w in t.lower() for t in all_texts() for w in SKIN_TYPES)


def test_the_wording_says_often_discussed_in_relation_to():
    assert cards_content.CARD_DISCUSSED_LABEL == "Often discussed in relation to"
    for text_ in all_texts():
        assert not re.search(r"\bused for\b|\bhelps with\b", text_.lower())


# ---------------------------------------------------------------- the service

def test_a_card_comes_back_as_plain_data():
    card = get_ingredient_card("retinol")
    assert card == {
        "key": "retinol", "checked": "2026-11-13",
        "what": {"text": "A form of vitamin A, found in animal liver and whole milk.",
                 "source_name": "MedlinePlus: Vitamin A", "source_url": "https://medlineplus.gov/ency/article/002400.htm"},
        "discussed": {"topics": ["uneven skin tone", "pigmentation", "texture"], "context": None,
                      "source_name": "American Academy of Dermatology: Retinoid or retinol?",
                      "source_url": "https://www.aad.org/public/everyday-care/skin-care-secrets/anti-aging/retinoid-retinol"},
    }


@pytest.mark.parametrize("term, key", [
    ("niacinamide", "niacinamide"), ("Nicotinamide", "niacinamide"), ("  NIACINAMIDE ", "niacinamide"),
    ("retinol", "retinol"), ("retinal", "retinal"), ("Retinaldehyde", "retinal"),
    ("vitamin C", "vitamin c"), ("ascorbic acid", "vitamin c"), ("hyaluronic acid", "hyaluronic acid"),
    ("Hyaluronan", "hyaluronic acid"), ("salicylic acid", "salicylic acid"), ("ceramides", "ceramides"),
    ("ceramide", "ceramides"),
])
def test_names_and_aliases_find_the_card(term, key):
    assert get_ingredient_card(term)["key"] == key


@pytest.mark.parametrize("term", ["bakuchiol", "retinoic acid", "vitamin", "niacin", "a", "", None, '"retinol"', "retinol[ti]",
                                  "x" * 61, "retinol or niacinamide"])
def test_an_ingredient_without_a_card_or_with_unusable_text_gets_none(term):
    assert get_ingredient_card(term) is None


def test_a_line_left_out_of_the_content_file_comes_back_as_none(monkeypatch):
    monkeypatch.setitem(cards_content.CARDS[1], "discussed", None)
    card = get_ingredient_card("retinol")
    assert card["discussed"] is None and card["what"]["text"].startswith("A form of vitamin A")
    monkeypatch.setitem(cards_content.CARDS[1], "what", None)
    assert get_ingredient_card("retinol") is None                       # no line, no card


def test_the_service_makes_no_call(pubmed_api):
    for name in NAMES:
        get_ingredient_card(name)
    assert pubmed_api.calls == []


def test_the_returned_topics_are_a_copy():
    get_ingredient_card("retinol")["discussed"]["topics"].append("x")
    assert get_ingredient_card("retinol")["discussed"]["topics"] == ["uneven skin tone", "pigmentation", "texture"]


# ---------------------------------------------------------------- the page

@pytest.mark.parametrize("name", NAMES)
def test_the_box_shows_the_card_with_its_sources_and_the_note(client, pubmed_api, name):
    papers(pubmed_api)
    html = page(client, f"/science?q={name}")
    kind, body = box(html)
    assert kind == "card" and text(body) == EXPECTED_BOX[name]


@pytest.mark.parametrize("name", NAMES)
def test_a_card_makes_no_pubmed_count_calls(client, pubmed_api, name):
    papers(pubmed_api)
    page(client, f"/science?q={name}")
    assert pubmed_api.count_queries() == [] and len(pubmed_api.calls) == 2      # the papers only: esearch and esummary


def test_the_topic_paper_counts_are_not_in_the_card_box(client, pubmed_api):
    papers(pubmed_api)
    pubmed_api.counts = {"niacinamide": 999}
    _kind, body = box(page(client, "/science?q=niacinamide"))
    assert "999" not in body and not re.search(r"\d+ papers?", text(body)) and "Often mentioned together with" not in body
    assert "These numbers show how often topics appear" not in body


def test_each_source_is_a_link_that_opens_safely(client, pubmed_api):
    papers(pubmed_api)
    _kind, body = box(page(client, "/science?q=retinol"))
    assert re.findall(r'<a href="([^"]+)" rel="noopener">(.*?)</a>', body) == [
        ("https://medlineplus.gov/ency/article/002400.htm", "MedlinePlus: Vitamin A"),
        ("https://www.aad.org/public/everyday-care/skin-care-secrets/anti-aging/retinoid-retinol",
         "American Academy of Dermatology: Retinoid or retinol?"),
    ]


def test_the_note_appears_once_and_the_box_sits_above_the_papers(client, pubmed_api):
    papers(pubmed_api)
    html = page(client, "/science?q=vitamin+C")
    assert text(html).count(NOTE) == 1
    assert html.index('id="labels-line"') < html.index('id="glance"') < html.index("paper-group-title")


def test_the_card_shows_for_a_quick_link_search(client, pubmed_api):
    papers(pubmed_api)
    link = re.findall(r'<a class="btn-ghost" href="([^"]+)">vitamin C</a>', page(client, "/science"))[0].replace("&amp;", "&")
    assert box(page(client, link))[0] == "card"


def test_the_card_shows_with_the_reviews_only_box_ticked(client, pubmed_api):
    pubmed_api.add(1, "A review", types=("Review",))
    assert box(page(client, "/science?q=retinol&reviews=1"))[0] == "card"


def test_the_card_shows_for_an_alias_search(client, pubmed_api):
    papers(pubmed_api)
    kind, body = box(page(client, "/science?q=ascorbic+acid"))
    assert kind == "card" and "water-soluble vitamin" in text(body)


def test_the_card_still_shows_when_pubmed_is_down_and_an_old_copy_is_listed(client, pubmed_api, app):
    from contextlib import closing
    from database.db import get_db
    papers(pubmed_api)
    page(client, "/science?q=retinol")
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        conn.execute("UPDATE pubmed_searches SET fetched_at = '2026-01-05T09:30:00+00:00'")
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/science?q=retinol")
    assert "saved results from 5 Jan 2026" in text(html) and box(html)[0] == "card"


def test_no_box_when_a_carded_ingredient_has_no_papers(client, pubmed_api):
    html = page(client, "/science?q=retinol")                                   # nothing to list
    assert box(html) is None and "At a glance" not in html and NOTE not in text(html)


def test_no_box_when_pubmed_is_down_and_nothing_is_saved(client, pubmed_api):
    pubmed_api.error["esearch"] = requests.Timeout("slow")
    html = page(client, "/science?q=retinol")
    assert box(html) is None and "At a glance" not in html


# ---------------------------------------------------------------- ingredients without a card

TOPICS = ["acne", "hyperpigmentation", "skin aging", "skin barrier", "irritation", "rosacea", "eczema"]


def test_an_ingredient_without_a_card_gets_the_counts_box_when_counts_are_available(client, pubmed_api):
    papers(pubmed_api)
    pubmed_api.counts = {f'"{t}"': n for t, n in zip(TOPICS, (9, 8, 0, 0, 0, 0, 0))}
    kind, body = box(page(client, "/science?q=bakuchiol"))
    assert kind == "counts"
    assert text(body).startswith("At a glance Often mentioned together with acne 9 papers hyperpigmentation 8 papers")
    assert "What it is" not in body and NOTE not in text(body)
    assert len(pubmed_api.count_queries()) == len(TOPICS)


def test_an_ingredient_without_a_card_and_without_counts_has_no_box(client, pubmed_api):
    papers(pubmed_api)
    pubmed_api.counts = {f'"{t}"': 0 for t in TOPICS}
    html = page(client, "/science?q=bakuchiol")
    assert box(html) is None and "At a glance" not in html and "paper-card" in html


def test_an_ingredient_without_a_card_and_failing_counts_has_no_box(client, pubmed_api):
    papers(pubmed_api)
    for topic in TOPICS:
        pubmed_api.count_error[f'"{topic}"'] = requests.Timeout("slow")
    assert box(page(client, "/science?q=bakuchiol")) is None


def test_a_blank_search_has_no_box_and_no_calls(client, pubmed_api):
    assert box(page(client, "/science")) is None and pubmed_api.calls == []


# ---------------------------------------------------------------- wording on the whole page

@pytest.mark.parametrize("name", NAMES)
def test_the_page_with_a_card_uses_none_of_the_banned_words_in_our_text(client, pubmed_api, name):
    papers(pubmed_api)
    html = page(client, f"/science?q={name}")
    ours = text(re.sub(r'<ul class="paper-list">.*?</ul>', "", html, flags=re.S)).lower()
    for word in ["safe", "best for", "treats", "cures", "proven", "effective", "helps"]:
        assert not re.search(rf"\b{re.escape(word)}", ours), (name, word)


def test_the_topic_words_are_only_in_the_content_files_and_the_tests():
    import pathlib
    for name in ("templates/science.html", "app.py", "database/services.py", "live/pubmed.py"):
        source = pathlib.Path(name).read_text(encoding="utf-8").lower()
        for word in ("eczema", "acne", "wound healing", "fine lines", "pigmentation"):
            assert word not in source, (name, word)
