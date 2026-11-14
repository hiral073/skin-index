"""Step 12c: the avoid list. Matching, the pages that show it, and that it is never kept."""
import json
import logging
import re
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest

from content import avoid_list as avoid_content
from database.db import get_db
from database.ingredient_match import ingredient_key, synonym_name, term_matches
from database.services import (
    check_avoid_list, check_product_avoid_list, clean_avoid_term, clean_avoid_terms, compare_products,
    split_ingredients_text,
)

ROOT = Path(__file__).resolve().parent.parent
PAGE_SIZE = 24


# ---------------------------------------------------------------- the words typed

@pytest.mark.parametrize("text, expected", [
    ("Fragrance", "fragrance"),
    ("  Cetyl   Alcohol ", "cetyl alcohol"),
    ("PEG-100", "peg-100"),
    ("Alcohol Denat.", "alcohol denat."),
    ("Citrus (Orange) Oil", "citrus (orange) oil"),
    ("Vitamin B3+", "vitamin b3+"),
    ("a/b", "a/b"),
    ("Crème", "crème"),
])
def test_clean_avoid_term_accepts_ordinary_ingredient_text(text, expected):
    assert clean_avoid_term(text) == expected


@pytest.mark.parametrize("text", [
    "", " ", "a", "x" * 41, "<b>fragrance</b>", "fragrance; DROP TABLE products", "a,b", "50%",
    "name.com", "www.example", "see https://x", "()", "..", "a_b", "tab\tin\nside\x00", None, 5, ["list"],
])
def test_clean_avoid_term_refuses_everything_else(text):
    assert clean_avoid_term(text) is None


def test_the_longest_allowed_word_is_40_characters():
    assert clean_avoid_term("x" * 40) == "x" * 40


def test_clean_avoid_terms_keeps_order_drops_repeats_and_caps_the_list_at_20():
    assert clean_avoid_terms(["Fragrance", "alcohol", "FRAGRANCE", "  alcohol  ", "bad<"]) == ["fragrance", "alcohol"]
    assert len(clean_avoid_terms([f"word{i}" for i in range(50)])) == avoid_content.MAX_TERMS == 20
    assert clean_avoid_terms([f"word{i}" for i in range(50)])[-1] == "word19"


def test_synonyms_count_as_a_repeat_in_the_list():
    assert clean_avoid_terms(["water", "aqua", "eau"]) == ["water"]
    assert clean_avoid_terms(["fragrance", "Parfum"]) == ["fragrance"]


@pytest.mark.parametrize("raw", [None, "fragrance", 5, {"a": "b"}])
def test_clean_avoid_terms_ignores_input_that_is_not_a_list_of_text(raw):
    assert clean_avoid_terms(raw) == []


# ---------------------------------------------------------------- matching

def found(term, *names):
    return check_avoid_list([term], list(names))["matches"]


def test_a_word_matches_whole_words_ignoring_case():
    result = found("alcohol", "Cetyl Alcohol", "ALCOHOL DENAT.", "alcohol")
    assert result == [{"term": "alcohol", "ingredients": ["Cetyl Alcohol", "ALCOHOL DENAT.", "alcohol"]}]


@pytest.mark.parametrize("term, name", [
    ("alcohol", "Alcoholic Extract"),         # a longer word
    ("alcohol", "Nonalcohol Base"),           # inside a word
    ("oil", "Coil Extract"), ("oil", "Oilseed Extract"),
    ("acid", "Acidic Complex"),
    ("peptide", "Tripeptide-1"), ("peptide", "Peptides"),     # no plural, no longer name
    ("glycerin", "Glycerine"), ("glycerin", "Glyceryl Stearate"),
    ("salicylic acid", "Salicylic"), ("salicylic acid", "Sodium Salicylate"),
    ("rose", "Primrose Oil"),
])
def test_no_partial_word_matches(term, name):
    assert found(term, name) == []


@pytest.mark.parametrize("term, name", [
    ("peg", "PEG-100 Stearate"),              # a hyphen ends a word
    ("stearate", "PEG-100 Stearate"),
    ("salicylic acid", "Salicylic Acid"),
    ("salicylic  acid", "salicylic acid"),    # extra spaces
    ("cetyl alcohol", "Cetyl   Alcohol"),
    ("orange", "Citrus Aurantium Dulcis (Orange) Peel Oil"),
    ("citrus (orange)", "Citrus (Orange) Oil"),
    ("vitamin c", "Vitamin C"),
])
def test_a_phrase_matches_the_same_words_in_the_same_order(term, name):
    assert len(found(term, name)) == 1


def test_the_words_of_a_phrase_must_be_next_to_each_other_in_order():
    assert found("acid salicylic", "Salicylic Acid") == []
    assert found("salicylic acid", "Salicylic Extract Acid") == []


@pytest.mark.parametrize("term, name", [
    ("fragrance", "Fragrance"), ("fragrance", "Parfum"), ("parfum", "Fragrance"),
    ("parfum", "Fragrance (Parfum)"), ("fragrance", "Parfum/Fragrance"), ("PARFUM", "fragrance"),
    ("fragrance", "Natural Fragrance"),       # the whole word is in the name
])
def test_fragrance_and_parfum_are_the_same_word(term, name):
    assert len(found(term, name)) == 1


@pytest.mark.parametrize("term, name", [
    ("water", "Water"), ("aqua", "Water"), ("eau", "Water"), ("water", "Aqua"), ("aqua", "Eau"),
    ("aqua", "Water (Aqua)"), ("water", "Rose Water"),     # whole words, so the word is found in a longer name
])
def test_water_aqua_and_eau_are_the_same_word(term, name):
    assert len(found(term, name)) == 1


@pytest.mark.parametrize("term, name", [
    ("perfume", "Parfum"), ("fragrances", "Fragrance"), ("scent", "Fragrance"),
    ("hyaluronic acid", "Sodium Hyaluronate"), ("vitamin c", "Ascorbic Acid"),
    ("retinol", "Retinal"), ("tocopherol", "Tocopheryl Acetate"), ("niacinamide", "Niacin"),
    ("water", "Watery Base"), ("aqua", "Aquaphor"),
])
def test_there_are_no_other_synonyms_and_no_similar_spellings(term, name):
    assert found(term, name) == []


def test_the_only_synonym_rules_are_water_aqua_eau_and_fragrance_parfum():
    from content.ingredient_words import SYNONYM_GROUPS
    assert SYNONYM_GROUPS == (("water", "aqua", "eau"), ("fragrance", "parfum"))
    assert synonym_name("Water (Aqua)") == "Water" and synonym_name("Fragrance (Parfum)") == "Fragrance"
    assert synonym_name("Purified Water") is None and synonym_name("Fragrance Mix") is None
    assert synonym_name("Water 2") is None and synonym_name("") is None and synonym_name(None) is None
    assert ingredient_key("  Aqua ") == ingredient_key("EAU") == "water"
    assert ingredient_key("Parfum") == ingredient_key("Fragrance") == "fragrance"
    assert ingredient_key("Glycerin") == "glycerin" != ingredient_key("Glycerine")


def test_special_characters_in_a_word_are_matched_literally():
    assert term_matches("c++", "Vitamin C++") is True
    assert term_matches("(orange)", "Citrus (Orange) Oil") is True
    assert term_matches("a+b", "AAB") is False


def test_matched_ingredient_names_are_returned_once_in_label_order():
    names = ["Water", "Cetyl Alcohol", "Fragrance (Parfum)", "Alcohol Denat.", "Cetyl Alcohol"]
    result = check_avoid_list(["parfum", "alcohol", "fragrance"], names)
    assert result["status"] == "found"
    assert result["terms"] == ["parfum", "alcohol"]            # fragrance repeats parfum
    assert result["matches"] == [
        {"term": "parfum", "ingredients": ["Fragrance (Parfum)"]},
        {"term": "alcohol", "ingredients": ["Cetyl Alcohol", "Alcohol Denat."]},
    ]
    assert result["lists"] == ["parfum", "alcohol"]
    assert result["matched_ingredients"] == ["Cetyl Alcohol", "Fragrance (Parfum)", "Alcohol Denat."]
    assert result["ingredients_checked"] == 5


def test_nothing_found_says_not_found_and_nothing_more():
    result = check_avoid_list(["fragrance"], ["Water", "Glycerin"])
    assert result["status"] == "not_found" and result["matches"] == [] and result["lists"] == []


@pytest.mark.parametrize("names", [[], None, [""], ["  "], [None, 5]])
def test_a_product_with_no_ingredients_is_never_clear(names):
    result = check_avoid_list(["fragrance"], names)
    assert result["status"] == "no_ingredients" and result["matches"] == [] and result["ingredients_checked"] == 0


@pytest.mark.parametrize("terms", [[], None, [""], ["<>"], "fragrance"])
def test_with_no_usable_list_nothing_is_checked(terms):
    assert check_avoid_list(terms, ["Fragrance"])["status"] == "no_list"


def test_split_ingredients_text():
    assert split_ingredients_text("Water, Glycerin, Fragrance (Parfum)") == ["Water", "Glycerin", "Fragrance (Parfum)"]
    assert split_ingredients_text("") == [] and split_ingredients_text(None) == []


def test_the_result_is_plain_data_that_can_become_json():
    result = check_avoid_list(["fragrance"], ["Fragrance"])
    assert json.loads(json.dumps(result)) == result


# ---------------------------------------------------------------- one product by id (for the MCP tool)

def add_product(db_path, name, ingredients, text="default", brand="Dew Labs", group="Face Serums"):
    """Insert a product; `ingredients` are names in label order; `text` overrides ingredients_text."""
    joined = ", ".join(ingredients) if text == "default" else text
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, compare_group, price, size_text, size_ml, price_per_ml,"
            " ingredients_text) VALUES (?, ?, ?, ?, 20, '50 mL', 50, 0.4, ?)",
            (name, brand, group, group, joined),
        ).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return pid


@pytest.fixture
def db_path(app):
    return app.config["DATABASE"]


def dump(db_path):
    with closing(get_db(db_path)) as conn:
        return list(conn.iterdump())


def test_check_product_avoid_list_returns_the_product_and_the_check(db_path):
    pid = add_product(db_path, "Rose Serum", ["Water", "Fragrance (Parfum)", "Cetyl Alcohol"])
    result = check_product_avoid_list(["parfum", "alcohol"], pid, db_path)
    assert result["product"] == {"id": pid, "name": "Rose Serum", "brand": "Dew Labs"}
    assert result["status"] == "found" and result["lists"] == ["parfum", "alcohol"]
    assert check_product_avoid_list(["parfum"], 9999, db_path) is None
    assert check_product_avoid_list(["parfum"], "1 OR 1=1", db_path) is None


def test_checking_a_list_changes_nothing_in_the_database(db_path):
    pid = add_product(db_path, "Rose Serum", ["Water", "Fragrance"])
    before = dump(db_path)
    check_product_avoid_list(["fragrance", "water"], pid, db_path)
    assert dump(db_path) == before


# ---------------------------------------------------------------- compare uses the same rules

def test_compare_treats_the_synonym_names_as_one_ingredient_and_nothing_else(db_path):
    a = add_product(db_path, "Niacinamide A", ["Aqua", "Niacinamide", "Parfum", "Glycerin", "Sodium Hyaluronate"])
    b = add_product(db_path, "Niacinamide B", ["WATER", "niacinamide", "Fragrance (Parfum)", "Glycerine",
                                               "Hyaluronic Acid"])
    ing = compare_products(a, b, db_path)["ingredients"]
    assert ing["shared"] == ["Aqua", "Niacinamide", "Parfum"]
    assert ing["only_a"] == ["Glycerin", "Sodium Hyaluronate"]
    assert ing["only_b"] == ["Glycerine", "Hyaluronic Acid"]


# ---------------------------------------------------------------- the pages

def set_list(client, terms, raw=None):
    value = raw if raw is not None else quote(json.dumps(terms))
    client.set_cookie(avoid_content.COOKIE_NAME, value)


@pytest.fixture
def shop(db_path):
    return {
        "rose": add_product(db_path, "Rose Serum", ["Water", "Niacinamide", "Fragrance (Parfum)", "Cetyl Alcohol"]),
        "plain": add_product(db_path, "Plain Serum", ["Water", "Niacinamide", "Glycerin"]),
        "alc": add_product(db_path, "Spirit Serum", ["Water", "Niacinamide", "Alcohol Denat."]),
        "blank": add_product(db_path, "Blank Serum", [], text=""),
        "null": add_product(db_path, "Unlisted Serum", [], text=None),
    }


def html(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def shown(page_html, names=("Rose Serum", "Plain Serum", "Spirit Serum", "Blank Serum", "Unlisted Serum")):
    return [n for n in names if f">{n}</a>" in page_html]


def test_without_a_list_the_products_page_has_no_tags_and_a_disabled_switch(shop, client):
    page = html(client, "/products")
    assert avoid_content.STORE_NOTE in page and avoid_content.EMPTY_HINT in page
    assert "Lists:" not in page and avoid_content.NO_INGREDIENTS not in page and avoid_content.BASED_ON_NOTE not in page
    assert re.search(r'<input type="checkbox" name="hide" value="1"[^>]*disabled', page)
    assert len(shown(page)) == 5


def test_the_list_shows_as_removable_chips_with_the_storage_note(shop, client):
    set_list(client, ["fragrance", "cetyl alcohol"])
    page = html(client, "/products")
    assert avoid_content.STORE_NOTE in page
    assert re.findall(r'<li class="chip"><span>([^<]+)</span>', page) == ["fragrance", "cetyl alcohol"]
    assert page.count('data-remove="') == 2
    assert avoid_content.CLEAR_LABEL in page and avoid_content.ADD_LABEL in page


def test_each_row_shows_what_matched(shop, client):
    set_list(client, ["parfum", "alcohol"])
    page = html(client, "/products")
    rose = page.split(">Rose Serum</a>")[1].split("</td>")[0]
    assert "Lists: parfum, alcohol" in rose
    assert "matched: Fragrance (Parfum), Cetyl Alcohol" in rose
    spirit = page.split(">Spirit Serum</a>")[1].split("</td>")[0]
    assert "Lists: alcohol" in spirit and "matched: Alcohol Denat." in spirit
    plain = page.split(">Plain Serum</a>")[1].split("</td>")[0]
    assert "Lists:" not in plain and "matched" not in plain
    assert avoid_content.BASED_ON_NOTE in page


def test_products_with_no_ingredient_list_say_so_and_are_never_clear(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, "/products")
    for name in ("Blank Serum", "Unlisted Serum"):
        cell = page.split(f">{name}</a>")[1].split("</td>")[0]
        assert "Ingredient list not available, can&#39;t check" in cell or "Ingredient list not available, can't check" in cell
    assert page.count("not available, can") == 2


def test_the_hide_switch_hides_products_that_list_a_word_and_keeps_the_rest(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, "/products?hide=1")
    assert shown(page) == ["Plain Serum", "Spirit Serum", "Blank Serum", "Unlisted Serum"]   # the can't-check ones stay
    assert "1 product hidden because they list an ingredient on your list." in page
    assert "4 products" in page
    assert re.search(r'<input type="checkbox" name="hide" value="1" checked', page)


def test_without_the_switch_nothing_is_hidden(shop, client):
    set_list(client, ["fragrance"])
    assert len(shown(html(client, "/products"))) == 5


def test_the_switch_does_nothing_without_a_list(shop, client):
    page = html(client, "/products?hide=1")
    assert len(shown(page)) == 5 and "hidden because" not in page


def test_hiding_combines_with_search_and_category(shop, client, db_path):
    add_product(db_path, "Rose Cream", ["Water", "Parfum"], group="Moisturizers")
    set_list(client, ["fragrance"])
    page = html(client, "/products?hide=1&category=Face+Serums&q=serum")
    assert shown(page) == ["Plain Serum", "Spirit Serum", "Blank Serum", "Unlisted Serum"]
    assert "Rose Cream" not in html(client, "/products?hide=1")


def test_hiding_everything_shows_the_empty_message_with_the_count(db_path, client):
    add_product(db_path, "Rose Serum", ["Fragrance"])
    set_list(client, ["fragrance"])
    page = html(client, "/products?hide=1")
    assert "No products found." in page and "1 product hidden" in page


def test_the_count_and_pages_follow_the_products_that_are_left(db_path, client):
    for i in range(30):
        add_product(db_path, f"Plain {i:02d}", ["Water"])
    for i in range(10):
        add_product(db_path, f"Scented {i:02d}", ["Water", "Fragrance"])
    set_list(client, ["fragrance"])
    page = html(client, "/products")
    assert "40 products · page 1 of 2" in page
    page = html(client, "/products?hide=1")
    assert "30 products · page 1 of 2" in page and "10 products hidden" in page
    assert "Scented" not in page
    second = html(client, "/products?hide=1&page=2")
    assert "30 products · page 2 of 2" in second and second.count('class="product-link"') == 30 - PAGE_SIZE


def test_pagination_and_detail_links_keep_the_switch_but_never_the_words(db_path, client):
    for i in range(30):
        add_product(db_path, f"Plain {i:02d}", ["Water"])
    set_list(client, ["secretword"])
    page = html(client, "/products?hide=1")
    hrefs = [h.replace("&amp;", "&") for h in re.findall(r'href="([^"]*)"', page)]
    assert any("hide=1" in h and "page=2" in h for h in hrefs)
    assert any(re.fullmatch(r"/products/\d+\?hide=1", h) for h in hrefs)
    assert not any("secretword" in h for h in hrefs)
    assert "secretword" in page                                  # shown as a chip, not as a link


def test_no_page_puts_the_list_in_a_link_or_form(shop, client):
    set_list(client, ["fragrance", "zzzword"])
    urls = []
    for url in ("/products", "/products?hide=1", f"/products/{shop['rose']}",
                f"/compare?a={shop['rose']}&b={shop['plain']}"):
        page = html(client, url)
        urls += re.findall(r'(?:href|action|src)="([^"]*)"', page)
    assert urls and not any("fragrance" in u.lower() or "zzzword" in u for u in urls)


def test_the_detail_page_shows_the_result_and_marks_the_ingredient(shop, client):
    set_list(client, ["alcohol", "fragrance", "sulfate"])
    page = html(client, f"/products/{shop['rose']}")
    assert avoid_content.DETAIL_TITLE in page
    assert "Lists: alcohol" in page and "matched: Cetyl Alcohol" in page
    assert "Lists: fragrance" in page and "matched: Fragrance (Parfum)" in page
    assert "Lists: sulfate" not in page
    assert page.count('class="avoid-hit"') == 2
    assert avoid_content.BASED_ON_NOTE in page and avoid_content.EDIT_LINK in page


def test_the_detail_page_says_none_found_without_calling_the_product_anything_else(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, f"/products/{shop['plain']}")
    assert avoid_content.NOT_FOUND in page and 'class="avoid-hit"' not in page


def test_the_detail_page_of_a_product_without_ingredients_cannot_be_checked(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, f"/products/{shop['blank']}")
    assert "Ingredient list not available, can" in page and avoid_content.NOT_FOUND not in page


def test_the_detail_page_has_no_avoid_box_without_a_list(shop, client):
    page = html(client, f"/products/{shop['rose']}")
    assert avoid_content.DETAIL_TITLE not in page and "Lists:" not in page


def test_the_back_link_keeps_the_hide_switch(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, f"/products/{shop['plain']}?hide=1&q=serum")
    back = re.search(r'class="back-link" href="([^"]+)"', page).group(1).replace("&amp;", "&")
    assert back == "/products?q=serum&hide=1"


def compare_url(a, b):
    return f"/compare?a={a}&b={b}"


def test_compare_has_a_row_with_the_matches_none_found_or_cannot_check(shop, client, db_path):
    other = add_product(db_path, "Lone Serum", ["Water", "Niacinamide", "Glycerin"])
    set_list(client, ["alcohol", "parfum"])
    page = html(client, compare_url(shop["rose"], shop["plain"]))
    row = page.split(f'<th scope="row">{avoid_content.COMPARE_ROW}</th>')[1].split("</tr>")[0]
    cells = re.findall(r"<td>(.*?)</td>", row, re.S)
    assert len(cells) == 2
    assert "matched: Cetyl Alcohol" in cells[0] and "matched: Fragrance (Parfum)" in cells[0]
    assert avoid_content.NOT_FOUND in cells[1] and "matched" not in cells[1]
    assert avoid_content.BASED_ON_NOTE in page
    page = html(client, compare_url(shop["plain"], other))
    assert page.count(avoid_content.NOT_FOUND) == 2


def test_compare_says_when_a_product_has_no_ingredient_list(shop, client, db_path):
    blank = add_product(db_path, "Blank Niacinamide Serum", [], text="")      # in a main group by its name
    set_list(client, ["fragrance"])
    page = html(client, compare_url(shop["plain"], blank))
    row = page.split(f'<th scope="row">{avoid_content.COMPARE_ROW}</th>')[1].split("</tr>")[0]
    cells = re.findall(r"<td>(.*?)</td>", row, re.S)
    assert avoid_content.NOT_FOUND in cells[0] and "Ingredient list not available, can" in cells[1]


def test_compare_has_no_avoid_row_without_a_list_or_when_not_comparable(shop, client, db_path):
    page = html(client, compare_url(shop["rose"], shop["plain"]))
    assert avoid_content.COMPARE_ROW not in page and avoid_content.BASED_ON_NOTE not in page
    set_list(client, ["fragrance"])
    cream = add_product(db_path, "Some Cream", ["Water"], group="Moisturizers")
    assert avoid_content.COMPARE_ROW not in html(client, compare_url(shop["rose"], cream))


# ---------------------------------------------------------------- the cookie is only input

@pytest.mark.parametrize("raw", [
    "not json", "%7B%22a%22%3A1%7D", quote('"fragrance"'), quote("[1, 2, null]"), quote("[[], {}]"),
    "%E0%A4%A", quote(json.dumps(["x" * 500])), "x" * 3500, quote("[" * 1200),
])
def test_a_broken_or_odd_cookie_is_ignored_not_an_error(shop, client, raw):
    set_list(client, None, raw=raw)
    for url in ("/products", "/products?hide=1", f"/products/{shop['rose']}", compare_url(shop["rose"], shop["plain"])):
        assert client.get(url).status_code == 200
    page = html(client, "/products")
    assert re.findall(r'<li class="chip">', page) == [] and len(shown(page)) == 5


def test_the_page_shows_at_most_20_words_and_only_usable_ones(shop, client):
    set_list(client, [f"word{i}" for i in range(40)] + ["<script>alert(1)</script>"])
    page = html(client, "/products")
    assert len(re.findall(r'<li class="chip">', page)) == 20
    assert "<script>alert" not in page


def test_words_in_the_cookie_are_escaped_on_the_page(shop, client):
    set_list(client, ["a'b(c)", "x/y"])
    page = html(client, "/products")
    assert 'data-remove="a&#39;b(c)"' in page and "<li class=\"chip\"><span>x/y</span>" in page


def test_the_server_never_sets_a_cookie(shop, client):
    set_list(client, ["fragrance"])
    for url in ("/products", "/products?hide=1", f"/products/{shop['rose']}", compare_url(shop["rose"], shop["plain"])):
        assert "Set-Cookie" not in client.get(url).headers


@pytest.mark.parametrize("url", ["/products", "/products?hide=1", "/products/{rose}", "/compare?a={rose}&b={plain}"])
def test_pages_that_read_the_list_are_private_and_vary_by_cookie(shop, client, url):
    response = client.get(url.format(**shop))
    assert response.headers["Cache-Control"] == "private"
    assert "Cookie" in response.headers["Vary"]


def test_other_pages_are_left_alone(client):
    assert "private" not in client.get("/insights").headers.get("Cache-Control", "")


# ---------------------------------------------------------------- never saved, never logged

def test_the_list_is_never_written_to_the_database(shop, client, db_path):
    before = dump(db_path)
    set_list(client, ["fragrance", "uniqueword", "alcohol"])
    for url in ("/products", "/products?hide=1&q=serum", "/products?category=Face+Serums",
                f"/products/{shop['rose']}", compare_url(shop["rose"], shop["plain"]), "/compare", "/insights", "/today"):
        client.get(url)
    after = dump(db_path)
    assert after == before
    assert not any("uniqueword" in line for line in after)


def test_the_list_is_never_logged_or_printed(shop, client, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    set_list(client, ["fragrance", "uniqueword"])
    for url in ("/products", "/products?hide=1", f"/products/{shop['rose']}", compare_url(shop["rose"], shop["plain"])):
        client.get(url)
    assert "uniqueword" not in caplog.text and "uniqueword" not in " ".join(r.getMessage() for r in caplog.records)
    out = capsys.readouterr()
    assert "uniqueword" not in out.out and "uniqueword" not in out.err


def test_the_app_code_has_no_logging_of_requests_or_cookies():
    for name in ("app.py", "database/services.py", "database/ingredient_match.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "import logging" not in source and "app.logger" not in source and "print(" not in source, name


def test_the_script_keeps_the_list_in_the_browser_only():
    source = (ROOT / "static/js/avoid.js").read_text(encoding="utf-8")
    assert "SameSite=Lax" in source and "max-age=" in source and "path=/" in source
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "localStorage", "sessionStorage", "searchParams.set",
                      "searchParams.append", "WebSocket"):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------- wording

BANNED = [
    r"\bsafe\b", r"\bsafer\b", r"\bsafety\b", r"free of", r"\bfree\b", r"\bclean\b", r"\bcleaner\b", r"\bbest\b",
    r"\bbetter\b", r"recommend", r"suitable", r"good for", r"\bhealthy\b", r"\bharmless\b", r"toxic",
    r"hypoallergenic", r"\btreats?\b", r"\bcures?\b", r"\bproven\b", r"\beffective\b", r"\bworks?\b", r"\bwinner\b",
]


def banned_in(text):
    return [pattern for pattern in BANNED if re.search(pattern, text, re.I)]


def test_the_avoid_list_texts_use_none_of_the_banned_words():
    texts = [v for k, v in vars(avoid_content).items() if k.isupper() and isinstance(v, str)]
    texts += [avoid_content.hidden_text(1), avoid_content.hidden_text(5)]
    assert len(texts) > 15
    for text in texts:
        assert banned_in(text) == [], text


def test_the_avoid_list_template_uses_none_of_the_banned_words():
    source = (ROOT / "templates" / "_avoid.html").read_text(encoding="utf-8")
    visible = re.sub(r"\{[{%#].*?[}%#]\}", " ", source, flags=re.S)       # drop the template code
    visible = re.sub(r"<[^>]+>", " ", visible)
    assert banned_in(visible) == []


def test_every_avoid_list_state_on_the_pages_uses_none_of_the_banned_words(shop, client):
    set_list(client, ["fragrance", "alcohol", "nothingfound"])
    seen = []
    for url in ("/products", "/products?hide=1", f"/products/{shop['rose']}", f"/products/{shop['plain']}",
                f"/products/{shop['blank']}", compare_url(shop["rose"], shop["plain"]),
                compare_url(shop["plain"], shop["blank"])):
        page = html(client, url)
        for block in re.findall(r'<(section|p|span|ul|details)[^>]*class="[^"]*(?:avoid|tag|chip)[^"]*"[^>]*>(.*?)</\1>',
                                page, re.S):
            seen.append(re.sub(r"<[^>]+>", " ", block[1]))
    assert len(seen) > 10
    for text in seen:
        assert banned_in(text) == [], text


def test_the_required_texts_are_word_for_word():
    assert avoid_content.STORE_NOTE == ("Your list is stored in your browser. The site reads it to filter results "
                                        "but does not save it.")
    assert avoid_content.BASED_ON_NOTE == ("Based on the ingredient list as written by the brand. Lists can be "
                                           "incomplete. Check the product label.")
    assert avoid_content.NOT_FOUND == "None found in the listed ingredients."
    assert avoid_content.NO_INGREDIENTS == "Ingredient list not available, can't check"
    assert avoid_content.HIDE_LABEL == "Hide products that list my avoided ingredients"
    assert avoid_content.CLEAR_LABEL == "Clear my list"
    assert (avoid_content.MAX_TERMS, avoid_content.MAX_TERM_LENGTH) == (20, 40)


# ---------------------------------------------------------------- where it appears

def filter_form(page):
    return re.search(r'<form class="filter-bar".*?</form>', page, re.S).group(0)


def filter_section(page):
    return re.search(r'<details class="avoid-filter".*?</details>', page, re.S).group(0)


def test_the_avoid_filter_is_inside_the_filter_form_after_the_group_dropdown(shop, client):
    page = html(client, "/products")
    form = filter_form(page)
    assert form.count('id="avoid-filter"') == 1 and page.count('id="avoid-filter"') == 1
    assert form.index('name="category"') < form.index('id="avoid-filter"') < form.index('name="sort"')
    assert page.count("<form") == 1                              # no form inside the form
    assert '<details class="avoid-filter" id="avoid-filter">' in form        # closed: the list is empty
    assert f">{avoid_content.FILTER_LABEL}</summary>" in form


def test_the_filter_is_open_only_when_the_list_has_items(shop, client):
    assert '<details class="avoid-filter" id="avoid-filter">' in html(client, "/products")
    set_list(client, ["fragrance", "alcohol"])
    page = html(client, "/products")
    assert '<details class="avoid-filter" id="avoid-filter" open>' in page
    assert 'Ingredients to avoid <span class="avoid-count">(2)</span>' in page
    set_list(client, [])
    assert '<details class="avoid-filter" id="avoid-filter">' in html(client, "/products")


def test_everything_the_filter_needs_is_inside_it(shop, client):
    set_list(client, ["fragrance"])
    section = filter_section(html(client, "/products"))
    assert avoid_content.STORE_NOTE in section and avoid_content.INPUT_LABEL in section
    assert re.search(r'<input class="form-input" id="avoid-input" type="text"(?![^>]*name=)', section)   # never sent
    assert '<button class="btn-primary" type="button" id="avoid-add">Add</button>' in section
    assert '<button class="btn-ghost" type="button" id="avoid-clear">Clear my list</button>' in section
    assert ('<li class="chip"><span>fragrance</span><button type="button" class="chip-remove" '
            'data-remove="fragrance"') in section
    assert 'name="hide" value="1"' in section and avoid_content.HIDE_LABEL in section
    assert 'type="submit"' not in section


def test_the_hidden_count_is_inside_the_filter_not_above_the_results(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, "/products?hide=1")
    assert "1 product hidden because they list an ingredient on your list." in filter_section(page)
    assert page.count("hidden because") == 1
    assert 'name="hide" value="1" checked' in filter_section(page)


def test_nothing_about_the_list_is_above_the_filters_or_between_them_and_the_results(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, "/products?hide=1")
    above = page.split('<form class="filter-bar"')[0].split('<section class="products-page">')[1]
    assert "avoid" not in above.lower() and "list" not in re.sub(r"<[^>]+>", " ", above).lower()
    between = page.split("</form>")[1].split('<div class="table-wrap">')[0]
    assert "avoid" not in between.lower() and "hidden" not in between.lower()


def test_the_old_box_is_gone(shop, client):
    page = html(client, "/products")
    for old in ('id="avoid-panel"', 'class="avoid-panel"', 'id="avoid-form"', "My avoid list", 'id="avoid-title"'):
        assert old not in page, old


def test_the_detail_page_has_only_results_and_an_edit_link(shop, client):
    set_list(client, ["fragrance", "alcohol"])
    page = html(client, f"/products/{shop['rose']}")
    section = re.search(r'<section class="avoid-detail".*?</section>', page, re.S).group(0)
    for editing in ("<input", "<button", "<form", 'class="chip', "data-remove", "avoid-input", "avoid-add",
                    "avoid-clear"):
        assert editing not in page, editing
    assert "Checked against: fragrance, alcohol" in section
    assert f'<a href="/products#avoid-filter">{avoid_content.EDIT_LINK}</a>' in section


def test_compare_has_only_results_and_an_edit_link(shop, client):
    set_list(client, ["fragrance"])
    page = html(client, compare_url(shop["rose"], shop["plain"]))
    for editing in ('class="chip', "data-remove", "avoid-input", "avoid-add", "avoid-clear", 'name="hide"'):
        assert editing not in page, editing
    assert f'<a href="/products#avoid-filter">{avoid_content.EDIT_LINK}</a>' in page
    assert page.count(avoid_content.EDIT_LINK) == 1


def test_with_an_empty_list_the_detail_and_compare_pages_show_nothing_about_it(shop, client):
    for url in (f"/products/{shop['rose']}", compare_url(shop["rose"], shop["plain"])):
        page = html(client, url)
        for text in (avoid_content.EDIT_LINK, avoid_content.DETAIL_TITLE, avoid_content.COMPARE_ROW, "#avoid-filter",
                     avoid_content.BASED_ON_NOTE, avoid_content.CHECKED_AGAINST, "Lists:", avoid_content.NOT_FOUND):
            assert text not in page, text
    set_list(client, [])
    assert avoid_content.EDIT_LINK not in html(client, f"/products/{shop['rose']}")


def test_the_edit_link_leads_to_the_open_filter(shop, client):
    set_list(client, ["fragrance"])
    href = re.search(r'<a href="(/products#avoid-filter)">', html(client, f"/products/{shop['rose']}")).group(1)
    assert '<details class="avoid-filter" id="avoid-filter" open>' in html(client, href.split("#")[0])


def test_the_script_targets_the_filter_and_adds_on_enter_without_searching():
    source = (ROOT / "static/js/avoid.js").read_text(encoding="utf-8")
    assert 'getElementById("avoid-filter")' in source and "#avoid-filter" in source
    assert "avoid-panel" not in source and "avoid-form" not in source and '"submit"' not in source
    assert 'event.key === "Enter"' in source and "event.preventDefault()" in source


def test_the_filter_has_phone_width_rules():
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    phone = css.split("@media (max-width: 600px) {\n    .avoid-filter")[1].split("\n}")[0]
    assert "flex: 1 1 100%" in phone and "flex-direction: column" in phone
