# Skin Index

A Flask app for understanding skincare products: ingredients, price per ml, product comparison and brand-level price insights.

**Status:** in progress. The project scaffold runs; the database and features are built step by step.

## Planned features
1. Database setup (SQLite)
2. Load and clean a product dataset (pandas)
3. Product search
4. Product page: ingredients, price, price per ml
5. Compare two products: price per ml and ingredient overlap
6. Insights page: price per ml by brand, most common ingredients

## Run it (Windows PowerShell)

```
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5001

## Run the tests

```
pytest
```

## Tech stack
Python, Flask, SQLite, pandas, HTML/CSS/JavaScript, pytest. Built with Claude Code.
