# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Skin Index: Flask app for exploring skincare products (ingredients, price per ml, product comparison, brand price insights). Early scaffold, built step by step per the README's planned-features list. Stack: Python, Flask, SQLite, pandas, plain HTML/CSS/JS, pytest.

## Commands (Windows PowerShell)

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py                  # dev server, http://localhost:5001 (debug=True)
pytest                         # all tests
pytest tests/test_routes.py::test_landing_page_loads   # single test
```

No linter or build step configured. Two virtualenvs exist in the tree (`venv/`, `.venv/`); README and `.gitignore` use `venv/`.

## Architecture

- `app.py`: single Flask app, module-level `app`. Only `/` renders a real template (`landing.html`). `/products`, `/products/<int:id>`, `/compare`, `/insights` are placeholder routes returning plain strings, labelled with the build step that will implement them. Replace the placeholder in place; templates/nav already link to them via `url_for('products')` etc., so keep those endpoint function names.
- `templates/`: `base.html` (navbar, Google Fonts, `{% block title %}`, `{% block head %}`, content blocks) is extended by page templates.
- `database/db.py`: stub only, comments describe the planned design: `get_db()` (row_factory + foreign keys on), `init_db()` (`CREATE TABLE IF NOT EXISTS`), `seed_db()`. Planned tables: `products`, `ingredients`, `product_ingredients` (with `position` = label order). Not yet implemented or wired into `app.py`.
- `data/`: product dataset not included yet. `data/*.csv` and `data/*.parquet` are gitignored, as is `skin_index.db`. CSV loading/cleaning (pandas) is a separate planned step (see `data/README.md`).
- `tests/conftest.py`: inserts project root into `sys.path`, imports `app` from `app.py`, and defines the `app` fixture (sets `TESTING=True`). `pytest-flask` supplies the `client` fixture from it. `test_routes.py` asserts placeholder routes return 200, so update it when a placeholder gets a real implementation.

## Project rules
- Stack: Flask, SQLite (sqlite3), pandas, pytest. No other frameworks.
- Windows: activate venv with .\venv\Scripts\Activate.ps1, app runs on port 5001.
- Build one step at a time (Steps 1-6 in README). Do not start later steps.
- After every change, run pytest and show the result.
- Keep the light pink theme and the existing file structure.
