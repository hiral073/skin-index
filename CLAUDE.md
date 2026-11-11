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

Steps 1-3 are done. Build one step at a time, in this order:

1. Database setup (SQLite) — done
2. Load and clean the dataset (pandas) — done
3. Product search — done
4. Currency: INR display
5. Product detail
6. Compare
7. Insights
8. Skin-type tags and filter
9. Today page (Open-Meteo weather, UV, AQI)
10. Research page (PubMed)
11. MCP server

## Architecture

- `app.py`: single Flask app, module-level `app`. `/` renders `landing.html`; `/products` is the real search page (`products.html`). `/products/<int:id>`, `/compare`, `/insights` are still placeholder routes returning plain strings; their text carries the old step numbers (4/5/6), so follow the Roadmap numbering, not those strings. Replace a placeholder in place; templates/nav link to them via `url_for('products')` etc., so keep those endpoint function names.
- `/products`: filters, sort and paging come from query args (`q`, `category`, `sort`, `page`; 24 per page). The database path is `app.config["DATABASE"]` (defaults to `database.db.DB_PATH`), so tests can point it at a temporary database.
- `templates/`: `base.html` (navbar, Google Fonts, `{% block title %}`, `{% block head %}`, content blocks) is extended by page templates.
- `database/db.py`: `get_db(db_path=None)` (Row factory, foreign keys on), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()` (5 sample products, no-op if products exist). Tables: `products`, `ingredients`, `product_ingredients` (`position` = label order). Prices are stored in USD (`price`, `price_per_ml`).
- `database/load_data.py`: pandas loader for `data/product_info.csv` (Skincare rows only; sizes converted to `size_ml`; ingredient lists split into the two ingredient tables; drop reasons printed). Cleaning helpers (`parse_size_ml`, `split_ingredients`, `clean_products`) are unit-tested without the CSV.
- `data/`: `data/*.csv` and `data/*.parquet` are gitignored, as is `skin_index.db`. The CSV must be present locally to run the loader.
- `tests/conftest.py`: inserts project root into `sys.path`, imports `app` from `app.py`, and defines the `app` fixture (sets `TESTING=True` and gives each test its own empty temporary database via `app.config["DATABASE"]`). `pytest-flask` supplies the `client` fixture from it. `test_routes.py` asserts the remaining placeholder routes return 200, so update it when a placeholder gets a real implementation.

## Architecture rules

- All external HTTP calls live in a `live/` package. Every call has a timeout, a cache, and a clear error message the page can show.
- Routes and MCP tools never call external APIs directly. They call service functions.
- Tests never use the real network. Fake or stub the `live/` functions.
- SQL is parameterized only. Never build SQL text from request or tool input.
- Sort columns come from a whitelist of known keys; an unknown key falls back to the default.

## Data rules

- Prices are stored in USD.
- INR is derived at display time from the cached daily exchange rate. It is labeled approximate and shows the rate date.
- If today's rate cannot be fetched, use the last saved rate with its date. If no rate was ever saved, hide INR.

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
- Stack: Flask, SQLite (sqlite3), pandas, pytest. No other frameworks.
- Windows: activate venv with .\venv\Scripts\Activate.ps1, app runs on port 5001.
- Build one step at a time (Steps 1-11 in the Roadmap and README). Do not start later steps.
- After every change, run pytest and show the result.
- Keep the light pink theme and the existing file structure.
