import re
from contextlib import closing
from datetime import date

import pytest

from database.db import COMPARE_DROPDOWN_MAX, get_db

TODAY = date.today().isoformat()


def add(db_path, name, brand="Dew Labs", group="Moisturizers", price=20.0, size_text="100 mL",
        price_per_ml=0.2, category=None, ingredients=()):
    with closing(get_db(db_path)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, brand, category or group, price, size_text, price_per_ml, group),
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
    """Moisturizers m1/m2/m3, Face Serums s1/s2, a Mini Size product, and a lone Sunscreen."""
    db = app.config["DATABASE"]
    ids = {
        "m1": add(db, "Bravo Cream", price=20.0, price_per_ml=0.2,
                  ingredients=[("Water",), ("Glycerin",), ("Squalane", 5.0)]),
        "m2": add(db, "Delta Balm", brand="Glow Co", price=30.0, size_text="100 mL", price_per_ml=0.3,
                  ingredients=[("Water",), ("Squalane", 3.0), ("Niacinamide",)]),
        "m3": add(db, "Echo Gel", price=10.0, size_text="50 mL", price_per_ml=0.2, ingredients=[("Water",)]),
        "s1": add(db, "Alpha Serum", brand="Glow Co", group="Face Serums", price=30.0, size_text="30 mL",
                  price_per_ml=1.0, ingredients=[("Water",), ("Niacinamide",)]),
        "s2": add(db, "Charlie Serum", group="Face Serums", price=15.0, size_text="15 mL", price_per_ml=1.0),
        "mini": add(db, "Tiny Pot", group=None, category="Mini Size", price=5.0, size_text="10 mL",
                    price_per_ml=0.5),
        "lone": add(db, "Lone Screen", group="Sunscreen", price=25.0, size_text="50 mL", price_per_ml=0.5),
    }
    return ids


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def options(html, select_name):
    """(value, label) pairs of one <select>."""
    body = re.search(rf'<select[^>]*name="{select_name}"[^>]*>(.*?)</select>', html, re.S)
    if not body:
        return None
    return re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', body.group(1), re.S)


# ---------------------------------------------------------------- picking

def test_empty_compare_page_offers_only_groups_with_two_products(shop, client, rate_api):
    html = page(client, "/compare")
    groups = [v for v, _ in options(html, "a_group") if v]
    assert groups == ["Face Serums", "Moisturizers"]                 # not Sunscreen (1), not Mini Size
    assert "Choose product A first" in html                            # B waits for A
    assert 'name="b_group"' not in html and 'name="b"' not in html
    assert rate_api.calls == []                                        # nothing shown, no rate fetched


def test_every_picker_has_a_visible_show_button(shop, client):
    assert ">Show</button>" in page(client, "/compare")
    assert ">Show</button>" in page(client, "/compare?a_group=Moisturizers")


def test_category_choice_lists_brands_and_products_with_labels(shop, client):
    html = page(client, "/compare?a_group=Moisturizers")
    assert [v for v, _ in options(html, "a_brand") if v] == ["Dew Labs", "Glow Co"]
    labels = [label for v, label in options(html, "a") if v]
    assert labels == [
        "Dew Labs - Bravo Cream (100 mL, $20.00)",
        "Glow Co - Delta Balm (100 mL, $30.00)",
        "Dew Labs - Echo Gel (50 mL, $10.00)",
    ]                                                                  # sorted by name
    assert "Alpha Serum" not in html                                   # other groups are not offered


def test_brand_choice_filters_the_product_list(shop, client):
    html = page(client, "/compare?a_group=Moisturizers&a_brand=Glow+Co")
    assert [label for v, label in options(html, "a") if v] == ["Glow Co - Delta Balm (100 mL, $30.00)"]
    assert '<option value="Glow Co" selected>' in html


def test_search_box_narrows_the_list_inside_the_category(shop, client):
    html = page(client, "/compare?a_group=Moisturizers&a_q=gel")
    assert [label for v, label in options(html, "a") if v] == ["Dew Labs - Echo Gel (50 mL, $10.00)"]
    assert 'value="gel"' in html


def test_unknown_category_or_brand_is_ignored(shop, client):
    html = page(client, "/compare?a_group=Nope&a_brand=Nobody")
    assert options(html, "a") is None and options(html, "a_brand") is None
    html = page(client, "/compare?a_group=Moisturizers&a_brand=Nobody")
    assert len([v for v, _ in options(html, "a") if v]) == 3          # unknown brand: all brands


def test_a_big_group_needs_a_brand_before_listing_products(app, client):
    db = app.config["DATABASE"]
    with closing(get_db(db)) as conn, conn:
        conn.executemany(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, ?, 'Big', 10, '50 mL', 0.2, 'Big')",
            [(f"Item {i:04d}", "Bulk") for i in range(COMPARE_DROPDOWN_MAX + 1)],
        )
    add(db, "Rare Find", brand="Small Brand", group="Big")
    html = page(client, "/compare?a_group=Big")
    assert f"This category has {COMPARE_DROPDOWN_MAX + 2} products. Choose a brand first" in html
    assert options(html, "a") is None                                  # no product list yet
    assert options(html, "a_brand") is not None
    html = page(client, "/compare?a_group=Big&a_brand=Small+Brand")
    assert [label for v, label in options(html, "a") if v] == ["Small Brand - Rare Find (100 mL, $20.00)"]


def test_a_capped_list_says_so(app, client):
    db = app.config["DATABASE"]
    with closing(get_db(db)) as conn, conn:
        conn.executemany(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group)"
            " VALUES (?, 'Bulk', 'Big', 10, '50 mL', 0.2, 'Big')",
            [(f"Item {i:04d}",) for i in range(COMPARE_DROPDOWN_MAX + 20)],
        )
    html = page(client, "/compare?a_group=Big&a_brand=Bulk")
    assert len([v for v, _ in options(html, "a") if v]) == COMPARE_DROPDOWN_MAX
    assert f"Showing the first {COMPARE_DROPDOWN_MAX} of {COMPARE_DROPDOWN_MAX + 20} matches" in html


def test_after_choosing_a_the_b_picker_is_limited_to_a_group_without_a(shop, client):
    html = page(client, f"/compare?a={shop['m1']}")
    assert "Comparing within: <strong>Moisturizers</strong>" in html
    assert 'name="b_group"' not in html                                # no category dropdown for B
    labels = [label for v, label in options(html, "b") if v]
    assert labels == ["Glow Co - Delta Balm (100 mL, $30.00)", "Dew Labs - Echo Gel (50 mL, $10.00)"]
    assert "Bravo Cream" in html                                       # A shown as chosen...
    assert not any("Bravo Cream" in label for label in labels)         # ...but not offered again
    assert "Change" in html and f'value="{shop["m1"]}"' in html        # A is carried by the form
    assert 'name="a_group"' not in html


def test_after_choosing_b_first_the_a_picker_is_limited_to_bs_group(shop, client):
    html = page(client, f"/compare?b={shop['s1']}")
    assert "Comparing within: <strong>Face Serums</strong>" in html
    assert [label for v, label in options(html, "a") if v] == ["Dew Labs - Charlie Serum (15 mL, $15.00)"]
    assert 'name="a_group"' not in html


def test_b_picker_has_brand_and_search_inside_the_group(shop, client):
    html = page(client, f"/compare?a={shop['m1']}&b_brand=Glow+Co&b_q=balm")
    assert [v for v, _ in options(html, "b_brand") if v] == ["Dew Labs", "Glow Co"]
    assert [label for v, label in options(html, "b") if v] == ["Glow Co - Delta Balm (100 mL, $30.00)"]


def test_a_leftover_product_from_an_old_category_or_brand_is_not_a_choice(shop, client):
    # form sent without JavaScript after the category changed: a still holds the old serum
    html = page(client, f"/compare?a={shop['s1']}&a_group=Moisturizers")
    assert options(html, "a") is not None and "Change" not in html
    assert "Alpha Serum" not in html
    # same for a brand that changed
    html = page(client, f"/compare?a={shop['m1']}&a_group=Moisturizers&a_brand=Glow+Co")
    assert "Change" not in html and options(html, "a") is not None
    # a product that does match is a choice
    html = page(client, f"/compare?a={shop['m1']}&a_group=Moisturizers&a_brand=Dew+Labs")
    assert "Change" in html and "Comparing within" in html


def test_the_javascript_hook_exists_and_is_served(shop, client):
    html = page(client, "/compare?a_group=Moisturizers")
    assert 'data-autosubmit' in html and 'data-resets="a_brand a"' in html
    assert "main.js" in html
    js = client.get("/static/js/main.js").get_data(as_text=True)
    assert "data-autosubmit" in js or "[data-autosubmit]" in js
    assert "dataset.resets" in js and "form.submit()" in js


# ---------------------------------------------------------------- bad and unusual ids

@pytest.mark.parametrize("value", ["abc", "0", "-3", "1.5", " ", "", "1e3", "٣", "12abc", "0x10", "%20"])
def test_invalid_ids_are_ignored(shop, client, value):
    response = client.get("/compare", query_string={"a": value})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "find product" not in html and "Change" not in html
    assert options(html, "a_group") is not None                        # back to the category picker


def test_a_valid_but_unknown_id_gets_a_friendly_message_and_still_lets_you_pick(shop, client):
    html = page(client, "/compare?a=99999")
    assert "We couldn&#39;t find product A (id 99999)" in html or "We couldn't find product A (id 99999)" in html
    assert options(html, "a_group") is not None


def test_unknown_a_with_a_valid_b_limits_the_a_picker_to_bs_group(shop, client):
    html = page(client, f"/compare?a=99999&b={shop['m1']}")
    assert "find product A (id 99999)" in html
    assert "Comparing within: <strong>Moisturizers</strong>" in html
    assert [label for v, label in options(html, "a") if v][0].startswith("Glow Co - Delta Balm")


def test_unknown_b_still_shows_a_and_a_picker_for_b(shop, client):
    html = page(client, f"/compare?a={shop['m1']}&b=99999")
    assert "find product B (id 99999)" in html
    assert options(html, "b") is not None
    assert "cheaper per ml" not in html


def test_a_huge_id_does_not_crash(shop, client):
    html = page(client, "/compare?a=" + "9" * 40)
    assert "find product A" in html


def test_the_same_id_on_both_sides_asks_for_a_different_product(shop, client):
    m1 = shop["m1"]
    html = page(client, f"/compare?a={m1}&b={m1}")
    assert "Product A and product B are the same product. Please choose a different product for B." in html
    assert [label for v, label in options(html, "b") if v] == [
        "Glow Co - Delta Balm (100 mL, $30.00)", "Dew Labs - Echo Gel (50 mL, $10.00)",
    ]
    assert "cheaper per ml" not in html and "overlap" not in html


# ---------------------------------------------------------------- the comparison

def compare_html(client, shop, a, b):
    return page(client, f"/compare?a={shop[a]}&b={shop[b]}")


def test_same_group_shows_both_products_side_by_side(shop, client):
    html = compare_html(client, shop, "m1", "m2")
    for text in ("Bravo Cream", "Delta Balm", "Dew Labs", "Glow Co", "100 mL", "$20.00", "$30.00",
                 "$0.200", "$0.300"):
        assert text in html
    assert html.count("Moisturizers") >= 2                              # the group, per product
    headers = re.findall(r"<th[^>]*>(.*?)</th>", html)
    assert headers[:3] == ["", "Product A", "Product B"]
    assert [h for h in headers if h.startswith(("Price", "≈", "Name", "Brand", "Group", "Size"))] == [
        "Name", "Brand", "Group", "Size", "Price (USD)", "Price per ml (USD)",
    ]


def test_cheaper_per_ml_sentence_and_percentage(shop, client):
    html = compare_html(client, shop, "m1", "m2")
    assert "Bravo Cream</strong> is cheaper per ml: it costs 33.3% less per ml than Delta Balm." in html
    html = compare_html(client, shop, "m2", "m1")
    assert "Bravo Cream</strong> is cheaper per ml: it costs 33.3% less per ml than Delta Balm." in html


def test_equal_price_per_ml_says_so(shop, client):
    html = compare_html(client, shop, "m1", "m3")
    assert "Both products cost the same per ml." in html
    assert "cheaper per ml:" not in html


def test_missing_price_per_ml_shows_not_available_and_no_verdict(app, client):
    db = app.config["DATABASE"]
    a = add(db, "No Ratio", price_per_ml=None, ingredients=[("Water",)])
    b = add(db, "Has Ratio", price_per_ml=0.3, ingredients=[("Water",)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "Price per ml is not available for one or both products, so there is no price verdict." in html
    assert "Not available" in html and "cheaper per ml:" not in html
    assert "$0.300" in html                                             # the other side still shows


def test_ingredient_sets_counts_and_overlap(shop, client):
    html = compare_html(client, shop, "m1", "m2")
    assert "<strong>2</strong> shared" in html
    assert "<strong>1</strong> only in A" in html and "<strong>1</strong> only in B" in html
    assert "overlap <strong>50.0%</strong>" in html and "2 of 4 distinct ingredients" in html
    shared = html.split("Shared (2)")[1].split("Only in A")[0]
    assert "Water" in shared and "Squalane" in shared and "Glycerin" not in shared
    assert "Glycerin" in html.split("Only in A (1)")[1].split("Only in B")[0]
    assert "Niacinamide" in html.split("Only in B (1)")[1]


def test_strengths_show_for_a_shared_ingredient_only_when_both_state_one(shop, client):
    html = compare_html(client, shop, "m1", "m2")
    assert "A: 5% · B: 3% (stated by brands)" in html
    assert html.count("stated by brands") == 1                          # Water states none
    one_sided = add(client.application.config["DATABASE"], "Zinc Cream", ingredients=[("Squalane",)])
    html = page(client, f"/compare?a={shop['m1']}&b={one_sided}")
    assert "stated by brands" not in html                               # only one side states Squalane


def test_the_ingredient_note_is_shown_under_the_overlap(shop, client):
    html = compare_html(client, shop, "m1", "m2")
    assert ("Shared ingredients show what the two products have in common. They do not mean the "
            "formulas behave the same, because concentrations are mostly not published.") in html


def test_missing_ingredients_show_not_available_but_price_still_compares(app, client):
    db = app.config["DATABASE"]
    a = add(db, "No List", price_per_ml=0.2, ingredients=[])
    b = add(db, "Has List", price_per_ml=0.3, ingredients=[("Water",)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "One or both products list no ingredients." in html
    assert "cheaper per ml:" in html
    assert "overlap" not in html and "Shared ingredients show" not in html


def test_rupees_use_the_cached_rate_with_the_standard_note(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "m1", "m2")
    assert "≈ Price (₹)" in html and "≈ Price per ml (₹)" in html
    assert "₹1,800" in html and "₹2,700" in html                        # $20 and $30 at 90
    assert "₹18.00" in html and "₹27.00" in html                        # 0.2 and 0.3 per ml at 90
    assert f"Converted from US prices at 1 USD = ₹90.00 ({TODAY}). Approximate, not Indian retail prices." in html
    assert "(older rate)" not in html


def test_a_stale_rate_is_marked_older(shop, client):
    db = client.application.config["DATABASE"]
    with closing(get_db(db)) as conn, conn:
        conn.execute("INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                     " VALUES ('2026-01-02', 'USD', 'INR', 88.5, '2026-01-02')")
    html = compare_html(client, shop, "m1", "m2")                       # API is offline in tests
    assert "₹1,770" in html and "Approximate, not Indian retail prices. (older rate)" in html


def test_without_a_rate_there_is_no_rupee_anywhere(shop, client):
    html = compare_html(client, shop, "m1", "m2")                       # offline, nothing saved
    assert "₹" not in html and "Converted from" not in html and "Approximate" not in html
    assert "$20.00" in html and "$0.200" in html and "cheaper per ml:" in html


def test_the_rate_is_fetched_once_for_a_comparison(shop, client, rate_api):
    compare_html(client, shop, "m1", "m2")
    compare_html(client, shop, "m1", "m3")
    assert len(rate_api.calls) == 1


# ---------------------------------------------------------------- not comparable

def test_different_groups_show_a_message_and_facts_but_no_verdict(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = compare_html(client, shop, "m1", "s1")
    assert "Product A is in Moisturizers and product B is in Face Serums, so they can&#39;t be compared fairly." in html \
        or "Product A is in Moisturizers and product B is in Face Serums, so they can't be compared fairly." in html
    for text in ("Bravo Cream", "Alpha Serum", "Dew Labs", "Glow Co", "$20.00", "$30.00", "30 mL", "₹1,800"):
        assert text in html
    for absent in ("cheaper per ml", "Both products cost the same", "per ml (USD)", "per ml (₹)", "overlap",
                   "Shared (", "Only in A", "Shared ingredients show"):
        assert absent not in html, absent
    link = re.search(r'<a class="btn-primary" href="([^"]+)">Choose a product from Moisturizers</a>', html)
    assert link and link.group(1) == f"/compare?a={shop['m1']}"


def test_the_link_after_a_mismatch_leads_to_a_picker_in_a_group(shop, client):
    html = page(client, f"/compare?a={shop['m1']}")
    assert "Comparing within: <strong>Moisturizers</strong>" in html


def test_a_mini_size_product_has_no_group_and_cannot_be_compared(shop, client):
    html = compare_html(client, shop, "mini", "m1")
    assert "Product A (Mini Size) has no comparison group, so it can&#39;t be compared fairly with other products." in html \
        or "Product A (Mini Size) has no comparison group, so it can't be compared fairly with other products." in html
    assert "cheaper per ml" not in html and "overlap" not in html
    html = page(client, f"/compare?a={shop['mini']}")                   # alone: no picker for B
    assert "Mini Size" in html and "has no comparison group" in html
    assert options(html, "b") is None and options(html, "b_group") is None


def test_two_mini_size_products_are_not_the_same_group(app, client):
    db = app.config["DATABASE"]
    a = add(db, "Tiny One", group=None, category="Mini Size")
    b = add(db, "Tiny Two", group=None, category="Mini Size")
    html = page(client, f"/compare?a={a}&b={b}")
    assert "has no comparison group" in html and "cheaper per ml" not in html


def test_the_word_dupe_never_appears(shop, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    urls = ["/compare", f"/compare?a={shop['m1']}", f"/compare?a={shop['m1']}&b={shop['m2']}",
            f"/compare?a={shop['m1']}&b={shop['s1']}", f"/compare?a={shop['m1']}&b={shop['m1']}",
            "/compare?a=99999", f"/compare?a={shop['mini']}"]
    for url in urls:
        assert "dupe" not in page(client, url).lower(), url


def test_names_are_escaped(app, client):
    db = app.config["DATABASE"]
    a = add(db, "<script>alert(1)</script>", ingredients=[("Water",)])
    b = add(db, "Plain", ingredients=[("Water",)])
    html = page(client, f"/compare?a={a}&b={b}")
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_compare_works_on_an_empty_database(app, client):
    html = page(client, "/compare")
    assert options(html, "a_group") == [("", "Choose a category")]


# ---------------------------------------------------------------- links to the page

def test_detail_page_links_to_compare_with_this_product(shop, client):
    html = page(client, f"/products/{shop['m1']}")
    assert f'href="/compare?a={shop["m1"]}"' in html
    assert "Compare with another product" in html


def test_each_row_on_the_list_links_to_compare(shop, client):
    html = page(client, "/products")
    for key in ("m1", "m2", "s1", "mini"):
        assert f'<a class="row-compare" href="/compare?a={shop[key]}">Compare</a>' in html
    assert re.findall(r"<th[^>]*>(.*?)</th>", html) == ["Product", "Brand", "Category", "Size", "Price (USD)"]
