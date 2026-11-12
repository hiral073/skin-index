import html as html_lib
import re
from contextlib import closing
from datetime import date

import pytest

from database.db import get_db

TODAY = date.today().isoformat()


def add(db, name, brand, group, price, ppm, loves, rating, reviews, ingredients=()):
    with closing(get_db(db)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, compare_group,"
            " loves_count, rating, reviews) VALUES (?, ?, ?, ?, '100 mL', ?, ?, ?, ?, ?)",
            (name, brand, group or "Mini Size", price, ppm, group, loves, rating, reviews),
        ).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return pid


def save_rate(db, rate=90.0, rate_date=TODAY, fetched_on=TODAY):
    with closing(get_db(db)) as conn, conn:
        conn.execute("INSERT INTO exchange_rates (rate_date, base, quote, rate, fetched_on)"
                     " VALUES (?, 'USD', 'INR', ?, ?)", (rate_date, rate, fetched_on))


@pytest.fixture
def market(app):
    """20 products.

    Face Serums (10): price per ml 1..10, rating 3.5..4.4, 100 reviews each, likes 1,000..10,000;
      Glow Co has the six cheaper ones, Dew Labs the four dearer ones.
      Water in all, Glycerin in 8, Squalane in 1.
    Moisturizers (5, Many Products): 5.0 stars but only 5 reviews each, 100 likes each.
    Toners (4, Zeta): too few for a group view.
    One Mini Size product (Tiny Brand, no group): the most loved of all, 60,000 likes.
    """
    db = app.config["DATABASE"]
    ids = {}
    for i in range(10):
        ids[f"s{i}"] = add(
            db, f"Serum {i}", "Glow Co" if i < 6 else "Dew Labs", "Face Serums", 10.0 + i, float(i + 1),
            1000 * (i + 1), round(3.5 + i / 10, 1), 100,
            ["Water"] + (["Glycerin"] if i < 8 else []) + (["Squalane"] if i == 9 else []),
        )
    for i in range(5):
        ids[f"m{i}"] = add(db, f"Cream {i}", "Many Products", "Moisturizers", 20.0, 0.1 + i / 10, 100, 5.0, 5,
                           ["Water", "Niacinamide"])
    for i in range(4):
        ids[f"t{i}"] = add(db, f"Toner {i}", "Zeta", "Toners", 8.0, 0.2, 10, 4.0, 40, ["Water"])
    ids["mini"] = add(db, "Tiny Pot", "Tiny Brand", None, 12.0, 9.0, 60_000, 4.8, 900, ["Water"])
    return ids


def page(client, url="/insights"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def section(html, start, end=None):
    body = html.split(start, 1)[1]
    return body.split(end, 1)[0] if end else body


def labels(html):
    return [re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", x))).strip()
            for x in re.findall(r'bar-label">(.*?)</div>', html, re.S)]


def fills(html):
    return re.findall(r'class="bar-fill" style="width: ([\d.]+)%"', html)


def takeaways(html):
    body = section(html, 'class="takeaways"', "How to read this")
    return [text(li) for li in re.findall(r"<li>(.*?)</li>", body, re.S)]


GROUP = "/insights?group=Face+Serums"


# ---------------------------------------------------------------- overall view

def test_overview_tiles_are_products_and_brands_only(market, client):
    html = page(client)
    tiles = dict(re.findall(r'tile-label">([^<]*)</div>\s*<div class="tile-value">(.*?)</div>', html, re.S))
    assert {k: text(v) for k, v in tiles.items()} == {"Products": "20", "Brands": "5"}
    assert "Comparison groups" not in text(html)


@pytest.mark.parametrize("url", ["/insights", GROUP, "/insights?group=Nope"])
def test_no_median_or_lowest_highest_price_section_anywhere(market, client, url):
    t = text(page(client, url))
    for phrase in ("Median", "median", "Lowest price", "Highest price", "Minimum price", "Maximum price",
                   "Price per ml by product type", "Priciest", "Cheapest"):
        assert phrase not in t, phrase


def test_most_loved_brands_are_ranked_by_total_loves_with_bars_relative_to_the_top(market, client):
    chart = section(page(client), "Most liked brands", "Most liked products")
    names =[re.match(r"(.*?) \d+ products?", l).group(1) for l in labels(chart)]
    assert names == ["Tiny Brand", "Dew Labs", "Glow Co", "Many Products", "Zeta"]   # not by product count (Glow Co has most)
    assert fills(chart) == ["100.0", "56.7", "35.0", "0.8", "0.1"]                  # loves / 60,000
    t = text(chart)
    assert "60,000 likes" in t and "34,000 likes" in t and "21,000 likes" in t
    assert "1 product" in t and "4 products" in t and "6 products" in t and "5 products" in t


def test_brand_ratings_are_weighted_by_reviews_and_say_so(market, client):
    t = text(section(page(client), "Most liked brands", "Most liked products"))
    assert "average rating 4.80 (weighted by 900 reviews)" in t                      # Tiny Brand
    assert "average rating 4.25 (weighted by 400 reviews)" in t                      # Dew Labs: 4.1 to 4.4
    assert "average rating 3.75 (weighted by 600 reviews)" in t                      # Glow Co: 3.5 to 4.0
    assert "weighted by how many reviews each has" in t


def test_most_loved_products_table(market, client):
    html = page(client)
    table = section(html, "Most liked products", "Common ingredients")
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]
    assert len(rows) == 10                                                         # top 10 of 20
    first = text(rows[0])
    assert first.startswith("Tiny Pot Tiny Brand $12.00 4.80 from 900 reviews 60,000")
    assert text(rows[1]).startswith("Serum 9 Dew Labs $19.00 4.40 from 100 reviews 10,000")
    assert f'href="/products/{market["mini"]}"' in table and f'href="/products/{market["s9"]}"' in table
    assert fills(table)[:2] == ["100.0", "16.7"]                                    # relative to the top product
    assert "Well-reviewed" not in html and "Price per ml and rating" not in html    # group-only sections


def test_common_ingredients_overall(market, client):
    chart = section(page(client), "Common ingredients</h2>", "Key takeaways")
    assert [l for l in labels(chart)] == ["Glycerin", "Niacinamide", "Squalane"]    # no Water
    assert "<strong>40.0%</strong>" in chart and "8 of 20 products" in text(chart)
    assert "<strong>25.0%</strong>" in chart and "<strong>5.0%</strong>" in chart
    assert fills(chart) == ["40.0", "25.0", "5.0"]
    t = text(chart)
    assert "Water is left out of this ranking" in t
    assert "it is in at least 100.0% of these products (20 of 20)" in t


# ---------------------------------------------------------------- one group

def test_group_view_adapts_sections_3_to_6_and_adds_the_group_only_ones(market, client):
    html = page(client, GROUP)
    assert '<option value="Face Serums" selected>' in html
    assert "Most liked products in Face Serums" in html
    assert "Well-reviewed and lower price per ml in Face Serums" in html
    assert "Price per ml and rating in Face Serums" in html
    assert "Common ingredients in Face Serums" in html
    assert 'href="/insights">Back to the overall view</a>' in html
    loved = section(html, "Most liked products in Face Serums", "Well-reviewed")
    rows = re.findall(r"<tr>(.*?)</tr>", loved, re.S)[1:]
    assert len(rows) == 10 and text(rows[0]).startswith("Serum 9 Dew Labs")         # Tiny Pot is not a Face Serum
    assert "Tiny Pot" not in loved


def test_the_brand_chart_stays_overall_in_the_group_view(market, client):
    chart = section(page(client, GROUP), "Most liked brands", "Most liked products")
    assert "Tiny Brand" in chart and "Zeta" in chart


def test_well_reviewed_list_states_the_thresholds_and_sorts_by_price_per_ml(market, client):
    html = page(client, GROUP)
    block = section(html, "Well-reviewed and lower price per ml", "Price per ml and rating")
    assert "at least 50 reviews and a rating of at least 4.0" in text(block)
    assert "5 products in Face Serums meet both." in text(block)
    rows = re.findall(r"<tr>(.*?)</tr>", block, re.S)[1:]
    assert [text(r).split(" ")[0] + " " + text(r).split(" ")[1] for r in rows] == [f"Serum {i}" for i in range(5, 10)]
    assert text(rows[0]).startswith("Serum 5 Glow Co $6.000 $15.00 4.00 from 100 reviews")
    assert "Serum 4" not in block                                                   # rating 3.9 is below 4.0


def test_price_bands_show_the_weighted_rating_and_count_of_each(market, client):
    block = section(page(client, GROUP), "Price per ml and rating in Face Serums", "Common ingredients in")
    assert [re.sub(r" average rating.*", "", l) for l in labels(block)] == [
        "Lower price per ml n=4", "Middle price per ml n=3", "Higher price per ml n=3"]
    t = text(block)
    assert "3.65 average rating, 400 reviews" in t
    assert "4.00 average rating, 300 reviews" in t
    assert "4.30 average rating, 300 reviews" in t
    assert fills(block) == ["73.0", "80.0", "86.0"]                                 # rating / 5
    assert "This shows a pattern in these products, not a cause." in t
    assert "at least 10 reviews" in t and "three equal-size bands" in t


def test_a_group_with_too_little_review_data_says_not_enough_data(market, client):
    html = page(client, "/insights?group=Moisturizers")
    block = section(html, "Well-reviewed and lower price per ml", "Common ingredients in")
    assert block.count("Not enough data") == 2                                      # list and bands
    assert "At least 9 products with a price per ml and 10 or more reviews are needed." in text(block)
    assert "Cream 0" in section(html, "Most liked products in Moisturizers", "Well-reviewed")   # loves still shown


def test_ingredients_in_a_group(market, client):
    chart = section(page(client, GROUP), "Common ingredients in Face Serums", "Key takeaways")
    assert labels(chart) == ["Glycerin", "Squalane"]
    assert "<strong>80.0%</strong>" in chart and "<strong>10.0%</strong>" in chart
    assert "8 of 10 products" in text(chart)
    assert "Niacinamide" not in chart


def test_groupless_products_are_left_out_of_group_views(market, client):
    html = page(client, GROUP)
    assert "Tiny Pot" not in section(html, "Most liked products in", "Well-reviewed")
    assert "Tiny Pot" not in html.split("Most liked brands")[1].split("Most liked products")[1]


# ---------------------------------------------------------------- takeaways

def test_overall_takeaways_use_the_computed_numbers(market, client):
    assert takeaways(page(client)) == [
        "Tiny Brand has the most likes (60,000) from its 1 product, with a review-weighted average rating of 4.80.",
        "The most liked product is Tiny Pot by Tiny Brand (60,000 likes).",
        "After water, the most common ingredient is Glycerin, found in 40.0% of products (8 of 20).",
    ]


def test_group_takeaways_include_the_bands_and_the_well_reviewed_count(market, client):
    assert takeaways(page(client, GROUP)) == [
        "Across all products, Tiny Brand has the most likes (60,000) from its 1 product, with a "
        "review-weighted average rating of 4.80.",
        "The most liked product in Face Serums is Serum 9 by Dew Labs (10,000 likes).",
        "After water, the most common ingredient is Glycerin, found in 80.0% of products (8 of 10).",
        "In Face Serums, products in the lower, middle and higher price-per-ml bands have review-weighted "
        "average ratings of 3.65, 4.00 and 4.30 (n=4, 3 and 3); this shows a pattern, not a cause.",
        "5 products in Face Serums have at least 50 reviews and a rating of at least 4.0.",
    ]


def test_a_group_without_enough_data_gets_only_the_takeaways_it_can_support(market, client):
    got = takeaways(page(client, "/insights?group=Moisturizers"))
    assert len(got) == 3 and not any("price-per-ml bands" in s or "at least 50 reviews" in s for s in got)


BANNED = ["best-selling", "best selling", "bestsell", "best seller", "most sold", "sold", "sales", "selling",
          "popular", "effective", "best", "worst", "better", "worse", "quality", "works", "good", "bad",
          "recommend", "should", "superior", "cure", "treat", "safe", "results", "proven"]


@pytest.mark.parametrize("url", ["/insights", GROUP, "/insights?group=Moisturizers", "/insights?group=Nope"])
def test_takeaways_use_engagement_wording_never_sales_or_quality_claims(market, client, url):
    for sentence in takeaways(page(client, url)):
        assert not any(word in sentence.lower() for word in BANNED), sentence


def test_the_page_never_says_best_selling_or_most_sold(market, client):
    for url in ("/insights", GROUP):
        t = text(page(client, url)).lower()
        for phrase in ("best-selling", "best selling", "bestseller", "most sold", "top seller", "best seller"):
            assert phrase not in t, phrase


def test_how_to_read_this(market, client):
    t = text(section(page(client), "How to read this"))
    assert "Likes, reviews and ratings show shopper engagement on one retailer's website. They are not sales figures." in t
    assert "Older products have had more time to collect likes and reviews." in t
    assert ("Ratings with few reviews are ignored: the well-reviewed list needs at least 50 reviews and the "
            "price bands need at least 10. Brand averages are weighted by review count.") in t
    assert "Prices are US prices and are approximate." in t
    save_rate(client.application.config["DATABASE"])
    assert "Prices are US prices converted at the rate shown below and are approximate." in text(
        section(page(client), "How to read this"))


# ---------------------------------------------------------------- rupees

def test_rupees_on_product_prices_with_a_rate(market, client):
    save_rate(client.application.config["DATABASE"], 90.0)
    html = page(client)
    t = text(section(html, "Most liked products", "Common ingredients"))
    assert "$12.00 (≈ ₹1,080)" in t and "$19.00 (≈ ₹1,710)" in t
    assert f"Converted from US prices at 1 USD = ₹90.00 ({TODAY}). Approximate, not Indian retail prices." in text(html)
    block = text(section(page(client, GROUP), "Well-reviewed and lower price per ml", "Price per ml and rating"))
    assert "$6.000 (≈ ₹540.00)" in block and "$15.00 (≈ ₹1,350)" in block


def test_a_stale_rate_is_marked_older(market, client):
    save_rate(client.application.config["DATABASE"], 88.5, rate_date="2026-01-02", fetched_on="2026-01-02")
    t = text(page(client))                                                          # API is offline in tests
    assert "₹1,062" in t and "Approximate, not Indian retail prices. (older rate)" in t


def test_no_rate_means_no_rupees_anywhere(market, client):
    for url in ("/insights", GROUP):
        html = page(client, url)
        assert "₹" not in html and "Converted from" not in html
    assert "$12.00" in page(client)


def test_the_rate_is_fetched_once_and_not_for_an_empty_database(app, client, rate_api):
    page(client)
    assert rate_api.calls == []
    add(app.config["DATABASE"], "p", "B", "Serums", 10.0, 1.0, 5, 4.5, 20)
    page(client)
    page(client, "/insights?group=Serums")
    assert len(rate_api.calls) == 1


# ---------------------------------------------------------------- selector

def test_selector_lists_groups_with_five_or_more_products(market, client):
    form = section(page(client), '<form class="filter-bar"', "</form>")
    assert re.findall(r'<option value="([^"]*)"[^>]*>(.*?)</option>', form) == [
        ("", "All product types (overall view)"), ("Face Serums", "Face Serums (10)"), ("Moisturizers", "Moisturizers (5)"),
    ]
    assert ">Show</button>" in form and "data-autosubmit" in form and 'method="get"' in form
    js = client.get("/static/js/main.js").get_data(as_text=True)
    assert "data-autosubmit" in js and "form.submit()" in js


@pytest.mark.parametrize("value", ["Nope", "Toners", "face serums", "%", "' OR 1=1 --",
                                   "x'; DROP TABLE products; --", "<script>alert(1)</script>"])
def test_an_invalid_or_too_small_group_falls_back_to_the_overall_view(market, client, value):
    html = client.get("/insights", query_string={"group": value}).get_data(as_text=True)
    assert "Most liked brands" in html and "Well-reviewed" not in html and "Price per ml and rating" not in html
    assert "We couldn't show that product type" in html_lib.unescape(html)
    assert "Only types with at least 5 products can be shown." in html
    assert "<script>alert(1)</script>" not in html
    assert client.get("/insights").status_code == 200


def test_a_blank_group_is_just_the_overall_view_without_a_message(market, client):
    html = page(client, "/insights?group=")
    assert "this is the overall view" not in html and "Most liked brands" in html


# ---------------------------------------------------------------- empty, tiny, missing data

def test_an_empty_database_page_loads_with_not_enough_data(app, client):
    html = page(client)
    assert html.count("Not enough data") >= 4                                       # brands, products, ingredients, takeaways
    tiles = dict(re.findall(r'tile-label">([^<]*)</div>\s*<div class="tile-value">(.*?)</div>', html, re.S))
    assert {k: text(v) for k, v in tiles.items()} == {"Products": "0", "Brands": "0"}
    assert "₹" not in html and "How to read this" in html
    assert "this is the overall view" in page(client, "/insights?group=Serums")


def test_a_single_product_database_loads(app, client):
    add(app.config["DATABASE"], "Only", "Solo", "Serums", 12.0, 0.12, 50, 4.5, 20, ["Water", "Glycerin"])
    t = text(page(client))
    assert "Solo" in t and "Only Solo" in t and "50 likes" in t
    assert takeaways(page(client))[0].startswith("Solo has the most likes (50) from its 1 product")


def test_products_with_no_popularity_data_do_not_break_the_page(app, client):
    db = app.config["DATABASE"]
    for i in range(12):
        add(db, f"Plain {i}", "Quiet", "Serums", 10.0, None, None, None, None, ["Water"])
    for url in ("/insights", "/insights?group=Serums"):
        html = page(client, url)
        assert "Not enough data" in html
    assert "Plain 0" not in text(page(client))                                      # nothing to rank by


def test_a_most_loved_product_without_a_rating_says_not_available(app, client):
    add(app.config["DATABASE"], "No rating", "B", "Serums", 10.0, 1.0, 500, None, None)
    row = section(page(client), "Most liked products", "Common ingredients")
    assert "Not available" in row and "No rating" in row


def test_names_are_escaped(app, client):
    db = app.config["DATABASE"]
    for i in range(5):
        add(db, f"<b>p{i}</b>", "<i>Evil</i>", "<u>Group</u>", 10.0, 1.0, 10, 4.5, 20, ["<script>x</script>"])
    html = page(client)
    for raw in ("<b>p0</b>", "<i>Evil</i>", "<u>Group</u>", "<script>x</script>"):
        assert raw not in html
    assert "&lt;i&gt;Evil&lt;/i&gt;" in html


def test_the_page_is_linked_from_the_navigation(app, client):
    assert 'href="/insights"' in page(client, "/")
