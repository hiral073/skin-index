import re
from contextlib import closing
from datetime import date

import pytest

from database.db import get_db

TODAY = date.today().isoformat()

# Words the Compare page must never use: it names no product better, cheaper or recommended
BANNED = ["better", "best", "worse", "cheaper", "cheapest", "winner", "dupe", "safe", "treats", "cures",
          "recommend", "effective", "proven"]


def add(db_path, name, brand="Dew Labs", group="Face Serums", price=20.0, size_text="100 mL",
        price_per_ml=0.2, category=None, ingredients=(), loves=None, rating=None, reviews=None):
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group,"
            " loves_count, rating, reviews) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category or group, price, size_text, price_per_ml, group, loves, rating, reviews),
        ).lastrowid
        for position, (ingredient, *percent) in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute(
                "INSERT INTO product_ingredients (product_id, ingredient_id, position, stated_percent)"
                " VALUES (?, ?, ?, ?)", (pid, iid, position, percent[0] if percent else None),
            )
    return pid


def save_rate(db_path, rate=90.0):
    with closing(get_db(db_path)) as conn, conn:
        conn.execute(
            "INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
            " VALUES (?, 'USD', 'INR', ?, ?)", (TODAY, rate, TODAY),
        )


@pytest.fixture
def shop(app):
    """Face Serums: three with niacinamide (n1, n2, n3), one with vitamin C (c1), one with neither
    (plain). Moisturizers: two with niacinamide (m1, m2). A Mini Size product and a lone Sunscreen."""
    db = app.config["DATABASE"]
    return {
        "n1": add(db, "Bravo Serum", price=20.0, size_text="100 mL", price_per_ml=0.2, loves=1200, rating=4.5,
                  reviews=300, ingredients=[("Water",), ("Glycerin",), ("Niacinamide",), ("Squalane",)]),
        "n2": add(db, "Delta Serum", brand="Glow Co", price=30.0, size_text="100 mL", price_per_ml=0.3,
                  loves=800, rating=4.0, reviews=50,
                  ingredients=[("Water",), ("Niacinamide",), ("Squalane",), ("Panthenol",)]),
        "n3": add(db, "Echo Niacinamide Serum", price=10.0, size_text="50 mL", price_per_ml=0.2,
                  ingredients=[("Water",)]),
        "c1": add(db, "Charlie Serum", brand="Glow Co", price=15.0, size_text="15 mL", price_per_ml=1.0,
                  ingredients=[("Water",), ("Ascorbic Acid",)]),
        "plain": add(db, "Plain Serum", ingredients=[("Water",), ("Glycerin",)]),
        "m1": add(db, "Foxtrot Cream", group="Moisturizers", ingredients=[("Water",), ("Niacinamide",)]),
        "m2": add(db, "Golf Cream", group="Moisturizers", ingredients=[("Niacinamide",)]),
        "mini": add(db, "Tiny Pot", group=None, category="Mini Size", ingredients=[("Niacinamide",)]),
        "lone": add(db, "Lone Screen", group="Sunscreen", ingredients=[("Niacinamide",)]),
    }


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def options(html, select_name):
    """(value, label) pairs of one <select>, or None when the page has none."""
    body = re.search(rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>', html, re.S)
    if not body:
        return None
    return re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', body.group(1), re.S)


def labels(html, select_name):
    return [label for value, label in options(html, select_name) if value]


def selected(html, select_name):
    body = re.search(rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>', html, re.S).group(1)
    return re.findall(r'<option value="([^"]*)" selected', body)


def row_labels(html):
    return re.findall(r'<th scope="row">(.*?)</th>', html)


def cells(html, label):
    """The cells of the table row with this row heading."""
    row = re.search(rf'<th scope="row">{re.escape(label)}</th>(.*?)</tr>', html, re.S).group(1)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]


def compare_html(client, shop, a, b, extra=""):
    return page(client, f"/compare?a={shop[a]}&b={shop[b]}{extra}")


# ---------------------------------------------------------------- the picker flow

def test_empty_page_offers_only_categories_with_two_products_and_nothing_else(shop, client, rate_api):
    html = page(client, "/compare")
    assert [v for v, _ in options(html, "group") if v] == ["Face Serums", "Moisturizers"]   # not Sunscreen (1), not Mini Size
    assert labels(html, "group") == ["Face Serums (5)", "Moisturizers (2)"]
    for name in ("ingredient", "a", "b"):
        assert options(html, name) is None                                   # each waits for the one before
    assert ">Show</button>" in html and rate_api.calls == []


def test_choosing_a_category_lists_its_main_ingredients_with_counts(shop, client):
    html = page(client, "/compare?group=Face+Serums")
    assert selected(html, "group") == ["Face Serums"]
    assert labels(html, "ingredient") == ["niacinamide (3 products)", "vitamin C (1 product, too few to compare)"]
    assert 'value="vitamin-c"  disabled' in html or re.search(r'value="vitamin-c"[^>]*disabled', html)
    assert not re.search(r'value="niacinamide"[^>]*disabled', html)
    assert options(html, "a") is None and options(html, "b") is None


def test_choosing_a_main_ingredient_lists_the_products_in_both_pickers(shop, client):
    html = page(client, "/compare?group=Face+Serums&ingredient=niacinamide")
    expected = ["Dew Labs - Bravo Serum (100 mL, $20.00)", "Glow Co - Delta Serum (100 mL, $30.00)",
                "Dew Labs - Echo Niacinamide Serum (50 mL, $10.00)"]
    assert labels(html, "a") == expected and labels(html, "b") == expected    # sorted by name
    for other in ("Charlie Serum", "Plain Serum", "Foxtrot Cream", "Tiny Pot"):
        assert other not in html                                              # other groups and ingredients are not offered


def test_after_choosing_a_the_b_list_is_limited_to_the_same_category_and_ingredient_without_a(shop, client):
    html = page(client, f"/compare?a={shop['n1']}")
    assert selected(html, "group") == ["Face Serums"] and selected(html, "ingredient") == ["niacinamide"]
    assert selected(html, "a") == [str(shop["n1"])]
    assert labels(html, "b") == ["Glow Co - Delta Serum (100 mL, $30.00)",
                                 "Dew Labs - Echo Niacinamide Serum (50 mL, $10.00)"]
    assert not any("Bravo Serum" in label for label in labels(html, "b"))
    for other in ("Charlie Serum", "Foxtrot Cream", "Golf Cream"):             # a vitamin C serum, another category
        assert other not in html


def test_after_choosing_b_first_the_a_list_is_limited_the_same_way(shop, client):
    html = page(client, f"/compare?b={shop['n2']}")
    assert labels(html, "a") == ["Dew Labs - Bravo Serum (100 mL, $20.00)",
                                 "Dew Labs - Echo Niacinamide Serum (50 mL, $10.00)"]


def test_a_product_in_two_main_groups_lets_you_choose_which_one(app, client):
    db = app.config["DATABASE"]
    a = add(db, "Duo Serum", ingredients=[("Niacinamide",), ("Sodium Hyaluronate",)])
    add(db, "N Serum", ingredients=[("Niacinamide",)])
    add(db, "H Serum", ingredients=[("Sodium Hyaluronate",)])
    html = page(client, f"/compare?a={a}")
    assert labels(html, "ingredient") == ["niacinamide (2 products)", "hyaluronic acid (2 products)"]
    assert selected(html, "ingredient") == [] and options(html, "b") is None   # B waits for the choice
    html = page(client, f"/compare?a={a}&ingredient=hyaluronic-acid")
    assert labels(html, "b") == ["Dew Labs - H Serum (100 mL, $20.00)"]


def test_a_leftover_product_from_an_old_category_or_ingredient_is_not_a_choice(shop, client):
    html = page(client, f"/compare?a={shop['m1']}&group=Face+Serums")            # form sent without JavaScript
    assert options(html, "a") is None and "Foxtrot Cream" not in html and selected(html, "group") == ["Face Serums"]
    html = page(client, f"/compare?a={shop['c1']}&group=Face+Serums&ingredient=niacinamide")
    assert selected(html, "a") == [] and "Charlie Serum" not in html
    html = page(client, f"/compare?a={shop['n1']}&group=Face+Serums&ingredient=niacinamide")
    assert selected(html, "a") == [str(shop["n1"])]


def test_an_unknown_category_or_ingredient_is_ignored(shop, client):
    html = page(client, "/compare?group=Nope&ingredient=nope")
    assert options(html, "ingredient") is None
    html = page(client, "/compare?group=Face+Serums&ingredient=nope")
    assert selected(html, "ingredient") == [] and options(html, "a") is None


def test_every_picker_state_has_a_visible_show_button_and_the_javascript_hooks(shop, client):
    for url in ("/compare", "/compare?group=Face+Serums", "/compare?group=Face+Serums&ingredient=niacinamide"):
        assert ">Show</button>" in page(client, url)
    html = page(client, "/compare?group=Face+Serums&ingredient=niacinamide")
    assert 'data-resets="ingredient a b"' in html and 'data-resets="a b"' in html
    assert html.count("data-autosubmit") == 4 and "main.js" in html
    js = client.get("/static/js/main.js").get_data(as_text=True)
    assert "[data-autosubmit]" in js and "dataset.resets" in js and "form.submit()" in js


# ---------------------------------------------------------------- fewer than two products

def test_a_category_with_one_product_says_so_plainly(shop, client):
    html = page(client, f"/compare?a={shop['lone']}")
    assert "There is only 1 product in Sunscreen, so there is nothing to compare." in html
    assert options(html, "b") is None


def test_a_main_ingredient_with_one_product_says_so_plainly_and_lists_no_products(shop, client):
    html = page(client, f"/compare?a={shop['c1']}")
    assert "Only 1 product in Face Serums is in the vitamin C group, so there is nothing to compare." in html
    assert options(html, "a") is None and options(html, "b") is None
    html = page(client, "/compare?group=Face+Serums&ingredient=vitamin-c")
    assert "Only 1 product in Face Serums is in the vitamin C group, so there is nothing to compare." in html


def test_a_category_where_no_main_ingredient_has_two_products(app, client):
    db = app.config["DATABASE"]
    add(db, "One", group="Toners", ingredients=[("Niacinamide",)])
    add(db, "Two", group="Toners", ingredients=[("Ascorbic Acid",)])
    html = page(client, "/compare?group=Toners")
    assert "In Toners, no main ingredient group has 2 or more products, so there is nothing to compare." in html
    assert options(html, "a") is None


def test_a_category_with_no_product_in_a_main_group(app, client):
    db = app.config["DATABASE"]
    add(db, "One", group="Toners", ingredients=[("Water",)])
    add(db, "Two", group="Toners", ingredients=[("Glycerin",)])
    html = page(client, "/compare?group=Toners")
    assert "No product in Toners is in a main ingredient group, so there is nothing to compare." in html


def test_a_product_in_no_main_group_cannot_be_compared(shop, client):
    html = page(client, f"/compare?a={shop['plain']}")
    assert "Product A doesn't name any of the main ingredients we group by or list one among its first 10 " \
           "ingredients, so it can't be compared here." in html.replace("&#39;", "'")
    assert options(html, "b") is None


# ---------------------------------------------------------------- bad and unusual ids

@pytest.mark.parametrize("value", ["abc", "0", "-3", "1.5", " ", "", "1e3", "٣", "12abc", "0x10", "%20"])
def test_invalid_ids_are_ignored(shop, client, value):
    response = client.get("/compare", query_string={"a": value})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "find product" not in html and selected(html, "group") == [] and options(html, "a") is None


def test_a_valid_but_unknown_id_gets_a_friendly_message_and_still_lets_you_pick(shop, client):
    html = page(client, "/compare?a=99999")
    assert "couldn&#39;t find product A (id 99999)" in html or "couldn't find product A (id 99999)" in html
    assert options(html, "group") is not None


def test_unknown_a_with_a_valid_b_limits_the_a_list_to_bs_category_and_ingredient(shop, client):
    html = page(client, f"/compare?a=99999&b={shop['n2']}")
    assert "find product A (id 99999)" in html
    assert labels(html, "a")[0].startswith("Dew Labs - Bravo Serum")
    assert not any("Delta Serum" in label for label in labels(html, "a"))


def test_a_huge_id_does_not_crash(shop, client):
    assert "find product A" in page(client, "/compare?a=" + "9" * 40)


def test_the_same_id_on_both_sides_asks_for_a_different_product(shop, client):
    n1 = shop["n1"]
    html = page(client, f"/compare?a={n1}&b={n1}")
    assert "Product A and product B are the same product. Please choose a different product for B." in html
    assert selected(html, "b") == [] and "Ingredients both have" not in html


# ---------------------------------------------------------------- the comparison

def test_the_table_has_the_rows_asked_for_with_rupees(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "n1", "n2")
    assert row_labels(html) == [
        "Name", "Brand", "Category", "Main ingredient", "Size", "≈ Price (₹)", "≈ Price per ml (₹)", "Likes",
        "Rating", "Reviews", "Ingredients both have (3)", "Ingredients only in A (1)", "Ingredients only in B (1)",
    ]
    assert re.findall(r"<th[^>]*>(.*?)</th>", html)[:3] == ["", "Product A", "Product B"]
    assert cells(html, "Name") == ["Bravo Serum", "Delta Serum"]
    assert cells(html, "Brand") == ["Dew Labs", "Glow Co"]
    assert cells(html, "Main ingredient") == ["niacinamide"]
    assert cells(html, "Size") == ["100 mL", "100 mL"]
    assert cells(html, "≈ Price (₹)") == ["₹1,800", "₹2,700"]                  # $20 and $30 at 90
    assert cells(html, "≈ Price per ml (₹)") == ["₹18.00", "₹27.00"]
    assert cells(html, "Likes") == ["1,200", "800"]
    assert cells(html, "Rating") == ["4.50", "4.00"]
    assert cells(html, "Reviews") == ["300", "50"]
    assert f"Converted from US prices at 1 USD = ₹90.00 ({TODAY}). Approximate, not Indian retail prices." in html
    assert "$" not in html.split("<tbody>")[1].split("</tbody>")[0]            # rupees only, with a rate


def test_shared_and_unique_ingredient_lists(shop, client):
    html = compare_html(client, shop, "n1", "n2")
    assert cells(html, "Ingredients both have (3)") == ["Water, Niacinamide, Squalane"]
    assert cells(html, "Ingredients only in A (1)") == ["Glycerin"]
    assert cells(html, "Ingredients only in B (1)") == ["Panthenol"]
    swapped = compare_html(client, shop, "n2", "n1")
    assert cells(swapped, "Ingredients only in A (1)") == ["Panthenol"]
    assert cells(swapped, "Ingredients only in B (1)") == ["Glycerin"]


def test_an_empty_side_of_the_ingredient_lists_says_none(shop, client):
    html = compare_html(client, shop, "n1", "n3")                                # n3 has only Water
    assert cells(html, "Ingredients only in B (0)") == ["None."]
    assert cells(html, "Ingredients both have (1)") == ["Water"]


def test_the_two_notes_are_on_the_page_and_stated_strengths_are_not_shown(app, client):
    db = app.config["DATABASE"]
    a = add(db, "Bravo Serum", ingredients=[("Water",), ("Niacinamide", 5.0)])
    b = add(db, "Delta Serum", ingredients=[("Water",), ("Niacinamide", 3.0)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "Ingredient order is a rough guide. Amounts are not in our data." in html
    assert ("Shared ingredients show what the two products have in common. They do not mean the formulas "
            "behave the same.") in html
    assert "stated by brand" not in html and "5%" not in html and "3%" not in html
    assert "Likes, ratings and reviews come from one retailer&#39;s site and are as of March 2023." in html \
        or "Likes, ratings and reviews come from one retailer's site and are as of March 2023." in html


def test_missing_values_say_not_available(app, client):
    db = app.config["DATABASE"]
    a = add(db, "No Data", price=None, size_text=None, price_per_ml=None, ingredients=[("Niacinamide",)])
    b = add(db, "Has Data", price_per_ml=0.3, loves=5, rating=3.5, reviews=7, ingredients=[("Niacinamide",)])
    save_rate(db, 90.0)
    html = page(client, f"/compare?a={a}&b={b}")
    for label in ("Size", "≈ Price (₹)", "≈ Price per ml (₹)", "Likes", "Rating", "Reviews"):
        assert cells(html, label)[0] == "Not available", label
    assert cells(html, "Likes")[1] == "5" and cells(html, "≈ Price per ml (₹)")[1] == "₹27.00"


def test_missing_ingredients_show_not_available_but_the_numbers_still_show(app, client):
    db = app.config["DATABASE"]
    a = add(db, "Niacinamide Serum", ingredients=[], loves=9)
    b = add(db, "Has List", ingredients=[("Niacinamide",)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "One or both products list no ingredients." in html and "Ingredients both have" not in html
    assert cells(html, "Likes")[0] == "9"


def test_a_stale_rate_is_marked_older(shop, client):
    db = client.application.config["DATABASE"]
    with closing(get_db(db)) as conn, conn:
        conn.execute("INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                     " VALUES ('2026-01-02', 'USD', 'INR', 88.5, '2026-01-02')")
    html = compare_html(client, shop, "n1", "n2")                               # the API is offline in tests
    assert cells(html, "≈ Price (₹)")[0] == "₹1,770"
    assert "Approximate, not Indian retail prices. (older rate)" in html


def test_without_a_rate_dollars_are_shown_in_place_of_rupees_with_a_note(shop, client):
    html = compare_html(client, shop, "n1", "n2")                               # offline, nothing saved
    assert "₹" not in html and "Converted from" not in html
    assert cells(html, "Price (USD)") == ["$20.00", "$30.00"]
    assert cells(html, "Price per ml (USD)") == ["$0.200", "$0.300"]
    assert "Rupee prices are not available right now, so US dollar prices are shown." in html


def test_the_rate_is_fetched_once_for_a_comparison(shop, client, rate_api):
    compare_html(client, shop, "n1", "n2")
    compare_html(client, shop, "n1", "n3")
    assert len(rate_api.calls) == 1


def test_no_verdict_overlap_or_ranking_is_shown(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "n1", "n2").lower()
    for absent in ("overlap", "less per ml", "costs", "verdict", "distinct ingredients"):
        assert absent not in html, absent


# ---------------------------------------------------------------- not comparable

def test_a_niacinamide_serum_and_a_vitamin_c_serum_are_not_compared(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "n1", "c1")
    assert ("Product A is grouped under niacinamide and product B under vitamin C, so they can't be compared "
            "here: they share no main ingredient group.") in html.replace("&#39;", "'")
    assert cells(html, "Name") == ["Bravo Serum", "Charlie Serum"] and cells(html, "≈ Price (₹)") == ["₹1,800", "₹1,350"]
    for absent in ("Price per ml", "Likes", "Rating", "Reviews", "Ingredients both have", "Ingredient order is a rough"):
        assert absent not in html, absent
    link = re.search(r'<a class="btn-primary" href="([^"]+)">Choose another product to compare with A</a>', html)
    assert link and link.group(1) == f"/compare?a={shop['n1']}"


def test_different_categories_are_not_compared_even_with_the_same_main_ingredient(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "n1", "m1")
    assert ("Product A is in Face Serums and product B is in Moisturizers, so they can't be compared fairly.") \
        in html.replace("&#39;", "'")
    assert "Price per ml" not in html and "Ingredients both have" not in html
    link = re.search(r'<a class="btn-primary" href="([^"]+)">Choose a product from Face Serums</a>', html)
    assert link and link.group(1) == f"/compare?a={shop['n1']}"


def test_a_product_in_no_main_group_in_a_pair_gets_its_own_message(shop, client):
    html = compare_html(client, shop, "n1", "plain").replace("&#39;", "'")
    assert "Product B doesn't name any of the main ingredients" in html and "Product A doesn't" not in html
    assert "Ingredients both have" not in html


def test_a_mini_size_product_has_no_group_and_cannot_be_compared(shop, client):
    html = compare_html(client, shop, "mini", "n1").replace("&#39;", "'")
    assert "Product A (Mini Size) has no comparison group, so it can't be compared fairly with other products." in html
    assert "Price per ml" not in html
    html = page(client, f"/compare?a={shop['mini']}")
    assert "has no comparison group" in html and options(html, "b") is None


def test_two_mini_size_products_are_not_the_same_group(app, client):
    db = app.config["DATABASE"]
    a = add(db, "Tiny One", group=None, category="Mini Size")
    b = add(db, "Tiny Two", group=None, category="Mini Size")
    assert "has no comparison group" in page(client, f"/compare?a={a}&b={b}")


# ---------------------------------------------------------------- wording and safety

def test_the_compare_page_uses_none_of_the_banned_words(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    urls = ["/compare", "/compare?group=Face+Serums", "/compare?group=Face+Serums&ingredient=niacinamide",
            f"/compare?a={shop['n1']}", f"/compare?a={shop['n1']}&b={shop['n2']}",
            f"/compare?a={shop['n2']}&b={shop['n1']}", f"/compare?a={shop['n1']}&b={shop['c1']}",
            f"/compare?a={shop['n1']}&b={shop['m1']}", f"/compare?a={shop['n1']}&b={shop['n1']}",
            f"/compare?a={shop['c1']}", f"/compare?a={shop['lone']}", f"/compare?a={shop['plain']}",
            f"/compare?a={shop['mini']}", "/compare?a=99999"]
    for url in urls:
        body = re.sub(r"<[^>]+>", " ", page(client, url)).lower()
        for word in BANNED:
            assert not re.search(rf"\b{word}", body), (url, word)


def test_the_banned_word_check_would_catch_a_verdict(shop, client):
    body = "Bravo Serum is better than Delta Serum".lower()
    assert any(re.search(rf"\b{word}", body) for word in BANNED)


def test_names_are_escaped(app, client):
    db = app.config["DATABASE"]
    a = add(db, "<script>alert(1)</script> niacinamide", ingredients=[("Water",)])
    b = add(db, "Plain niacinamide", ingredients=[("Water",)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_compare_works_on_an_empty_database(app, client):
    html = page(client, "/compare")
    assert options(html, "group") == [("", "Choose a category")]


# ---------------------------------------------------------------- links to the page

def test_detail_page_links_to_compare_with_this_product(shop, client):
    html = page(client, f"/products/{shop['n1']}")
    assert f'href="/compare?a={shop["n1"]}"' in html and "Compare with another product" in html


def test_each_row_on_the_list_links_to_compare(shop, client):
    html = page(client, "/products")
    for key in ("n1", "m1", "mini"):
        assert f'<a class="row-compare" href="/compare?a={shop[key]}">Compare</a>' in html
    assert re.findall(r"<th[^>]*>(.*?)</th>", html) == ["Product", "Brand", "Category", "Size", "Price (USD)"]
