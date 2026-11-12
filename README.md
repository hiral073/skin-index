# Skin Index

A Flask app for understanding skincare products: ingredients, price per ml, product comparison and shopper-engagement insights, plus live pages for today's sun and air conditions and for research, and later ingredient tools.

**Status:** in progress. Steps 1-7 and 9 are done (database, dataset loader, product search, INR prices, product page, compare, insights, today page). The rest is built step by step.

## Features and roadmap
1. Database setup (SQLite) — done
2. Load and clean a product dataset (pandas) — done
3. Product search — done
4. Currency: show prices in INR (approximate, from a daily exchange rate) — done
5. Product page: ingredients, price, price per ml — done
   - 5b. Stated ingredient strengths, only where the brand prints them — done
6. Compare two products: price per ml and ingredient overlap — done
7. Insights page: most liked brands and products, well-reviewed products with a lower price per ml, price vs rating, most common ingredients — done
8. Dropped (no step 8)
9. Today page: live UV, humidity and US AQI from Open-Meteo, shown as information, plus general sun-protection guidance based on public UV index categories, and a link to the sunscreen list. No product recommendations. — done
10. Research page: PubMed titles, journals, years and links
11. MCP server (read-only access to the product data): search, compare, insights, weather and an avoid-list check
12. Ingredient Intelligence
    - 12a. Ingredient-name normalizer: names mapped to canonical names (exact, alias and fuzzy matching), with a reported match rate
    - 12b. Official ingredient functions, and "has an EU restriction, see CosIng" notes, from the EU CosIng database (only after checking its data-use terms)
    - 12c. "My avoid list" checker and a Products exclude filter, with common aliases such as Parfum/Fragrance and an optional EU fragrance-allergen list
13. Engineering polish: GitHub Actions CI, a test hook, a claims-reviewer check, an automated scan of the pages for medical-claim wording, and screenshots

Not planned: login, an in-app AI assistant, Indian product data, product recommendations.

**Data:** the product data is a March 2023 Sephora US snapshot. Prices, likes, ratings and reviews are as of then, not live.

The Insights page shows what shoppers like and review on one retailer's site (likes, ratings and reviews from the dataset, not sales): the most liked brands and products, and the most common ingredients. Choose one product type in the dropdown to also see well-reviewed products (at least 50 reviews and a rating of at least 4.0) sorted by price per ml, and how the average rating differs across three price-per-ml bands. Ratings are averaged using each product's number of reviews as the weight, ratings with few reviews are ignored, and older products have had more time to collect likes and reviews. The bands show a pattern, not a cause. Prices are US prices, converted to rupees at the shown rate, and are approximate.

The Today page shows live conditions for a city: UV index now and today's maximum, humidity, temperature and US air quality (AQI), each UV and AQI value with its standard category, as information only. When the weather is cool or dry, or hot and humid, a "Skin-care tips for today's weather" card shows tips quoted from named sources (American Academy of Dermatology, Johns Hopkins Medicine), each with its source. Below it, a "Sun protection today" card depends on today's peak UV: at 3 or higher it gives an hour-by-hour UV timeline with the peak hour, general sunscreen guidance from the American Academy of Dermatology, extra steps from the World Health Organization, a few reminders and a link to the sunscreen list; at 1 to 2 it is a single short line; below 1 it only says UV is very low. It is general information, not medical or dermatological advice, and it recommends no product. Weather data comes from [Open-Meteo.com](https://open-meteo.com/) (free for non-commercial use, no key), with air quality from CAMS and places from GeoNames. Results are cached for 15 minutes, and if the service is down or slow the page says so and never shows made-up numbers. The default city is Pune.

Compare works on two products from the same category (the most specific category level in the data, for example "Face Serums"). You pick them from dropdowns, so there is no need to type a name. Products from different categories, and mini sizes and gift sets, are not compared, because the result would not be fair. After loading the data, run `python -m database.load_data` again whenever the loader changes, so each product gets its category group.

INR prices are converted from the US prices using the daily USD to INR rate from [Frankfurter](https://frankfurter.dev) (no API key). The rate is saved in the database and fetched at most once a day, so the first page load of the day needs internet. If the rate cannot be fetched, the last saved rate is shown and marked "older rate"; if none was ever saved, INR is hidden. The figures are approximate and are not Indian retail prices.

Some brands print a strength next to an ingredient (for example "Zinc Oxide 12.025%"). The product page shows it as "12.025% (stated by brand)". Strengths are never estimated: if a brand prints none, nothing is shown, and a missing percentage means "not stated", not "low". Unclear text is left as it was written.

Skin Index shows information only. It does not recommend products, make skin-type or skin-concern claims, or give medical advice. Patch-test new products, and see a dermatologist about skin concerns.

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

## Tech stack
Python, Flask, SQLite, pandas, HTML/CSS/JavaScript, pytest, requests. Live data from Frankfurter (exchange rates), Open-Meteo and PubMed. Built with Claude Code.
