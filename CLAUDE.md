# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Skin Index: Flask app for exploring skincare products (ingredients, price per ml, product comparison, brand price insights, skin-type tags) with a few live-data pages (daily conditions, research). Built step by step per the Roadmap below. Stack: Python, Flask, SQLite, pandas, plain HTML/CSS/JS, pytest.

## Commands (Windows PowerShell)

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m database.load_data   # (re)load data/product_info.csv into skin_index.db; empties the 3 tables first
python app.py                  # dev server, http://localhost:5001 (debug=True)
pytest                         # all tests
pytest tests/test_routes.py::test_landing_page_loads   # single test
```

No linter or build step configured. Two virtualenvs exist in the tree (`venv/`, `.venv/`); README and `.gitignore` use `venv/`.

## Scope

MVP pages:
- Products, with search, category filter and skin-type filter
- Product detail
- Compare
- Insights

Live-data pages: Today (weather, UV, air quality) and Research (PubMed).

Later: an MCP server over the same data.

Still out of scope: login, an in-app AI assistant, Indian product data. INR is only a display conversion of the USD prices already in the dataset, not Indian product data.

## Roadmap

Steps 1-7 are done. Build one step at a time, in this order:

1. Database setup (SQLite) — done
2. Load and clean the dataset (pandas) — done
3. Product search — done
4. Currency: INR display — done
5. Product detail — done
   - 5b. Stated ingredient strengths (`stated_percent`) — done
6. Compare — done
7. Insights — done
8. Skin-type tags and filter
9. Today page (Open-Meteo weather, UV, AQI)
10. Research page (PubMed)
11. MCP server

## Architecture

- `app.py`: single Flask app, module-level `app`. `/` renders `landing.html`; `/products` is the real search page (`products.html`) and `/products/<int:id>` is the real detail page (`product_detail.html`). `/compare` is the real compare page (`compare.html`). `/insights` is the real insights page (`insights.html`). No placeholder routes are left; later steps add routes (Today, Research), and templates/nav link to routes via `url_for('products')` etc., so keep the endpoint function names.
- `/insights?group=<name>`: computed from the database only (the one outside call is the cached rate service, for rupee values on product prices). It is about shopper engagement (loves, ratings, reviews from the retailer's site, not sales) and ingredients; there are no median or min/max price sections. Sections: overview tiles (products, brands, comparison groups); most loved brands (top 10 by total `loves_count`, with product count and a review-weighted average rating; bars relative to the top brand; always overall); most loved products (top 10 by loves, overall or within the group: name linked to its detail page, brand, price in USD and `≈ ₹`, rating and reviews); group only: well-reviewed and lower price per ml (at least 50 reviews and a rating of at least 4.0, sorted by price per ml ascending, top 10, thresholds stated on the page) and price vs rating (products with a price per ml and at least 10 reviews split into three equal-size bands by price per ml, each with its review-weighted average rating and n, plus the note that this shows a pattern, not a cause; needs at least 9 such products, else "Not enough data"); common ingredients (top 10 by share of products, Water in a note); key takeaways; a "How to read this" note. The selector lists groups with at least 5 products (GET form, visible Show button, `data-autosubmit`); an unknown or too-small group shows the overall view with a small message. Products with no comparison group are excluded from group views. Bars are plain HTML/CSS with percentage widths computed in `app.py` (ratings on a 0-5 scale, ingredient shares on 0-100). Sections without data show "Not enough data".
- `/products/<int:id>`: name, brand, category, size, price in USD and `≈ ₹` (same rate service, rounding and note as the list), price per ml in USD and `≈ ₹` per ml, and the numbered ingredient list in label order (`position`); an ingredient with a stated strength shows "12.025% (stated by brand)" (the `percent` template filter), and a product with any shows the note "Only some brands state strengths. A missing percentage means not stated, not low." Anything missing shows "Not available". An unknown id gives a 404 page (`404.html`, extends `base.html`, link back to `/products`); the app-wide `@app.errorhandler(404)` renders it for every 404. The list links each name to the detail page and adds the current `q`, `category`, `sort` and `page` (defaults left out) to the link; the detail page rebuilds its "Back to results" link from only those four keys (`list_args()` in `app.py`), so unknown or invalid params are dropped.
- `/compare?a=<id>&b=<id>`: ids must be plain positive integers, anything else is ignored. Each missing side gets a GET-form picker: Category dropdown (groups with at least two products), optional Brand dropdown, a small search box, and a Product dropdown labelled "Brand - Name (size, $price)", with a visible "Show" button; `static/js/main.js` auto-submits dropdowns marked `data-autosubmit` and empties the fields below the one that changed (`data-resets`). Once one side is chosen, the other side's picker lists only that product's group (no category dropdown, "Comparing within: <group>") and leaves the chosen product out. A product left over from an earlier category or brand (`a_group`, `a_brand` in the URL not matching it) is treated as not chosen, so the page also works without JavaScript. Both chosen and in the same group: side-by-side facts (USD and `≈ ₹`, price per ml in both), which is cheaper per ml and by what percentage (how much less it costs than the dearer one), then shared / only-A / only-B ingredients with counts, the overlap percentage and the sentence that shared ingredients do not mean the formulas behave the same. Not the same group (or a product with no group): the message "Product A is in X and product B is in Y, so they can't be compared fairly.", both products' basic facts, and no verdict, no per-ml figures and no overlap. Unknown id, same id on both sides, missing price per ml or missing ingredients each have their own message or "Not available". Never use the word "dupe". The detail page links to `/compare?a=<id>` and each `/products` row has a "Compare" link inside the product cell.
- `/products`: filters, sort and paging come from query args (`q`, `category`, `sort`, `page`; 24 per page). The database path is `app.config["DATABASE"]` (defaults to `database.db.DB_PATH`), so tests can point it at a temporary database. Columns: Product, Brand, Category, Size, Price (USD), and `≈ Price (₹)` (whole rupees, comma thousands separators) with a rate note under the table; with no rate, INR is not shown at all. Price per ml is not a column here, but it is still stored and still a sort option (`sort=price_per_ml`); `sort=price` sorts by the actual price.
- `templates/`: `base.html` (navbar, Google Fonts, `{% block title %}`, `{% block head %}`, content blocks) is extended by page templates.
- `database/db.py`: `get_db(db_path=None)` (Row factory, foreign keys on), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()` (5 sample products, no-op if products exist). Tables: `products`, `ingredients`, `product_ingredients` (`position` = label order), `exchange_rates` (`rate_date` = date the source publishes for, `fetched_on` = day we saved it; unique per base, quote, rate_date). `products.compare_group` is the comparison group (see Comparison rules); `products.loves_count`, `rating` and `reviews` (nullable) are the retailer's shopper engagement numbers. `init_db()` adds these columns, like `stated_percent`, to older databases (run the loader to fill them). Prices are stored in USD (`price`, `price_per_ml`). The loader empties only the three product tables, so saved rates survive a reload.
- `database/services.py`: service functions shared by pages and later the MCP server. `get_usd_inr_rate(db_path=None, today=None)` returns `RateInfo(rate, rate_date, stale)` or `None`: a rate fetched today is reused with no network call; otherwise it fetches and saves; if the fetch fails it returns the newest saved rate with `stale=True`. After a failed fetch it does not retry for 15 minutes, so an outage cannot slow every page load. It calls `init_db()` first so older databases get the `exchange_rates` table. `get_product_detail(product_id, db_path=None)` returns one product as a plain dict whose `ingredients` are `{"name", "stated_percent"}` dicts in label order (`stated_percent` is the brand's printed number or `None`, unformatted), or `None` for an unknown id; the MCP server should reuse it. `inr_price(price_usd, rate)` gives whole rupees (halves round up) and is what `/products` shows; `inr_per_ml(price_per_ml_usd, rate)` rounds to 2 decimals and is used by the detail and compare pages. Compare: `compare_products(a_id, b_id)` returns plain data only (both products, per-side state `not chosen`/`unknown`/`found`, a `status` of `waiting`/`same_product`/`no_group`/`different_groups`/`ok`, a `comparable` flag, both groups, and, only when comparable, the price-per-ml verdict and the shared / only-A / only-B ingredients with both sides' stated strengths); `list_groups()`, `list_brands_in_group(group)` and `list_products_in_group(group, brand, q, exclude_id)` feed the dropdowns (a group over `COMPARE_DROPDOWN_MAX` = 300 products lists nothing until a brand is chosen; no list is longer than 300). The MCP server should reuse all of these. `get_insights(group=None, db_path=None)` returns the numbers for the Insights page as plain data (no formatting, HTML or currency): `config` (`INSIGHTS_CONFIG`, the one block of thresholds: 5 products per group, top 10, 50 reviews and rating 4.0 for the well-reviewed list, 10 reviews and 9 products for the price bands), overview, selector groups, brands (overall), loved products (overall or in the group), and for a valid group `well_reviewed` and `price_bands`, plus ingredient shares with Water apart; `group_status` is `none`, `ok` or `unavailable`. `weighted_rating(pairs)` is sum(rating × reviews) ÷ sum(reviews), skipping products missing either value. A product missing a value a section needs is skipped by that section, never counted as zero. Ties are broken by name; bands are equal in size (the extra product goes to the lower bands first, equal prices ordered by id). The takeaway sentences are built in `app.py` from that data.
- `live/currency.py`: `fetch_usd_inr()` is the only code that calls the network for rates (Frankfurter `https://api.frankfurter.dev/v1/latest`, no key, `requests`, 5 second timeout). It raises `CurrencyError` with a plain message on any failure. Frankfurter lists v1 as deprecated but available indefinitely (v2 is the documented current API); only this function needs to change if v1 goes away.
- `database/load_data.py`: pandas loader for `data/product_info.csv` (Skincare rows only; sizes converted to `size_ml`; ingredient lists split into the two ingredient tables; drop reasons printed). Cleaning helpers (`parse_size_ml`, `split_ingredients`, `parse_strength`, `parse_ingredients`, `clean_products`) are unit-tested without the CSV. It also reads `tertiary_category` to set each product's `compare_group` (see Comparison rules) and prints a group report (fallbacks, products with no group, big groups, groups with one product, renamed groups), and reads `loves_count`, `rating` and `reviews` (blank stays NULL) with a report of how many are filled and their ranges.
- Stated strengths (`product_ingredients.stated_percent`, nullable, must be above 0 and below 100; `init_db()` adds the column to older databases): for Skincare products outside the secondary categories "Value & Gift Sets" and "Mini Size" only, `parse_strength` splits a percentage the brand printed off an ingredient piece in exactly three formats: trailing (`Salicylic Acid 2.0%`, `... 15 %`), parenthesised (`Zinc Oxide (12.025%)`, `Ceramide Np(0.2%)`) and leading (`3% Procapil`). The cleaned name then goes through the Water alias map, so `Zinc Oxide 20%` and `Zinc Oxide` are one ingredient. Ignored and left exactly as written: values of 100 or more or 0 or below, and colon-style compounds (`Name : 0.0408%`). Anything else containing a `%` is ambiguous and also left unchanged: a word after the %, glued text (`6.90%Water`), several strengths in one piece, a range (`13.20 - 14.00 %`), a limit (`less than 1%`), a name that is part of a sentence or heading. When an ingredient name repeats, the first position is kept and takes the strength if it has none. The loader prints a report (counts, 30 varied examples, every ambiguous case, merged duplicates). Gift-set and mini-size products keep their raw names, so a `%` can still sit inside an ingredient name there.
- `data/`: `data/*.csv` and `data/*.parquet` are gitignored, as is `skin_index.db`. The CSV must be present locally to run the loader.
- `tests/conftest.py`: inserts project root into `sys.path`, imports `app` from `app.py`, and defines the `app` fixture (sets `TESTING=True` and gives each test its own empty temporary database via `app.config["DATABASE"]`). An autouse fixture replaces `live.currency.requests.get` with a call that fails like an outage, so no test reaches the network and by default no rate exists; the `rate_api` fixture patches it with a controllable fake. `pytest-flask` supplies the `client` fixture from it. `test_routes.py` asserts every page (`/`, `/products`, `/compare`, `/insights`) loads on an empty database; add new pages to that list.

## Architecture rules

- All external HTTP calls live in a `live/` package and use `requests`. Every call has a timeout, a cache, and a clear error message the page can show.
- Routes and MCP tools never call external APIs directly. They call service functions.
- Tests never use the real network. Fake or stub the `live/` functions.
- SQL is parameterized only. Never build SQL text from request or tool input.
- Sort columns come from a whitelist of known keys; an unknown key falls back to the default.

## Data rules

- Prices are stored in USD.
- INR is derived at display time from the cached daily exchange rate. It is labeled approximate and shows the rate date.
- If today's rate cannot be fetched, use the last saved rate with its date. If no rate was ever saved, hide INR.
- Ingredient strengths are shown only when the brand printed them on the label: stored as `stated_percent`, shown as "12.025% (stated by brand)". Never infer, estimate or compute a concentration (not from list position, not from other products), and never treat a missing percentage as low or zero. Ambiguous text is left unchanged and reported, not guessed.

## Comparison rules

- A product's comparison group is the most specific category level the data has: the third level (`tertiary_category`, for example "Face Serums"), else the second level (`secondary_category`, for example "Lip Balms & Treatments"). Two products are comparable only if they have the same group.
- Mini Size and Value & Gift Sets products have no group: they mix every kind of product, so they are never compared (the page says they can't be compared fairly). No Value & Gift Sets product is in the database today, because the size rules dropped them all.
- A third-level name that appears under more than one second-level category is made unique by putting the second level in front, for example "High Tech Tools › Anti-Aging" and "Shop by Concern › Anti-Aging" (today the only such name). Names are checked across the whole Skincare CSV, so a group's name does not change when some of its products are dropped.
- A fallback product whose second-level name equals a third-level name joins that group (the one Moisturizers product with no third level is in "Moisturizers"). Groups with fewer than two products are not offered in the picker.
- Cheaper per ml is (dearer − cheaper) ÷ dearer × 100. Ingredient overlap is shared ÷ all distinct ingredients across both products × 100, matched by ingredient row. Stated strengths are shown only when both products state one for the same shared ingredient; they are never worked out. Shared ingredients are not a claim that two formulas behave the same.

## Insights rules

- Popularity means shopper engagement from one retailer's site: loves, reviews and ratings. There is no sales data. Say "most loved" or "most reviewed"; never "best-selling", "most sold", "bestseller" or anything about sales. Tests check the takeaways against a list of such words.
- Everything on the page is computed from the data and worded neutrally: numbers, never claims about effectiveness or quality. The price-vs-rating bands show a pattern, not a cause.
- Weighted average rating = sum(rating × reviews) ÷ sum(reviews). Ratings with few reviews are ignored where it matters: the well-reviewed list needs at least 50 reviews and a rating of at least 4.0, the price bands at least 10 reviews. Old products have had more time to collect loves and reviews, and the page says so.
- No median or min/max price sections on this page. Water is shown in a note, not in the ingredient ranking; its share is "at least" because names like "Purified Water" are separate ingredients.

## Skin-type rules

- Tags are ingredient-based and conservative.
- Tag a product only when there is a clear positive signal and no conflicting ingredient.
- Always return the reasons for a tag, not just the tag.
- Wording is "contains ...", never "treats" or "safe for".
- Pages that show skin-type tags carry a not-medical-advice note.

## Research rules

- Show PubMed titles, journals, years and links only.
- Make no claim that a product works.
- Stay under 3 requests per second to PubMed.

## MCP rules

- The MCP server opens the database read-only.
- MCP tools call the same service functions as the pages.

## Project rules
- Stack: Flask, SQLite (sqlite3), pandas, pytest, plus `requests` for HTTP in `live/`. No other frameworks.
- Windows: activate venv with .\venv\Scripts\Activate.ps1, app runs on port 5001.
- Build one step at a time (Steps 1-11 in the Roadmap and README). Do not start later steps.
- After every change, run pytest and show the result.
- Keep the light pink theme and the existing file structure.
