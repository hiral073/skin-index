# Skin Index

A Flask app for understanding skincare products: ingredients, price per ml, product comparison and shopper-engagement insights, plus live pages for today's sun and air conditions and for ingredient science, and later ingredient tools.

**Status:** in progress. Steps 1-7, 9, 10 and 12c are done (database, dataset loader, product search, INR prices, product page, compare, insights, today page). The rest is built step by step.

## Features and roadmap
1. Database setup (SQLite) — done
2. Load and clean a product dataset (pandas) — done
3. Product search — done
4. Currency: show prices in INR (approximate, from a daily exchange rate) — done
5. Product page: ingredients, price, price per ml — done
   - 5b. Stated ingredient strengths, only where the brand prints them — done
6. Compare two products from the same category and main ingredient group: price, size, price per ml, likes, rating, reviews and ingredients — done
7. Insights page: most liked brands and products, well-reviewed products with a lower price per ml, price vs rating, most common ingredients — done
8. Dropped (no step 8)
9. Today page: live UV, humidity and US AQI from Open-Meteo, shown as information, plus general sun-protection guidance based on public UV index categories, and a link to the sunscreen list. No product recommendations. — done
10. Ingredient Science page (first called Research): PubMed papers as cards under plain labels, with an At a glance box (source-named ingredient cards, topic counts for other ingredients) — done
11. MCP server (read-only access to the product data): search, compare, insights, weather and an avoid-list check
12. Avoid list
    - 12a. Dropped: automatic merging of ingredient names could combine chemically different substances, so ingredient text is kept exactly as the brand wrote it.
    - 12b. Dropped: already covered by the sourced At a glance cards on the Ingredient Science page.
    - 12c. "My avoid list": type ingredients to avoid, hide products that list them, and see which ingredient matched — done
13. Engineering polish: GitHub Actions CI, a test hook, a claims-reviewer check, an automated scan of the pages for medical-claim wording, and screenshots

Not planned: login, an in-app AI assistant, Indian product data, product recommendations.

**Data:** the product data is a March 2023 Sephora US snapshot. Prices, likes, ratings and reviews are as of then, not live.

The Insights page shows what shoppers like and review on one retailer's site (likes, ratings and reviews from the dataset, not sales): the most liked brands and products, and the most common ingredients. Choose one product type in the dropdown to also see well-reviewed products (at least 50 reviews and a rating of at least 4.0) sorted by price per ml, and how the average rating differs across three price-per-ml bands. Ratings are averaged using each product's number of reviews as the weight, ratings with few reviews are ignored, and older products have had more time to collect likes and reviews. The bands show a pattern, not a cause. Prices are US prices, converted to rupees at the shown rate, and are approximate.

The Ingredient Science page (it was called Research; `/research` still redirects to `/science`) lists published papers about a skincare ingredient from PubMed (the US National Library of Medicine). Each paper is a small card with its title, journal, year and a "Read on PubMed" link, grouped under plain labels (overview papers first): Start here: overview papers, Studies combined into one analysis, Trials with people, and Other research papers. The groups name the kind of paper and are not our summary of what a paper found. An "At a glance" box above the papers gives, for niacinamide, retinol, retinal, vitamin C, hyaluronic acid, salicylic acid and ceramides, two short lines (what it is, and what it is often discussed in relation to), each with a named public source and a link (MedlinePlus, ChEBI, the NLM MeSH vocabulary, the American Academy of Dermatology, Cleveland Clinic). It is general information from those sources, not medical advice. For other ingredients the box shows how often topics such as acne or skin barrier appear together with the ingredient in PubMed papers (topics with no papers are left out, and the box is hidden when there is nothing to show); those counts show how often topics appear in published papers, not that an ingredient works. On the first search for an ingredient without a card the page makes 9 PubMed calls and can take several seconds; the counts are then saved for 24 hours. The page is linked from the footer (under "Learn more") and from product pages ("Studies on ..."), not from the top navigation. It only lists papers: a study existing does not mean a product works. Searches are saved for 24 hours, so repeat searches do not call PubMed again, and if PubMed is down an older saved copy is shown with its date. To give NCBI a contact address (they ask for one), set the `NCBI_EMAIL` environment variable; with none set, no email is sent.

The Today page shows live conditions for a city: UV index now and today's maximum, humidity, temperature and US air quality (AQI), each UV and AQI value with its standard category, as information only. When the weather is cool or dry, or hot and humid, a "Skin-care tips for today's weather" card shows tips quoted from named sources (American Academy of Dermatology, Johns Hopkins Medicine), each with its source. Below it, a "Sun protection today" card depends on today's peak UV: at 3 or higher it gives an hour-by-hour UV timeline with the peak hour, general sunscreen guidance from the American Academy of Dermatology, extra steps from the World Health Organization, a few reminders and a link to the sunscreen list; at 1 to 2 it is a single short line; below 1 it only says UV is very low. It is general information, not medical or dermatological advice, and it recommends no product. Weather data comes from [Open-Meteo.com](https://open-meteo.com/) (free for non-commercial use, no key), with air quality from CAMS and places from GeoNames. Results are cached for 15 minutes, and if the service is down or slow the page says so and never shows made-up numbers. The default city is Pune.

Compare works on two products that share a category (the most specific category level in the data, for example "Face Serums") and a main ingredient group (niacinamide, ascorbic acid, retinol, retinal, hyaluronic acid, salicylic acid, glycolic acid, lactic acid, azelaic acid, ceramide or peptide; each is one exact word or phrase with no related forms grouped in, and a product is in a group when that word is in its name or among its first 10 listed ingredients). You choose the category, then the main ingredient, then the two products from dropdowns, so there is no need to type a name. The table shows price, size, price per ml, likes, rating, reviews and the ingredients both products have and only one has. It never says one product is better: ingredient order is a rough guide and amounts are not in the data. Products from different categories or main ingredient groups, and mini sizes and gift sets, are not compared, because the result would not be fair. Some groups are merged or hidden by a cleanup map in `content/compare_groups.py` (for example sunscreen and self-tanners each have a Face and a Body subcategory, written "Sunscreen › Face", and shown in the dropdowns under one heading); the original categories are kept (and shown on the product detail page), the Products page Category filter and column use the cleaned groups, and the before and after counts are in the "Group cleanup" section of [docs/data-audit.md](docs/data-audit.md). After loading the data, run `python -m database.load_data` again whenever the loader or the cleanup map changes, so each product gets its category group.

INR prices are converted from the US prices using the daily USD to INR rate from [Frankfurter](https://frankfurter.dev) (no API key). The rate is saved in the database and fetched at most once a day, so the first page load of the day needs internet. If the rate cannot be fetched, the last saved rate is shown and marked "older rate"; if none was ever saved, INR is hidden. The figures are approximate and are not Indian retail prices.

Some brands print a strength next to an ingredient (for example "Zinc Oxide 12.025%"). The product page shows it as "12.025% (stated by brand)". Strengths are never estimated: if a brand prints none, nothing is shown, and a missing percentage means "not stated", not "low". Unclear text is left as it was written.

Skin Index shows information only. It does not recommend products, make skin-type or skin-concern claims, or give medical advice. Patch-test new products, and see a dermatologist about skin concerns.

## My avoid list

On the Products page, open "Ingredients to avoid" in the filters (next to the Group filter), type an ingredient you want to avoid and press Add (or Enter). The section is closed while the list is empty and open once it has items. Each word or phrase becomes a chip you can remove, and "Clear my list" empties the list. Every word or phrase is matched as whole words, ignoring capital letters, in the ingredient list as the brand wrote it, so "alcohol" finds "Cetyl Alcohol" but not "Alcoholic". The only synonyms are fragrance/parfum and water/aqua/eau; everything else (for example retinol and retinal) is exact.

- A row, the product page and the Compare page show a small tag such as "Lists: fragrance, matched: Fragrance (Parfum)" when something is found. Nothing found says "None found in the listed ingredients", never that a product is free of anything. A product with no ingredient list says "Ingredient list not available, can't check" and is never treated as clear.
- The switch "Hide products that list my avoided ingredients" removes the matching products from the list; products that cannot be checked stay.
- Privacy: the list is stored in your browser (a cookie your own action sets, kept for 30 days, up to 20 items). The site reads it with each request to filter and tag results, but does not save it, log it or put it in a link, and there are no accounts. Clearing the list removes the cookie.
- It is based on the brand's own ingredient list, which can be incomplete. Check the product label.

## Run it (Windows PowerShell)

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m database.load_data
python app.py
```

`database.load_data` needs `data/product_info.csv` (not in the repo) and fills `skin_index.db`.

Then open http://localhost:5001

## Run the tests

```
pytest
```

## MCP in this project

A read-only SQLite MCP server lets Claude Code answer questions about `skin_index.db` in plain English (for example "count products per compare_group"). It is a developer tool only: the app does not use it, and the app's own MCP server is still a later step. The server is [mcp-sqlite-insights](https://github.com/RayaanKaz/mcp-sqlite-insights), pinned to one commit and installed in its own virtual environment under `tools/`, which is not committed.

It is read-only: SQLite opens the file read-only, so a write is refused even if one is asked for. That covers this server only. Claude Code's own shell and edit tools can still reach the file, so keep a copy if the data matters.

Set it up once, from the project folder (Windows PowerShell or Git Bash):

```
git clone https://github.com/RayaanKaz/mcp-sqlite-insights.git tools/mcp-sqlite-insights
git -C tools/mcp-sqlite-insights checkout 0f36dbc01923b67c45cf90a3dcbf658cc54b5be9
python -m venv tools/mcp-sqlite-insights/.venv
tools/mcp-sqlite-insights/.venv/Scripts/python.exe -m pip install -r tools/mcp-sqlite-insights/requirements.txt
tools/mcp-sqlite-insights/.venv/Scripts/python.exe tools/mcp-sqlite-insights/server.py --check
claude mcp add --scope local --transport stdio skin-index-db -- tools/mcp-sqlite-insights/.venv/Scripts/python.exe tools/mcp-sqlite-insights/server.py --db skin_index.db
```

`--scope local` keeps it private to you and to this project folder: nothing is written to the repository and no other project sees it.

Check it: start a new session with `claude` in this folder and run `/mcp`; `skin-index-db` should show as connected (outside a session, `claude mcp list` shows the same). Then ask, for example, "list the tables" or "show the schema of the products table". It has two tools, `inspect_schema` and `execute_query` (one SELECT at a time, at most 50 rows).

Remove it: `claude mcp remove skin-index-db --scope local`, then delete the `tools/mcp-sqlite-insights` folder.

The first findings from using it are in [docs/data-audit.md](docs/data-audit.md).

## Tech stack
Python, Flask, SQLite, pandas, HTML/CSS/JavaScript, pytest, requests. Live data from Frankfurter (exchange rates), Open-Meteo and PubMed. Built with Claude Code.
