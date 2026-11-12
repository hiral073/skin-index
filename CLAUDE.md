# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Skin Index: Flask app for exploring skincare products (ingredients, price per ml, product comparison, shopper-engagement insights) with live-data pages (today's UV, humidity and air quality; research) and, later, ingredient tools. It informs and never recommends (see Claims and safety rules). Built step by step per the Roadmap below. Stack: Python, Flask, SQLite, pandas, plain HTML/CSS/JS, pytest.

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
- Products, with search and category filter (the avoid-list exclude filter comes with Step 12c)
- Product detail
- Compare
- Insights

Live-data pages: Today (UV, humidity and US AQI as information, an attributed "Sun protection today" card and attributed weather-based skin-care tips) and Research (PubMed).

Later: an MCP server over the same data (Step 11), then Ingredient Intelligence (Step 12) and engineering polish (Step 13).

Still out of scope: login, an in-app AI assistant, Indian product data, product recommendations, and skin-type or skin-concern advice. INR is only a display conversion of the USD prices already in the dataset, not Indian product data.

## Roadmap

Steps 1-7 and 9 are done (there is no Step 8). Build one step at a time, in this order:

1. Database setup (SQLite) — done
2. Load and clean the dataset (pandas) — done
3. Product search — done
4. Currency: INR display — done
5. Product detail — done
   - 5b. Stated ingredient strengths (`stated_percent`) — done
6. Compare — done
7. Insights — done
8. Dropped (no step 8)
9. Today page: live UV (with an hourly timeline), humidity and US AQI from Open-Meteo, shown as information, plus a "Sun protection today" card (dermatologist and WHO guidance, attributed) and attributed weather-based skin-care tips. Links go only to category lists; no product recommendations. — done
10. Research page (PubMed)
11. MCP server: tools for search, compare, insights, weather and the avoid-list check. No skin-type tool.
12. Ingredient Intelligence
    - 12a. Ingredient-name normalizer: map names to canonical names with exact, alias and fuzzy matching, and report the match rate.
    - 12b. Official ingredient functions, and "has an EU restriction, see CosIng" notes, from the EU CosIng database. Only after checking its data-use terms.
    - 12c. "My avoid list" checker and a `/products` exclude filter, including common aliases such as Parfum/Fragrance and an optional EU fragrance-allergen list.
13. Engineering polish: GitHub Actions CI, a test hook, a claims-reviewer skill or subagent, an automated test that scans templates for medical-claim wording, README and screenshots.

## Architecture

- `app.py`: single Flask app, module-level `app`. `/` renders `landing.html`; `/products` is the real search page (`products.html`) and `/products/<int:id>` is the real detail page (`product_detail.html`). `/compare` is the real compare page (`compare.html`). `/insights` is the real insights page (`insights.html`). `/today` is the real Today page (`today.html`). No placeholder routes are left; later steps add routes (Research), and templates/nav link to routes via `url_for('products')` etc., so keep the endpoint function names.
- `/insights?group=<name>`: computed from the database only (the one outside call is the cached rate service, for rupee values on product prices). It is about shopper engagement (likes, ratings, reviews from the retailer's site, not sales) and ingredients; there are no median or min/max price sections. Sections: overview tiles (products and brands; no comparison groups tile); most liked brands (top 10 by total `loves_count`, with product count and a review-weighted average rating; bars relative to the top brand; always overall); most liked products (top 10 by likes, overall or within the group: name linked to its detail page, brand, price in USD and `≈ ₹`, rating and reviews); group only: well-reviewed and lower price per ml (at least 50 reviews and a rating of at least 4.0, sorted by price per ml ascending, top 10, thresholds stated on the page) and price vs rating (products with a price per ml and at least 10 reviews split into three equal-size bands by price per ml, each with its review-weighted average rating and n, plus the note that this shows a pattern, not a cause; needs at least 9 such products, else "Not enough data"); common ingredients (top 10 by share of products, Water in a note); key takeaways; a "How to read this" note. The selector lists groups with at least 5 products (GET form, visible Show button, `data-autosubmit`); an unknown or too-small group shows the overall view with a small message. Products with no comparison group are excluded from group views. Bars are plain HTML/CSS with percentage widths computed in `app.py` (ratings on a 0-5 scale, ingredient shares on 0-100). Sections without data show "Not enough data".
- `/products/<int:id>`: name, brand, category, size, price in USD and `≈ ₹` (same rate service, rounding and note as the list), price per ml in USD and `≈ ₹` per ml, and the numbered ingredient list in label order (`position`); an ingredient with a stated strength shows "12.025% (stated by brand)" (the `percent` template filter), and a product with any shows the note "Only some brands state strengths. A missing percentage means not stated, not low." Anything missing shows "Not available". An unknown id gives a 404 page (`404.html`, extends `base.html`, link back to `/products`); the app-wide `@app.errorhandler(404)` renders it for every 404. The list links each name to the detail page and adds the current `q`, `category`, `sort` and `page` (defaults left out) to the link; the detail page rebuilds its "Back to results" link from only those four keys (`list_args()` in `app.py`), so unknown or invalid params are dropped.
- `/compare?a=<id>&b=<id>`: ids must be plain positive integers, anything else is ignored. Each missing side gets a GET-form picker: Category dropdown (groups with at least two products), optional Brand dropdown, a small search box, and a Product dropdown labelled "Brand - Name (size, $price)", with a visible "Show" button; `static/js/main.js` auto-submits dropdowns marked `data-autosubmit` and empties the fields below the one that changed (`data-resets`). Once one side is chosen, the other side's picker lists only that product's group (no category dropdown, "Comparing within: <group>") and leaves the chosen product out. A product left over from an earlier category or brand (`a_group`, `a_brand` in the URL not matching it) is treated as not chosen, so the page also works without JavaScript. Both chosen and in the same group: side-by-side facts (USD and `≈ ₹`, price per ml in both), which is cheaper per ml and by what percentage (how much less it costs than the dearer one), then shared / only-A / only-B ingredients with counts, the overlap percentage and the sentence that shared ingredients do not mean the formulas behave the same. Not the same group (or a product with no group): the message "Product A is in X and product B is in Y, so they can't be compared fairly.", both products' basic facts, and no verdict, no per-ml figures and no overlap. Unknown id, same id on both sides, missing price per ml or missing ingredients each have their own message or "Not available". Never use the word "dupe". The detail page links to `/compare?a=<id>` and each `/products` row has a "Compare" link inside the product cell.
- `/products`: filters, sort and paging come from query args (`q`, `category`, `sort`, `page`; 24 per page). The database path is `app.config["DATABASE"]` (defaults to `database.db.DB_PATH`), so tests can point it at a temporary database. Columns: Product, Brand, Category, Size, Price (USD), and `≈ Price (₹)` (whole rupees, comma thousands separators) with a rate note under the table; with no rate, INR is not shown at all. Price per ml is not a column here, but it is still stored and still a sort option (`sort=price_per_ml`); `sort=price` sorts by the actual price.
- `templates/`: `base.html` (navbar, Google Fonts, `{% block title %}`, `{% block head %}`, content blocks) is extended by page templates.
- `database/db.py`: `get_db(db_path=None)` (Row factory, foreign keys on), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()` (5 sample products, no-op if products exist). Tables: `products`, `ingredients`, `product_ingredients` (`position` = label order), `exchange_rates` (`rate_date` = date the source publishes for, `fetched_on` = day we saved it; unique per base, quote, rate_date). `products.compare_group` is the comparison group (see Comparison rules); `products.loves_count`, `rating` and `reviews` (nullable) are the retailer's shopper engagement numbers. `init_db()` adds these columns, like `stated_percent`, to older databases (run the loader to fill them). Prices are stored in USD (`price`, `price_per_ml`). The loader empties only the three product tables, so saved rates survive a reload.
- `database/services.py`: service functions shared by pages and later the MCP server. `get_usd_inr_rate(db_path=None, today=None)` returns `RateInfo(rate, rate_date, stale)` or `None`: a rate fetched today is reused with no network call; otherwise it fetches and saves; if the fetch fails it returns the newest saved rate with `stale=True`. After a failed fetch it does not retry for 15 minutes, so an outage cannot slow every page load. It calls `init_db()` first so older databases get the `exchange_rates` table. `get_product_detail(product_id, db_path=None)` returns one product as a plain dict whose `ingredients` are `{"name", "stated_percent"}` dicts in label order (`stated_percent` is the brand's printed number or `None`, unformatted), or `None` for an unknown id; the MCP server should reuse it. `inr_price(price_usd, rate)` gives whole rupees (halves round up) and is what `/products` shows; `inr_per_ml(price_per_ml_usd, rate)` rounds to 2 decimals and is used by the detail and compare pages. Compare: `compare_products(a_id, b_id)` returns plain data only (both products, per-side state `not chosen`/`unknown`/`found`, a `status` of `waiting`/`same_product`/`no_group`/`different_groups`/`ok`, a `comparable` flag, both groups, and, only when comparable, the price-per-ml verdict and the shared / only-A / only-B ingredients with both sides' stated strengths); `list_groups()`, `list_brands_in_group(group)` and `list_products_in_group(group, brand, q, exclude_id)` feed the dropdowns (a group over `COMPARE_DROPDOWN_MAX` = 300 products lists nothing until a brand is chosen; no list is longer than 300). The MCP server should reuse all of these. `get_today_conditions(city=None, latitude=None, longitude=None, label=None)` returns the Today page's data as plain values, no HTML and no texts (status `ok`/`choose`/`no_match`/`invalid`/`unavailable`, place, choices, UV now and max with categories, humidity, temperature, AQI with category and PM2.5, `timeline` from `uv_timeline()`, `guidance` (`uv_card` of `full`/`low`/`very_low` from today's peak UV, `extra_steps` of `none`/`moderate_to_high`/`very_high`, `show_sunscreen_link`, `check_advisories`), `tips` (an empty group list, or `cool_dry` or `hot_humid`, and a headline), and a `missing` list). `TODAY_CONFIG` holds every threshold and category label: UV Low 0-2, Moderate 3-5, High 6-7, Very high 8-10, Extreme 11+; AQI Good 0-50, Moderate 51-100, Unhealthy for sensitive groups 101-150, Unhealthy 151-200, Very unhealthy 201-300, Hazardous 301+; sun-protection start UV 3, stronger steps UV 8, advisory above AQI 100; cool at or below 15 C, dry at or below 35%, hot at or above 30 C, humid at or above 60%, very-low UV below 1. UV and AQI are rounded half up to whole numbers before they get a category or are compared. `clean_place_text` accepts only letters, digits, spaces, hyphens, apostrophes, commas and full stops (2 to 60 characters; links, markup and domain-like text are refused) and `parse_coordinates` accepts only finite in-range numbers. The MCP weather tool should reuse it. `get_insights(group=None, db_path=None)` returns the numbers for the Insights page as plain data (no formatting, HTML or currency): `config` (`INSIGHTS_CONFIG`, the one block of thresholds: 5 products per group, top 10, 50 reviews and rating 4.0 for the well-reviewed list, 10 reviews and 9 products for the price bands), overview, selector groups, brands (overall), liked products (overall or in the group), and for a valid group `well_reviewed` and `price_bands`, plus ingredient shares with Water apart; `group_status` is `none`, `ok` or `unavailable`. `weighted_rating(pairs)` is sum(rating × reviews) ÷ sum(reviews), skipping products missing either value. A product missing a value a section needs is skipped by that section, never counted as zero. Ties are broken by name; bands are equal in size (the extra product goes to the lower bands first, equal prices ordered by id). The takeaway sentences are built in `app.py` from that data.
- `live/currency.py`: `fetch_usd_inr()` is the only code that calls the network for rates (Frankfurter `https://api.frankfurter.dev/v1/latest`, no key, `requests`, 5 second timeout). It raises `CurrencyError` with a plain message on any failure. Frankfurter lists v1 as deprecated but available indefinitely (v2 is the documented current API); only this function needs to change if v1 goes away.
- `/today?city=<text>` or `?lat=&lon=&label=`: live conditions for a city (see Today rules). With no arguments it shows the default place, Pune, Maharashtra, India, from fixed coordinates in `TODAY_CONFIG` (no lookup, so no choice list on first load). A city name is looked up with the Open-Meteo geocoding API: one match shows its conditions, several (up to 5) show name, region and country as links (`/today?lat=..&lon=..&label=..`), none shows a friendly message. Tiles (information only, no advice): UV now and today's max with their category, humidity, temperature, US AQI with its category and PM2.5; AQI above Moderate adds only "Check your local health advisories". Once a place is resolved (even if the live services are down) the page shows, in this order: (1) "Skin-care tips for today's weather", only when the weather fits a group, a cool-or-dry group (temperature at or below 15 C, or humidity at or below 35%; link "Browse moisturizers with 'cream' in the name" to `/products?category=Moisturizers&q=cream`) or a hot-and-humid group (30 C or above and humidity 60% or above; links to the Cleansers and Moisturizers categories), each tip with its source label; there are no every-day tips, and a missing temperature or humidity never triggers a group; (2) "Sun protection today", driven by today's peak UV as a whole number: 3 or higher shows the UV timeline (the hours with UV 3 or higher as ranges, labelled by the hour each hourly value covers because Open-Meteo hourly values average the hour that ENDS at their time) and the peak hour, the American Academy of Dermatology sunscreen sentence once, the WHO extra steps ("seek shade, cover up, hat, sunscreen" at 3 to 7; "avoid being outside at midday where possible..." at 8 and above), the four "Also worth remembering" reminders and "Browse sunscreens" (`/products?category=Sunscreen`) with a note to check SPF and broad-spectrum; 1 to 2 shows only the one line "UV is low right now. Dermatologists still recommend daily sunscreen on exposed skin when you're outdoors." with its source (no timeline, peak, reminders, WHO steps or link); below 1 shows only "UV is very low today."; no UV data shows only "The UV index isn't available right now."; (3) one small note, "General information from the sources named. Not medical advice." The sunscreen sentence appears at most once on the page and no line says sun protection is unnecessary. If the services are down or slow the page says so and shows no numbers; if only some values are missing, the rest are shown. The page also carries "Live conditions, general information only. Not medical or dermatological advice." and the attributions ("Weather data by Open-Meteo.com", CAMS for air quality, GeoNames for places).
- `content/today_tips.py`: the one file holding every fixed guidance and tip text on the Today page with its source (American Academy of Dermatology, World Health Organization, Johns Hopkins Medicine), the UV low and very-low lines, the headlines, the sources note and the browse links' labels and filters. Texts are quoted from their sources; do not add or reword one without the content owner agreeing, and never add a tip without a source. The every-day tips and the "see a board-certified dermatologist" line were removed on purpose and must not come back. `tests/test_today.py` pins every text and source as a literal, so an edit here fails a test.
- `live/weather.py`: the only code that calls Open-Meteo for conditions (`search_places`, `fetch_forecast`, `fetch_air_quality`; `requests` with `params=` and a 5 second timeout; `WeatherError` with a plain message). UV is requested as a current value (`uv_index`), the hourly `uv_index` (each value is the average of the hour ENDING at its time) and the daily `uv_index_max`, in one request with `timezone=auto`. Values outside plausible ranges become missing, never repaired. In-memory cache: 15 minutes per place or grid point (coordinates rounded to 2 decimals), a failure remembered for 10 seconds (so reloads in an outage are not hammered, yet a slow lookup can be retried quickly), at most 200 entries; `clear_cache()` and the module clock `_clock` exist for tests. The geocoding service returns no `results` key at all when nothing matches.
- `database/load_data.py`: pandas loader for `data/product_info.csv` (Skincare rows only; sizes converted to `size_ml`; ingredient lists split into the two ingredient tables; drop reasons printed). Cleaning helpers (`parse_size_ml`, `split_ingredients`, `parse_strength`, `parse_ingredients`, `clean_products`) are unit-tested without the CSV. It also reads `tertiary_category` to set each product's `compare_group` (see Comparison rules) and prints a group report (fallbacks, products with no group, big groups, groups with one product, renamed groups), and reads `loves_count`, `rating` and `reviews` (blank stays NULL) with a report of how many are filled and their ranges.
- Stated strengths (`product_ingredients.stated_percent`, nullable, must be above 0 and below 100; `init_db()` adds the column to older databases): for Skincare products outside the secondary categories "Value & Gift Sets" and "Mini Size" only, `parse_strength` splits a percentage the brand printed off an ingredient piece in exactly three formats: trailing (`Salicylic Acid 2.0%`, `... 15 %`), parenthesised (`Zinc Oxide (12.025%)`, `Ceramide Np(0.2%)`) and leading (`3% Procapil`). The cleaned name then goes through the Water alias map, so `Zinc Oxide 20%` and `Zinc Oxide` are one ingredient. Ignored and left exactly as written: values of 100 or more or 0 or below, and colon-style compounds (`Name : 0.0408%`). Anything else containing a `%` is ambiguous and also left unchanged: a word after the %, glued text (`6.90%Water`), several strengths in one piece, a range (`13.20 - 14.00 %`), a limit (`less than 1%`), a name that is part of a sentence or heading. When an ingredient name repeats, the first position is kept and takes the strength if it has none. The loader prints a report (counts, 30 varied examples, every ambiguous case, merged duplicates). Gift-set and mini-size products keep their raw names, so a `%` can still sit inside an ingredient name there.
- `data/`: `data/*.csv` and `data/*.parquet` are gitignored, as is `skin_index.db`. The CSV must be present locally to run the loader.
- `tests/conftest.py`: inserts project root into `sys.path`, imports `app` from `app.py`, and defines the `app` fixture (sets `TESTING=True` and gives each test its own empty temporary database via `app.config["DATABASE"]`). An autouse fixture replaces `live.currency.requests.get` with a call that fails like an outage, so no test reaches the network and by default no rate exists; the `rate_api` fixture patches it with a controllable fake; the `weather_api` fixture answers like the three Open-Meteo services (geocoding, forecast, air quality; anything else stays offline) and records every call, and `weather_clock` moves the weather cache's clock. The weather cache is cleared before every test. `pytest-flask` supplies the `client` fixture from it. `test_routes.py` asserts every page (`/`, `/products`, `/compare`, `/insights`, `/today`) loads on an empty database; add new pages to that list.

## Architecture rules

- All external HTTP calls live in a `live/` package and use `requests`. Every call has a timeout, a cache, and a clear error message the page can show.
- Routes and MCP tools never call external APIs directly. They call service functions.
- Tests never use the real network. Fake or stub the `live/` functions.
- SQL is parameterized only. Never build SQL text from request or tool input.
- Sort columns come from a whitelist of known keys; an unknown key falls back to the default.

## Data rules

- Data note: the product data is a March 2023 Sephora US snapshot. Prices, likes, ratings and reviews are as of then, not live.
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

- Popularity means shopper engagement from one retailer's site: likes, reviews and ratings. There is no sales data. Say "most liked" or "most reviewed"; never "best-selling", "most sold", "bestseller" or anything about sales. Tests check the takeaways against a list of such words.
- Everything on the page is computed from the data and worded neutrally: numbers, never claims about effectiveness or quality. The price-vs-rating bands show a pattern, not a cause.
- Weighted average rating = sum(rating × reviews) ÷ sum(reviews). Ratings with few reviews are ignored where it matters: the well-reviewed list needs at least 50 reviews and a rating of at least 4.0, the price bands at least 10 reviews. Old products have had more time to collect likes and reviews, and the page says so.
- No median or min/max price sections on this page. Water is shown in a note, not in the ingredient ranking; its share is "at least" because names like "Purified Water" are separate ingredients.

## Claims and safety rules

- The app informs and never recommends. No product is called better, best, right or suitable for anyone.
- No skin-type, skin-concern or "good for" claims anywhere (pages, takeaways, MCP tools, docs).
- Never say "safe", "treats" or "cures". Wording is "contains ...".
- The user's avoid list lives only in the browser (the URL or local storage). It is never saved in the database and never logged.
- "Not flagged" must never be shown as "safe": an ingredient list with no match only means nothing on the list was found.
- Every page that shows ingredient information or the avoid list carries a patch-test / see-a-dermatologist note.
- Regulatory restrictions (for example EU CosIng) are shown only as a pointer to CosIng ("has an EU restriction, see CosIng"), never interpreted.
- One narrow exception, by decision of the project owner: the Today page's tips (Step 9). They are quoted word for word from named public sources, each shown with its source label and the line "General information from the sources named. Not medical advice.", so they are not the app's own claims. They include wording such as "tend to suit dry, sensitive skin" and "more effective ... for dry skin" because the sources say so. The exception covers only the texts in `content/today_tips.py`; everywhere else, and for any new text, the rules above apply in full, and the Step 13 claims scan must allow only that file's texts.

## Today rules

- Information first: live UV, humidity, temperature and US AQI. The tiles carry no advice; AQI above Moderate adds only "check local health advisories".
- All guidance and tips are quoted from named public sources (American Academy of Dermatology, World Health Organization, Johns Hopkins Medicine), shown with their source labels, and live only in `content/today_tips.py`. The weather-based tips apply by config thresholds (cool or dry: at or below 15 C or at or below 35% humidity; hot and humid: at or above 30 C and 60% humidity); with a missing reading no group applies, and with no group there is no tips card. The sunscreen advice appears at most once on the page (the full sentence at UV 3 or higher, the one low line at 1 to 2, none below 1). No line may say sun protection is unnecessary or "not needed" at low UV. Never use "safe", "best for", "treats" or "cures". Tests check the whole page and the content file for banned wording.
- Links go only to category lists on the Products page (sunscreens; moisturizers with "cream" in the name; cleansers; moisturizers). They are links, not recommendations; no product is named or ranked.
- Never invent a value: a missing or implausible value is shown as not available, and a service that is down or slow gives a friendly message.
- Open-Meteo's free tier is for non-commercial use only, with limits of 10,000 calls a day, 5,000 an hour and 600 a minute; the cache keeps this app far below them. A site with ads or subscriptions would need their paid plan. The data is CC-BY 4.0, so keep the attributions on the page.

## Research rules

- Show PubMed titles, journals, years and links only.
- Make no claim that a product works.
- Stay under 3 requests per second to PubMed.

## MCP rules

- The MCP server opens the database read-only.
- MCP tools call the same service functions as the pages.
- Tools: search, compare, insights, weather and the avoid-list check. There is no skin-type tool.
- The avoid-list check takes the list as an argument for that one call and does not store it (see Claims and safety rules).

## Project rules
- Stack: Flask, SQLite (sqlite3), pandas, pytest, plus `requests` for HTTP in `live/`. No other frameworks.
- Windows: activate venv with .\venv\Scripts\Activate.ps1, app runs on port 5001.
- Build one step at a time (Steps 1-13 in the Roadmap and README; there is no Step 8). Do not start later steps.
- After every change, run pytest and show the result.
- Keep the light pink theme and the existing file structure.
