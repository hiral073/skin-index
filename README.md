# Skin Index

A Flask app for understanding skincare products: ingredients, price per ml, product comparison, brand-level price insights and skin-type tags, plus live pages for daily conditions and research.

**Status:** in progress. Steps 1-5 are done (database, dataset loader, product search, INR prices, product page). The rest is built step by step.

## Features and roadmap
1. Database setup (SQLite) — done
2. Load and clean a product dataset (pandas) — done
3. Product search — done
4. Currency: show prices in INR (approximate, from a daily exchange rate) — done
5. Product page: ingredients, price, price per ml — done
6. Compare two products: price per ml and ingredient overlap
7. Insights page: price per ml by brand, most common ingredients
8. Skin-type tags and filter (ingredient-based, with reasons)
9. Today page: weather, UV and air quality from Open-Meteo
10. Research page: PubMed titles, journals, years and links
11. MCP server (read-only access to the product data)

Not planned: login, an in-app AI assistant, Indian product data.

INR prices are converted from the US prices using the daily USD to INR rate from [Frankfurter](https://frankfurter.dev) (no API key). The rate is saved in the database and fetched at most once a day, so the first page load of the day needs internet. If the rate cannot be fetched, the last saved rate is shown and marked "older rate"; if none was ever saved, INR is hidden. The figures are approximate and are not Indian retail prices.

Skin-type tags are based only on ingredients and are not medical advice.

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
