"""Compare: the name-word type rule, the services, the one Compare page (both modes), the fixed texts and the MCP tool."""
import asyncio
import re
from contextlib import closing
from datetime import date

import pytest

from content import product_types as pt
from database import services
from database.db import get_db
from database.type_match import name_has_word, split_by_types

TODAY = date.today().isoformat()

# Our own wording must never use these (paper titles and product names are the source's own text)
BANNED = re.compile(
    r"\b(safe|free of|best|recommend\w*|suitable|good for|treats|cures|proven|effective|dupe|"
    r"better|worse|cheaper|cheapest|winner|bestseller)\b|for your skin|skin type", re.I)

LEFT_OUT_LINE = "Products whose names contain both words are left out of this comparison, {n} products."
SIZES_LINE = ("The two types have different numbers of products, so compare the shares and "
              "averages, not the totals.")
CLEANSERS = "Face Wash & Cleansers"


def add(db, name, group="Moisturizers", price=20.0, rating=None, reviews=None, ingredients=()):
    with closing(get_db(db)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group,"
            " rating, reviews) VALUES (?, 'Dew Labs', ?, ?, '50 mL', ?, ?, ?, ?)",
            (name, group, price, price / 50, group, rating, reviews),
        ).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return pid


def save_rate(db, rate=90.0):
    with closing(get_db(db)) as conn, conn:
        conn.execute("INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                     " VALUES (?, 'USD', 'INR', ?, ?)", (TODAY, rate, TODAY))


@pytest.fixture
def market(app):
    """Moisturizers: 21 cream-only, 20 gel-only, 3 gel-cream (both words), 2 plain. Two Toners and
    two BB & CC Creams (no type pair)."""
    db = app.config["DATABASE"]
    for i in range(21):
        add(db, f"Rich Cream {i}", price=10.0 + i, rating=4.0, reviews=10,
            ingredients=["Water", "Glycerin", "Dimethicone"])
    for i in range(20):
        add(db, f"Water GEL {i}", price=30.0 + i, rating=5.0, reviews=30, ingredients=["Aqua", "Glycerin", "Citric Acid"])
    for i in range(3):
        add(db, f"Gel-Cream {i}", ingredients=["Water", "Glycerin"])
    add(db, "Plain Lotion")
    add(db, "Creme Brulee Moisturizer")        # "creme" is not "cream"
    add(db, "Toner One", group="Toners")
    add(db, "Toner Two", group="Toners")
    add(db, "Tint One", group="BB & CC Creams", ingredients=["Water", "Glycerin"])
    add(db, "Tint Two", group="BB & CC Creams", ingredients=["Water", "Niacinamide"])
    return db


@pytest.fixture
def cleansers(app):
    """Face Wash & Cleansers: 16 gel, 15 oil ("oil-free" and "oil control" names do not count), 14 foam, 3 gel-oil."""
    db = app.config["DATABASE"]
    for i in range(16):
        add(db, f"Clear Gel Cleanser {i}", group=CLEANSERS, price=10.0 + i, ingredients=["Water", "Glycerin"])
    for i in range(15):
        add(db, f"Cleansing Oil {i}", group=CLEANSERS, price=20.0 + i, ingredients=["Water", "Squalane"])
    for i in range(14):
        add(db, f"Soft Foam {i}", group=CLEANSERS, ingredients=["Water"])
    for i in range(6):
        add(db, f"Oil-Free Wash {i}", group=CLEANSERS)
        add(db, f"Oil Control Wash {i}", group=CLEANSERS)
    for i in range(3):
        add(db, f"Gel Oil Duo {i}", group=CLEANSERS)
    return db


# ---- the name-word rule ------------------------------------------------------------------------ #

@pytest.mark.parametrize("name, word, expected", [
    ("Rich Cream", "cream", True),
    ("RICH CREAM", "cream", True),
    ("Gel-Cream Moisturizer", "cream", True),       # a hyphen splits words
    ("Gel-Cream Moisturizer", "gel", True),
    ("Gel/Cream", "gel", True),
    ("Creamy Lotion", "cream", False),              # no part of a longer word
    ("Moisturizing Creme", "cream", False),         # no other spelling
    ("Crème Légère", "cream", False),
    ("Sunscreen SPF 30", "cream", False),
    ("Gelatin Mask", "gel", False),
    ("Oil-Free Moisturizer", "oil", False),         # these phrases are not the word "oil"
    ("Oil Free Moisturizer", "oil", False),
    ("Oil-Control Gel", "oil", False),
    ("OIL CONTROL Lotion", "oil", False),
    ("Oil-Free Face Oil", "oil", True),             # a real "oil" elsewhere in the name still counts
    ("Cleansing Oil", "oil", True),
    ("", "cream", False),
    (None, "cream", False),
])
def test_a_type_is_a_whole_word_in_the_name(name, word, expected):
    assert name_has_word(name, word) is expected


def test_a_name_with_both_words_is_on_neither_side():
    rows = [{"name": n} for n in ("Rich Cream", "Gel Cream", "Cool Gel", "Gel-Cream", "Plain Lotion")]
    only_a, only_b, both = split_by_types(rows, "cream", "gel")
    assert [r["name"] for r in only_a] == ["Rich Cream"]
    assert [r["name"] for r in only_b] == ["Cool Gel"]
    assert [r["name"] for r in both] == ["Gel Cream", "Gel-Cream"]


# ---- the services ------------------------------------------------------------------------------ #

def test_the_minimum_is_one_number_in_one_place():
    assert pt.TYPES_CONFIG["min_products"] == 15
    assert services.list_format_types.__doc__ and "usable pair" in services.list_format_types.__doc__


def test_the_listing_is_built_from_the_data_and_only_has_usable_pairs(market):
    listing = services.list_format_types(market)
    assert listing["min_products"] == 15
    [group] = listing["groups"]                       # not Toners, not BB & CC Creams
    assert group["name"] == "Moisturizers"
    assert [t["key"] for t in group["types"]] == ["cream", "gel"]
    assert group["pairs"] == [{"a": "cream", "b": "gel", "a_products": 21, "b_products": 20, "left_out": 3}]


def test_cleansers_list_the_pairs_that_have_enough_products_after_the_left_out_ones(cleansers):
    [group] = services.list_format_types(cleansers)["groups"]
    assert group["name"] == CLEANSERS
    pairs = {(p["a"], p["b"]): (p["a_products"], p["b_products"]) for p in group["pairs"]}
    assert pairs == {("gel", "oil"): (16, 15)}        # foam has 14: too few; "oil-free" and "oil control" are not oil
    assert [t["key"] for t in group["types"]] == ["gel", "oil"]


def test_a_type_with_too_few_products_is_never_listed(app):
    db = app.config["DATABASE"]
    for i in range(30):
        add(db, f"Cream {i}")
    for i in range(14):
        add(db, f"Gel {i}")
    assert services.list_format_types(db)["groups"] == []


def test_compare_types_returns_plain_numbers(market):
    r = services.compare_types("Moisturizers", "cream", "gel", market)
    assert r["status"] == "ok" and r["left_out"] == {"products": 3, "words": ["cream", "gel"]}
    assert (r["a"]["products"], r["b"]["products"]) == (21, 20)
    assert r["a"]["price"] == {"min": 10.0, "max": 30.0, "products": 21}          # no median
    assert r["b"]["price"] == {"min": 30.0, "max": 49.0, "products": 20}
    assert r["a"]["rating"] == 4.0 and r["b"]["rating"] == 5.0
    assert r["a"]["rated_products"] == 21
    top = {i["name"]: i for i in r["a"]["ingredients"]["top"]}
    assert top["Glycerin"]["products"] == 21 and top["Glycerin"]["share_percent"] == 100.0
    assert "Water" not in top and r["a"]["ingredients"]["water"] == {"products": 21, "share_percent": 100.0}
    assert r["a"]["format_line"]["source_name"] == pt.AAD_EMOLLIENTS["name"]
    assert r["b"]["format_line"]["source_url"] == pt.AAD_EMOLLIENTS["url"]


def test_a_cleanser_pair_has_data_and_no_format_line(cleansers):
    r = services.compare_types(CLEANSERS, "gel", "oil", cleansers)
    assert r["status"] == "ok" and (r["a"]["products"], r["b"]["products"]) == (16, 15)
    assert r["left_out"]["products"] == 3
    assert r["a"]["price"]["min"] and r["b"]["ingredients"]["top"][0]["name"] in ("Squalane", "Glycerin")
    assert r["a"]["format_line"] is None and r["b"]["format_line"] is None


def test_the_format_lines_only_exist_for_cream_and_gel_in_moisturizers():
    assert set(pt.FORMAT_LINES) == {("Moisturizers", "cream"), ("Moisturizers", "gel")}


def test_a_missing_price_or_rating_is_skipped_never_counted_as_zero(app):
    db = app.config["DATABASE"]
    for i in range(20):
        add(db, f"Cream {i}", price=10.0, rating=None, reviews=None)
        add(db, f"Gel {i}", price=20.0, rating=4.0, reviews=5)
    with closing(get_db(db)) as conn, conn:
        conn.execute("UPDATE products SET price = NULL WHERE name = 'Cream 0'")
    r = services.compare_types("Moisturizers", "cream", "gel", db)
    assert r["a"]["products"] == 20 and r["a"]["price"]["products"] == 19 and r["a"]["price"]["min"] == 10.0
    assert r["a"]["rating"] is None and r["a"]["rated_products"] == 0 and r["b"]["rating"] == 4.0


def test_too_few_products_gives_counts_only(app):
    db = app.config["DATABASE"]
    for i in range(25):
        add(db, f"Cream {i}")
    for i in range(14):
        add(db, f"Gel {i}")
    r = services.compare_types("Moisturizers", "cream", "gel", db)
    assert r["status"] == "too_few" and (r["a"]["products"], r["b"]["products"]) == (25, 14)
    assert "price" not in r["a"] and "ingredients" not in r["b"]


@pytest.mark.parametrize("args, status", [
    (("Moisturizers", "", "gel"), "waiting"),
    (("Moisturizers", "cream", ""), "waiting"),
    (("Moisturizers", "cream", "cream"), "same_type"),
    (("Moisturizers", "cream", "nonsense"), "unknown"),
    (("Toners", "cream", "gel"), "too_few"),
    (("Nope", "cream", "gel"), "unknown"),
    (("Moisturizers' OR 1=1 --", "cream", "gel"), "unknown"),
])
def test_unusable_input_is_a_status_not_an_error(market, args, status):
    assert services.compare_types(*args, market)["status"] == status


# ---- the one Compare page ---------------------------------------------------------------------- #

def page(client, url="/compare"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    import html as html_lib
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def select_options(html, name):
    body = re.search(rf'<select[^>]*name="{name}"[^>]*>(.*?)</select>', html, re.S)
    return None if not body else [(v, text(label)) for v, label in re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', body.group(1), re.S)]


def test_there_are_no_tabs_and_the_old_types_page_redirects(client):
    assert "tabs" not in page(client) and "Compare types" not in page(client)
    response = client.get("/compare/types")
    assert response.status_code == 301 and response.headers["Location"].endswith("/compare")
    assert not response.headers["Location"].endswith("/types")
    response = client.get("/compare/types?group=Moisturizers&a=cream&b=gel&junk=1")
    assert response.headers["Location"].split("/compare")[1].startswith("?")
    assert "mode=types" in response.headers["Location"] and "group=Moisturizers" in response.headers["Location"]
    assert "junk" not in response.headers["Location"]


def test_after_a_category_the_page_asks_what_to_compare_with_two_big_cards(client, market):
    html = page(client, "/compare?group=Moisturizers")
    body = text(html)
    assert "What do you want to compare?" in body
    cards = re.findall(r'<a class="mode-card" href="([^"]+)">(.*?)</a>', html, re.S)
    assert [text(c) for _, c in cards] == [
        "Two specific products For example, two serums from different brands.",
        "Two product types For example, cream vs gel moisturizers."]
    assert [h for h, _ in cards] == ["/compare?mode=products&amp;group=Moisturizers",
                                     "/compare?mode=types&amp;group=Moisturizers"]
    assert select_options(html, "a") is None and select_options(html, "ingredient") is None   # the choice comes first
    assert "What do you want to compare?" not in text(page(client, "/compare"))               # no category yet


def test_a_category_without_a_usable_type_pair_still_offers_specific_products_and_no_dead_end(client, market):
    html = page(client, "/compare?group=Toners")
    assert 'href="/compare?mode=products&amp;group=Toners"' in html
    assert "mode=types" not in html and 'class="mode-card is-off"' in html
    assert "no pair of types has enough products" in text(html)


# -- two specific products ---------------------------------------------------------------------- #

def test_bb_and_cc_creams_appears_and_two_of_its_products_can_be_compared(client, market):
    html = page(client, "/compare")
    assert "BB &amp; CC Creams (2)" in html
    html = page(client, "/compare?group=BB+%26+CC+Creams&mode=products")
    options = select_options(html, "a")
    assert [label for v, label in options if v] == ["Dew Labs - Tint One (50 mL, $20.00)", "Dew Labs - Tint Two (50 mL, $20.00)"]
    a, b = (v for v, _ in options if v)
    body = text(page(client, f"/compare?group=BB+%26+CC+Creams&mode=products&a={a}&b={b}"))
    assert "Tint One" in body and "Tint Two" in body and "Ingredients both have" in body
    assert "nothing to compare" not in body


def test_narrowing_by_main_ingredient_is_optional(client, market):
    html = page(client, "/compare?group=BB+%26+CC+Creams&mode=products")
    ingredient = select_options(html, "ingredient")
    assert ingredient[0] == ("", "Any") and "Optional" not in html and "(optional)" in html
    assert ingredient[1:] == []                                       # niacinamide has only 1 product: not listed
    assert len(select_options(html, "a")) == 3                        # "Choose a product" and both products
    html = page(client, "/compare?group=Moisturizers&mode=products")
    assert len(select_options(html, "a")) == 1 + 21 + 20 + 3 + 2      # every product of the category
    assert select_options(html, "ingredient") == [("", "Any")]


def test_no_category_with_two_or_more_products_says_there_is_nothing_to_compare(client, market, cleansers):
    import html as html_lib
    categories = [html_lib.unescape(v) for v, _ in select_options(page(client), "group") if v]
    assert set(categories) >= {"Moisturizers", "Toners", "BB & CC Creams", CLEANSERS}
    for category in categories:
        for url in (f"/compare?group={category}", f"/compare?group={category}&mode=products",
                    f"/compare?group={category}&mode=types"):
            from urllib.parse import quote
            html = page(client, url.replace(category, quote(category)))
            assert "nothing to compare" not in html and "no main ingredient group" not in html, url


# -- two product types -------------------------------------------------------------------------- #

def test_the_type_pickers_only_list_types_that_lead_to_a_result(client, market, cleansers):
    html = page(client, "/compare?mode=types&group=Moisturizers")
    assert select_options(html, "a") == [("", "Choose a type"), ("cream", "Cream"), ("gel", "Gel")]
    assert select_options(html, "b") is None
    html = page(client, "/compare?mode=types&group=Moisturizers&a=cream")
    assert select_options(html, "b") == [("", "Choose a type"), ("gel", "Gel (20 products)")]    # no "cream", no lotion
    html = page(client, f"/compare?mode=types&group={'Face+Wash+%26+Cleansers'}")
    assert select_options(html, "a") == [("", "Choose a type"), ("gel", "Gel"), ("oil", "Oil")]   # foam: too few
    html = page(client, f"/compare?mode=types&group={'Face+Wash+%26+Cleansers'}&a=gel")
    assert select_options(html, "b") == [("", "Choose a type"), ("oil", "Oil (15 products)")]


def test_the_result_shows_big_counts_the_left_out_line_and_the_sizes_line(client, market):
    save_rate(market)
    html = page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel")
    body = text(html)
    assert '<p class="type-count"><strong>21 products</strong></p>' in html
    assert '<p class="type-count"><strong>20 products</strong></p>' in html
    assert LEFT_OUT_LINE.format(n=3) in body
    assert SIZES_LINE in body
    assert html.index("type-count") < html.index("type-left-out") < html.index("type-sizes")   # under the result
    assert "≈ ₹900 to ₹2,700" in body                                 # the cream price range, $10 to $30 at 90
    assert "Price range" in body and "Average rating" in body and "Most common ingredients" in body
    assert "median" not in body.lower() and "Typical price" not in body
    assert "Water is in 100% of these products" in body


def test_a_cleanser_pair_shows_data_only_with_no_format_description(client, cleansers):
    html = page(client, "/compare?mode=types&group=Face+Wash+%26+Cleansers&a=gel&b=oil")
    body = text(html)
    assert '<p class="type-count"><strong>16 products</strong></p>' in html
    assert '<p class="type-count"><strong>15 products</strong></p>' in html
    assert LEFT_OUT_LINE.format(n=3) in body and SIZES_LINE in body
    assert body.count(pt.NO_FORMAT_LINE) == 2
    assert "Thicker than a lotion" not in body and "aad.org" not in html
    assert "Price range" in body and "Squalane" in body and "median" not in body.lower()


def test_one_left_out_product_reads_as_singular(client, app):
    db = app.config["DATABASE"]
    for i in range(15):
        add(db, f"Cream {i}")
        add(db, f"Gel {i}")
    add(db, "Gel Cream")
    assert "are left out of this comparison, 1 product." in text(page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel"))


def test_equal_sizes_leave_out_the_sizes_line(client, app):
    db = app.config["DATABASE"]
    for i in range(15):
        add(db, f"Cream {i}")
        add(db, f"Gel {i}")
    assert SIZES_LINE not in text(page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel"))


def test_the_format_lines_have_their_named_source_link_and_the_not_medical_note(client, market):
    html = page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel")
    body = text(html)
    assert "Thicker than a lotion or a gel, with a higher oil content." in body
    assert "Often water-based, and tends to feel lighter on the skin than a lotion." in body
    assert html.count('href="https://www.aad.org/public/everyday-care/skin-care-basics/dry/pick-moisturizer" rel="noopener"') == 2
    assert "American Academy of Dermatology: Emollient options" in body
    assert "General information from the sources named. Not medical advice." in body
    assert "Patch-test new products and see a dermatologist with any concern." in body
    assert "not tested formulations" in body and "Creme" in body and "oil-free" in body


def test_a_link_with_an_unusable_choice_gets_a_friendly_line_that_names_what_works(client, market, cleansers):
    urls = ["/compare?mode=types&group=Toners",                                # no type pair in this category
            "/compare?mode=types&group=Nope&a=cream&b=gel",                    # unknown category
            "/compare?mode=types&group=Moisturizers&a=lotion&b=gel",           # a word that is not offered
            "/compare?mode=types&group=Moisturizers&a=cream&b=cream",
            "/compare?mode=types&group=Face+Wash+%26+Cleansers&a=gel&b=foam"]  # foam has too few products
    for url in urls:
        html = page(client, url)
        assert 'class="gentle-note"' in html and 'class="notice"' not in html, url
        note = text(re.search(r'<p class="gentle-note">(.*?)</p>', html, re.S).group(1))
        assert "Face Wash & Cleansers and Moisturizers" in note, url
        assert "<script>" not in html
    assert "Toners has no pair of types with at least 15 products each" in text(page(client, urls[0]))


def test_bad_arguments_never_break_the_page(client, market):
    for url in ("/compare?mode=types&group=%3Cscript%3E&a=x&b=y", "/compare?mode=types&a=cream&b=gel",
                "/compare?mode=types&group=Moisturizers&a=cream&b=gel&a=gel", "/compare?mode=bogus&group=Moisturizers",
                "/compare?mode=products&a=cream&b=gel"):
        response = client.get(url)
        assert response.status_code == 200
        assert "<script>" not in response.get_data(as_text=True)


def test_without_a_rate_prices_are_in_dollars_with_a_note(client, market):
    body = text(page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel"))
    assert "Rupee prices are not available right now, so US dollar prices are shown." in body
    assert "$10.00 to $30.00" in body and "₹" not in body


# ---- the fixed texts and the banned wording -------------------------------------------------- #

def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from all_strings(k)
            yield from all_strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from all_strings(v)


def test_the_content_file_has_no_banned_wording_and_every_line_has_a_source():
    for name in [n for n in dir(pt) if n.isupper()]:
        for s in all_strings(getattr(pt, name)):
            if s.startswith("http"):
                continue
            assert not BANNED.search(s), f"{name}: {s}"
    for line in pt.FORMAT_LINES.values():
        assert line["source"]["name"] and line["source"]["url"].startswith("https://") and line["checked"]


def test_the_type_words_are_forms_not_purposes_or_ingredients():
    assert pt.TYPE_WORDS == ["cream", "gel", "lotion", "oil", "balm", "foam", "serum", "mask", "mist", "spray",
                             "stick", "powder", "butter", "milk", "essence"]
    assert pt.NOT_A_TYPE_PHRASES == ["oil-free", "oil free", "oil-control", "oil control"]


def test_the_format_lines_and_page_lines_are_pinned():
    assert pt.FORMAT_LINES[("Moisturizers", "cream")]["text"] == "Thicker than a lotion or a gel, with a higher oil content."
    assert pt.FORMAT_LINES[("Moisturizers", "gel")]["text"] == \
        "Often water-based, and tends to feel lighter on the skin than a lotion."
    assert pt.LEFT_OUT.format(n=19, products="products") == LEFT_OUT_LINE.format(n=19)
    assert pt.DIFFERENT_SIZES == SIZES_LINE
    assert pt.MODE_QUESTION == "What do you want to compare?"
    assert pt.MODES["products"]["title"] == "Two specific products" and pt.MODES["types"]["title"] == "Two product types"


def test_the_whole_page_has_no_banned_wording_in_either_mode(client, market, cleansers):
    for url in ("/compare", "/compare?group=Moisturizers", "/compare?group=Toners&mode=types",
                "/compare?mode=products&group=BB+%26+CC+Creams",
                "/compare?mode=types&group=Moisturizers", "/compare?mode=types&group=Moisturizers&a=cream&b=gel",
                "/compare?mode=types&group=Face+Wash+%26+Cleansers&a=gel&b=oil"):
        html = page(client, url)
        main = html.split('<section class="compare-page">', 1)[1].split("</section>", 1)[0]
        assert not BANNED.search(text(main)), url


# ---- the MCP tool ----------------------------------------------------------------------------- #

@pytest.fixture
def mcp(market, monkeypatch):
    monkeypatch.setenv("SKIN_INDEX_DB", market)
    from mcp_server import server
    return server


def test_the_mcp_tool_exists_is_read_only_and_has_no_banned_wording(mcp):
    tools = {t.name: t for t in asyncio.run(mcp.mcp.list_tools())}
    tool = tools["compare_types"]
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert not BANNED.search(tool.description)
    for prop, schema in tool.inputSchema["properties"].items():
        assert schema.get("description") and not BANNED.search(schema["description"]), prop


def test_the_mcp_tool_returns_the_same_numbers_as_the_page(mcp, market):
    answer = mcp.compare_types("Moisturizers", "cream", "gel")
    data = answer["data"]
    assert answer["source"].startswith("Skin Index database") and data["status"] == "ok"
    assert (data["a"]["products"], data["b"]["products"]) == (21, 20)
    assert data["left_out"] == {"products": 3, "words": ["cream", "gel"]}
    assert data["a"]["price_usd"] == {"min": 10.0, "max": 30.0}
    assert "median" not in str(answer).lower()
    assert data["a"]["products_path"] == "/products?category=Moisturizers&type=cream&vs=gel"
    assert data["b"]["products_path"] == "/products?category=Moisturizers&type=gel&vs=cream"
    assert data["b"]["average_rating"] == 5.0
    assert data["a"]["format_line"]["source_name"] == pt.AAD_EMOLLIENTS["name"]
    assert [i["name"] for i in data["a"]["most_common_ingredients"]] == ["Dimethicone", "Glycerin"]   # tied: by name
    assert "different numbers of products" in answer["note"] and "Not medical advice" in answer["note"]
    assert not BANNED.search(answer["note"])


def test_the_mcp_tool_works_for_a_cleanser_pair_with_data_only(app, cleansers, monkeypatch):
    monkeypatch.setenv("SKIN_INDEX_DB", cleansers)
    from mcp_server import server
    data = server.compare_types(CLEANSERS, "Gel", "oil")["data"]            # a type word is read ignoring capital letters
    assert data["status"] == "ok" and (data["a"]["products"], data["b"]["products"]) == (16, 15)
    assert data["a"]["format_line"] is None and data["b"]["format_line"] is None


def test_the_mcp_tool_returns_a_plain_status_with_the_valid_choices(mcp):
    for args, status in (((), "waiting"), (("Moisturizers",), "waiting"), (("Moisturizers", "cream", "cream"), "same_type"),
                         (("Moisturizers", "x", "y"), "unknown"), (("Nope", "cream", "gel"), "unknown")):
        answer = mcp.compare_types(*args)
        data = answer["data"]
        assert "error" not in answer and data["status"] == status, args
        assert data["minimum_products"] == 15
        assert data["valid_choices"] == [{"group": "Moisturizers", "types": ["cream", "gel"],
                                          "pairs": [{"a": "cream", "b": "gel", "a_products": 21, "b_products": 20, "left_out": 3}]}]
        assert not BANNED.search(data["message"])
    assert mcp.compare_types(5, "cream", "gel") == {"error": "group must be text."}


def test_the_mcp_tool_gives_counts_and_the_valid_choices_when_a_side_is_too_small(mcp):
    data = mcp.compare_types("Toners", "cream", "gel")["data"]
    assert data["status"] == "too_few" and "price_usd" not in data["a"]
    assert (data["a"]["products"], data["b"]["products"]) == (0, 0)
    assert "fewer than the 15 needed" in data["message"] and data["valid_choices"]
    assert not BANNED.search(data["message"])


def test_the_mcp_message_uses_the_singular_for_one_product(app, monkeypatch):
    db = app.config["DATABASE"]
    monkeypatch.setenv("SKIN_INDEX_DB", db)
    for i in range(25):
        add(db, f"Cream {i}")
    add(db, "Gel 1")
    from mcp_server import server
    data = server.compare_types("Moisturizers", "cream", "gel")["data"]
    assert data["status"] == "too_few" and "Gel has 1 product in Moisturizers" in data["message"]


# ---- no median anywhere ------------------------------------------------------------------------ #

def test_no_median_in_the_content_the_templates_or_the_mcp_text():
    from pathlib import Path
    from content import mcp_text
    root = Path(__file__).resolve().parent.parent
    for path in (root / "templates" / "_compare_types_result.html", root / "content" / "product_types.py",
                 root / "content" / "mcp_text.py", root / "mcp_server" / "server.py"):
        assert "median" not in path.read_text(encoding="utf-8").lower(), path.name
    assert "median" not in mcp_text.NOTES["compare_types"].lower()


# ---- the "See all N products" link and the Products page type filter --------------------------- #

def product_total(html):
    return int(re.search(r'<p class="results-count">([\d,]+) products?', html).group(1).replace(",", ""))


def test_each_column_links_to_the_products_page_with_exactly_its_products(client, market):
    html = page(client, "/compare?mode=types&group=Moisturizers&a=cream&b=gel")
    links = re.findall(r'<a class="btn-ghost" href="([^"]+)">(See all [\d,]+ products?)</a>', html)
    assert [(h.replace("&amp;", "&"), t) for h, t in links] == [
        ("/products?category=Moisturizers&type=cream&vs=gel", "See all 21 products"),
        ("/products?category=Moisturizers&type=gel&vs=cream", "See all 20 products")]


def test_the_count_on_the_link_is_the_count_on_the_filtered_list(client, market, cleansers):
    for url in ("/compare?mode=types&group=Moisturizers&a=cream&b=gel",
                "/compare?mode=types&group=Face+Wash+%26+Cleansers&a=gel&b=oil"):
        html = page(client, url)
        for href, n in re.findall(r'<a class="btn-ghost" href="([^"]+)">See all ([\d,]+) products?</a>', html):
            assert product_total(page(client, href.replace("&amp;", "&"))) == int(n.replace(",", "")), href


def test_the_filter_is_a_whole_word_match_that_leaves_out_names_with_both_words(client, market):
    html = page(client, "/products?category=Moisturizers&type=gel&vs=cream")
    assert product_total(html) == 20 and "Water GEL 0" in html and "Gel-Cream 0" not in html
    assert "Rich Cream" not in html and "Creme Brulee" not in html and "Plain Lotion" not in html
    # a plain text search for "gel" finds the left-out names too: a different number, which is why the filter exists
    assert product_total(page(client, "/products?category=Moisturizers&q=gel")) == 23


def test_the_active_filter_is_a_removable_chip(client, market):
    html = page(client, "/products?category=Moisturizers&type=gel&vs=cream&sort=price")
    chip = re.search(r'<a class="filter-chip" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
    assert text(chip.group(2)) == "Type: gel moisturizers"
    assert chip.group(1).replace("&amp;", "&") == "/products?category=Moisturizers&sort=price"   # removes only the type filter
    assert 'aria-label="Remove filter Type: gel moisturizers"' in html
    assert 'name="type" value="gel"' in html and 'name="vs" value="cream"' in html           # a new search keeps it
    assert product_total(page(client, chip.group(1).replace("&amp;", "&"))) == 21 + 20 + 3 + 2


def test_unusable_filter_values_are_ignored(client, market):
    for url in ("/products?category=Moisturizers&type=gel", "/products?category=Moisturizers&type=gel&vs=gel",
                "/products?category=Moisturizers&type=nonsense&vs=cream", "/products?type=gel&vs=cream",
                "/products?category=Nope&type=gel&vs=cream", "/products?category=Moisturizers&type=gel&vs=%3Cscript%3E"):
        html = page(client, url)
        assert "filter-chip" not in html and "<script>" not in html, url


def test_the_filter_works_with_paging_and_sorting(client, app):
    db = app.config["DATABASE"]
    for i in range(30):
        add(db, f"Cool Gel {i:02d}", price=50.0 - i)
    for i in range(5):
        add(db, f"Rich Cream {i}")
    first = page(client, "/products?category=Moisturizers&type=gel&vs=cream&sort=price")
    assert product_total(first) == 30 and "page 1 of 2" in first
    nxt = re.search(r'<a [^>]*href="([^"]+)"[^>]*>\s*Next', first, re.S).group(1).replace("&amp;", "&")
    assert "type=gel" in nxt and "vs=cream" in nxt and "sort=price" in nxt and "page=2" in nxt
    second = page(client, nxt)
    assert "page 2 of 2" in second and second.count("Cool Gel") == 6 and "filter-chip" in second
    assert second.index("Cool Gel 05") < second.index("Cool Gel 00") or "Cool Gel 05" not in second   # price order: low to high


def test_the_filter_works_with_the_avoid_list(client, app):
    db = app.config["DATABASE"]
    for i in range(3):
        add(db, f"Cool Gel {i}", ingredients=["Water", "Glycerin"])
    add(db, "Fragrant Gel", ingredients=["Water", "Parfum"])
    add(db, "Fragrant Cream", ingredients=["Water", "Parfum"])
    with closing(get_db(db)) as conn, conn:
        conn.execute("UPDATE products SET ingredients_text = 'Water, Glycerin' WHERE name LIKE 'Cool Gel%'")
        conn.execute("UPDATE products SET ingredients_text = 'Water, Parfum' WHERE name LIKE 'Fragrant%'")
    client.set_cookie("avoid_list", '%5B%22fragrance%22%5D')
    shown = page(client, "/products?category=Moisturizers&type=gel&vs=cream")
    assert product_total(shown) == 4 and "Lists:" in shown                       # the avoid list still tags rows
    hidden = page(client, "/products?category=Moisturizers&type=gel&vs=cream&hide=1")
    assert product_total(hidden) == 3 and "Fragrant Gel" not in hidden and "Fragrant Cream" not in hidden
    assert "filter-chip" in hidden


def test_the_detail_page_back_link_keeps_the_filter(client, market):
    html = page(client, "/products?category=Moisturizers&type=gel&vs=cream")
    detail = re.search(r'<a class="product-link" href="([^"]+)"', html).group(1).replace("&amp;", "&")
    assert "type=gel" in detail and "vs=cream" in detail
    back = re.search(r'href="(/products\?[^"]+)"', page(client, detail)).group(1).replace("&amp;", "&")
    assert back == "/products?category=Moisturizers&type=gel&vs=cream"


def test_the_filter_service_uses_the_comparison_rule(market):
    f = services.type_filter("Moisturizers", "gel", "cream", market)
    assert len(f["ids"]) == 20 and f["label"] == "gel moisturizers"
    assert services.type_filter("Moisturizers", "gel", "gel", market) is None
    assert services.type_filter("Nope", "gel", "cream", market) is None
    assert services.type_filter("Moisturizers", "gel", "x", market) is None
    assert len(services.type_filter("Moisturizers", "cream", "gel", market)["ids"]) == \
        services.compare_types("Moisturizers", "cream", "gel", market)["a"]["products"]


def test_the_products_page_with_a_filter_has_no_banned_wording(client, market):
    html = page(client, "/products?category=Moisturizers&type=gel&vs=cream")
    main = html.split('<section class="products-page">', 1)[1].split("</section>", 1)[0]
    assert "Type: gel moisturizers" in main
    assert not BANNED.search(text(re.sub(r'<table.*?</table>', "", main, flags=re.S)))
