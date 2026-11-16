"""The MCP server (Step 11): every tool, bad input, the read-only guarantee and the banned wording.

No test reaches the network: the weather and PubMed tools run against the `weather_api` and
`pubmed_api` fakes, and every test has its own temporary database.
"""
import asyncio
import json
import re
import sqlite3
from contextlib import closing

import pytest

from content import mcp_text
from database.db import get_db, read_only_uri
from mcp_server import server

EXPECTED_TOOLS = {
    "search_products", "get_product_detail", "compare_products", "get_insights",
    "list_groups", "get_weather", "find_studies", "check_avoid_list",
}

# Our own wording must never use these (paper titles and product names are the source's own text)
BANNED = re.compile(
    r"\b(safe|free of|clean|best|recommend\w*|suitable|good for|treats|cures|proven|effective|dupe)\b", re.I)
FORBIDDEN_TOOL_WORDS = re.compile(
    r"write|create|update|delete|remove|insert|save|set_|add_|skin_?type|suitab|recommend|advice|diagnos", re.I)


def add(db, name, group="Face Serums", brand="Dew Labs", ingredients=(), price=20.0, loves=None, rating=None,
        reviews=None):
    with closing(get_db(db)) as conn, conn:
        pid = conn.execute(
            "INSERT INTO products (name, brand, category, price, size_text, price_per_ml, ingredients_text,"
            " compare_group, loves_count, rating, reviews) VALUES (?, ?, ?, ?, '100 mL', ?, ?, ?, ?, ?, ?)",
            (name, brand, group, price, price / 100, ", ".join(ingredients) or None, group, loves, rating, reviews),
        ).lastrowid
        for position, ingredient in enumerate(ingredients, start=1):
            conn.execute("INSERT OR IGNORE INTO ingredients (name) VALUES (?)", (ingredient,))
            iid = conn.execute("SELECT id FROM ingredients WHERE name = ?", (ingredient,)).fetchone()[0]
            conn.execute("INSERT INTO product_ingredients (product_id, ingredient_id, position) VALUES (?, ?, ?)",
                         (pid, iid, position))
    return pid


@pytest.fixture
def shop(app, monkeypatch):
    """Face Serums: two with niacinamide (n1, n2), one with ascorbic acid (c1); a niacinamide Moisturizers
    product (m1); a serum with fragrance (f1) and one with no ingredient list (bare)."""
    db = app.config["DATABASE"]
    monkeypatch.setenv("SKIN_INDEX_DB", db)
    return {
        "db": db,
        "n1": add(db, "Bravo Serum", ingredients=["Water", "Glycerin", "Niacinamide"], loves=900, rating=4.5, reviews=300),
        "n2": add(db, "Delta Serum", brand="Glow Co", ingredients=["Aqua", "Niacinamide", "Squalane"], loves=500,
                  rating=4.0, reviews=100),
        "c1": add(db, "Cee Serum", ingredients=["Water", "Ascorbic Acid"], loves=100, rating=3.5, reviews=20),
        "m1": add(db, "Dew Cream", group="Moisturizers", ingredients=["Water", "Niacinamide"], loves=50),
        "f1": add(db, "Scent Serum", ingredients=["Water", "Parfum", "Alcohol Denat."]),
        "bare": add(db, "Bare Serum"),
    }


def tool_names():
    return {tool.name for tool in asyncio.run(server.mcp.list_tools())}


def own_text(answer):
    """The wording that is ours in an answer: source, note, message and error."""
    found = []
    def walk(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str) and key in ("source", "note", "message", "error"):
            found.append(value)
    walk(answer)
    return found


# ---- the tool list and the read-only guarantee ------------------------------------------------ #

def test_exactly_the_planned_tools_exist():
    assert tool_names() == EXPECTED_TOOLS


def test_no_write_skin_type_or_recommendation_tool_exists():
    assert [n for n in tool_names() if FORBIDDEN_TOOL_WORDS.search(n)] == []


def test_every_tool_is_marked_read_only_and_not_destructive():
    for tool in asyncio.run(server.mcp.list_tools()):
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.destructiveHint is False, tool.name


def test_every_tool_has_a_description_and_typed_inputs():
    for tool in asyncio.run(server.mcp.list_tools()):
        assert len(tool.description) > 40, tool.name
        for prop, schema in tool.inputSchema.get("properties", {}).items():
            assert "type" in schema or "anyOf" in schema, f"{tool.name}.{prop}"
            assert schema.get("description"), f"{tool.name}.{prop}"


def test_the_product_database_is_opened_read_only(shop):
    with closing(sqlite3.connect(server._product_db(), uri=True)) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM products")


def test_no_tool_changes_a_product_table(shop, weather_api, pubmed_api):
    pubmed_api.add(1, "A paper")

    def counts():
        with closing(get_db(shop["db"])) as conn:
            return [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("products", "ingredients", "product_ingredients", "exchange_rates")]

    before = counts()
    server.search_products("serum")
    server.get_product_detail(shop["n1"])
    server.compare_products(shop["n1"], shop["n2"])
    server.get_insights("")
    server.list_groups()
    server.get_weather("Pune")
    server.find_studies("niacinamide")
    server.check_avoid_list(shop["n1"], ["water"])
    assert counts() == before


def test_a_missing_database_gives_a_plain_message(monkeypatch, tmp_path):
    monkeypatch.setenv("SKIN_INDEX_DB", str(tmp_path / "nope.db"))
    assert "not found" in server.list_groups()["error"]


# ---- search_products --------------------------------------------------------------------------- #

def test_search_by_name_group_and_ingredient(shop):
    answer = server.search_products(query="serum")
    assert answer["source"] == mcp_text.SOURCES["products"]
    assert answer["data"]["total_matches"] == 5
    assert [p["name"] for p in answer["data"]["products"]] == [
        "Bare Serum", "Bravo Serum", "Cee Serum", "Delta Serum", "Scent Serum"]
    assert server.search_products(group="Moisturizers")["data"]["products"][0]["name"] == "Dew Cream"
    niacinamide = server.search_products(ingredient="Niacinamide")["data"]
    assert {p["name"] for p in niacinamide["products"]} == {"Bravo Serum", "Delta Serum", "Dew Cream"}
    both = server.search_products(group="Face Serums", ingredient="niacinamide")["data"]
    assert both["total_matches"] == 2


def test_search_ingredient_is_a_whole_word_with_the_site_synonyms(shop):
    assert server.search_products(ingredient="niacin")["data"]["total_matches"] == 0          # no part of a word
    assert {p["name"] for p in server.search_products(ingredient="fragrance")["data"]["products"]} == {"Scent Serum"}
    assert server.search_products(ingredient="aqua")["data"]["total_matches"] == 5            # water = aqua


def test_search_limit_is_kept_between_1_and_25(shop):
    assert len(server.search_products(limit=2)["data"]["products"]) == 2
    assert len(server.search_products(limit=0)["data"]["products"]) == 1
    assert len(server.search_products(limit=500)["data"]["products"]) == 6
    assert server.search_products(limit=2)["data"]["total_matches"] == 6


def test_search_bad_input_gives_a_plain_error(shop):
    for bad in ("<script>", "x", "http://a.com"):
        assert "not usable" in server.search_products(ingredient=bad)["error"]
    assert "must be text" in server.search_products(query=5)["error"]


def test_search_treats_like_symbols_as_text(shop):
    assert server.search_products(query="%")["data"]["total_matches"] == 0
    assert server.search_products(query="'; DROP TABLE products; --")["data"]["total_matches"] == 0
    assert server.search_products()["data"]["total_matches"] == 6


# ---- get_product_detail ------------------------------------------------------------------------ #

def test_product_detail_has_ingredients_in_label_order_and_a_patch_test_note(shop):
    answer = server.get_product_detail(shop["n1"])
    assert answer["source"] == mcp_text.SOURCES["products"]
    assert answer["data"]["name"] == "Bravo Serum"
    assert [i["name"] for i in answer["data"]["ingredients"]] == ["Water", "Glycerin", "Niacinamide"]
    assert "dermatologist" in answer["note"]


@pytest.mark.parametrize("bad", [0, -1, True, "1", 1.5, None, 2**70])
def test_product_detail_bad_id_gives_a_plain_error(shop, bad):
    assert server.get_product_detail(bad) == {"error": "product_id must be a whole number above 0."}


def test_product_detail_unknown_id(shop):
    assert server.get_product_detail(99999) == {"error": "No product has the id 99999."}


# ---- compare_products -------------------------------------------------------------------------- #

def test_compare_same_group_and_main_ingredient(shop):
    answer = server.compare_products(shop["n1"], shop["n2"])
    data = answer["data"]
    assert data["comparable"] is True and data["status"] == "ok"
    assert data["shared_main_ingredient_groups"] == ["niacinamide"]
    assert data["ingredients"]["shared"] == ["Water", "Niacinamide"]       # Water and Aqua are the same ingredient
    assert data["ingredients"]["only_a"] == ["Glycerin"]
    assert data["ingredients"]["only_b"] == ["Squalane"]
    assert data["a"]["loves_count"] == 900 and data["b"]["rating"] == 4.0
    assert "No verdict" in answer["note"]


def test_compare_gives_no_verdict_or_overlap_field(shop):
    data = server.compare_products(shop["n1"], shop["n2"])["data"]
    flat = json.dumps(data).lower()
    for word in ("better", "winner", "cheaper", "overlap", "similarity", "score"):
        assert word not in flat


def test_compare_different_groups_is_refused_with_basic_facts_only(shop):
    data = server.compare_products(shop["n1"], shop["m1"])["data"]
    assert data["comparable"] is False and data["status"] == "different_groups"
    assert data["message"] == "Product A is in Face Serums and product B is in Moisturizers, so they can't be compared fairly."
    assert "ingredients" not in data
    assert "rating" not in data["a"] and "loves_count" not in data["b"]


def test_compare_same_group_without_a_shared_main_ingredient_is_refused(shop):
    data = server.compare_products(shop["n1"], shop["c1"])["data"]
    assert data["comparable"] is False and data["status"] == "different_ingredients"
    assert "share no main ingredient group" in data["message"]


def test_compare_a_product_in_no_main_ingredient_group_is_refused(shop):
    data = server.compare_products(shop["n1"], shop["f1"])["data"]
    assert data["status"] == "no_main_ingredient"


def test_compare_same_product_and_bad_ids(shop):
    assert server.compare_products(shop["n1"], shop["n1"])["data"]["status"] == "same_product"
    assert server.compare_products(shop["n1"], 99999) == {"error": "No product has the id 99999."}
    assert server.compare_products(0, shop["n1"]) == {"error": "product_a_id must be a whole number above 0."}
    assert server.compare_products(shop["n1"], "x") == {"error": "product_b_id must be a whole number above 0."}


# ---- get_insights and list_groups -------------------------------------------------------------- #

def test_insights_overall_and_in_a_group(shop):
    for i in range(5):   # a group needs 5 products
        add(shop["db"], f"Filler {i}", group="Toners", brand="Filler Co", loves=10 + i)
    overall = server.get_insights()
    assert overall["source"] == mcp_text.SOURCES["insights"]
    assert overall["data"]["group"] is None
    assert overall["data"]["most_liked_brands"][0]["brand"] == "Dew Labs"
    assert overall["data"]["most_liked_products"][0]["name"] == "Bravo Serum"
    assert "not sales" in overall["source"]
    toners = server.get_insights("Toners")["data"]
    assert toners["group"] == "Toners"
    assert toners["most_liked_products"][0]["name"] == "Filler 4"
    assert toners["most_liked_brands"][0]["brand"] == "Dew Labs"          # brands stay overall


def test_insights_unknown_or_small_group_names_the_ones_available(shop):
    for i in range(5):
        add(shop["db"], f"Filler {i}", group="Toners")
    answer = server.get_insights("Nope")
    assert answer["error"].startswith('No group named "Nope" has enough products.')
    assert "Toners" in answer["error"]
    assert "has enough products" in server.get_insights("Moisturizers")["error"]    # only 1 product
    assert "must be text" in server.get_insights(3)["error"]


def test_list_groups_has_groups_of_two_or_more_products(shop):
    groups = server.list_groups()["data"]["groups"]
    assert groups == [{"name": "Face Serums", "products": 5}]


# ---- get_weather ------------------------------------------------------------------------------- #

SPRINGFIELDS = [
    ("Springfield", "Illinois", "United States", 39.8, -89.6),
    ("Springfield", "Missouri", "United States", 37.2, -93.3),
    ("Springfield", "Massachusetts", "United States", 42.1, -72.6),
    ("Springfield", "Ontario", "Canada", 42.8, -80.9),
]


def several_springfields(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([weather_api.place(*p) for p in SPRINGFIELDS])


def test_weather_for_a_city(shop, weather_api):
    answer = server.get_weather("Pune")
    assert answer["source"] == mcp_text.SOURCES["weather"]
    data = answer["data"]
    assert data["status"] == "ok"
    assert "tips" not in data and "guidance" not in data          # the page's own texts are not part of the data
    assert weather_api.count("forecast") == 1 and weather_api.count("air") == 1
    assert data["place_used"] == "Pune, Maharashtra, India"


def test_weather_with_coordinates_uses_them_directly(shop, weather_api):
    answer = server.get_weather(latitude=18.5, longitude=73.9)
    data = answer["data"]
    assert weather_api.count("geocoding") == 0                    # no place search
    assert weather_api.calls[0][1]["latitude"] == 18.5 and weather_api.calls[0][1]["longitude"] == 73.9
    assert data["status"] == "ok" and data["place_source"] == "coordinates"
    assert data["place"] == {"name": "Selected place", "region": None, "country": None,
                             "latitude": 18.5, "longitude": 73.9}
    assert data["other_matches"] == []
    assert data["uv"]["max"] == 7 and data["humidity"] == 37 and data["temperature_c"] == 26.7
    assert data["aqi"]["value"] == 42
    assert answer["source"] == mcp_text.SOURCES["weather"]


def test_weather_coordinates_keep_the_names_given_with_them(shop, weather_api):
    data = server.get_weather("Pune", "India", "Maharashtra", 18.5, 73.9)["data"]
    assert weather_api.count("geocoding") == 0
    assert data["place_used"] == "Pune, Maharashtra, India"


def test_weather_city_only_uses_the_top_match_and_names_two_alternatives(shop, weather_api):
    several_springfields(weather_api)
    answer = server.get_weather("Springfield")
    data = answer["data"]
    assert data["status"] == "ok" and data["place_source"] == "first match of the place search"
    assert data["place"] == {"name": "Springfield", "region": "Illinois", "country": "United States",
                             "latitude": 39.8, "longitude": -89.6}
    assert data["place_used"] == "Springfield, Illinois, United States"
    assert [(p["region"], p["country"]) for p in data["other_matches"]] == [
        ("Missouri", "United States"), ("Massachusetts", "United States")]
    assert all(set(p) == {"name", "region", "country", "latitude", "longitude"} for p in data["other_matches"])
    assert "choices" not in data
    assert (weather_api.count("forecast"), weather_api.count("air")) == (1, 1)    # the conditions are in the same call
    assert weather_api.calls[1][1]["latitude"] == 39.8
    assert data["uv"] is not None and data["aqi"] is not None
    assert answer["source"] == mcp_text.SOURCES["weather"]


def test_weather_country_and_region_narrow_the_match(shop, weather_api):
    several_springfields(weather_api)
    data = server.get_weather("Springfield", country="canada")["data"]
    assert data["place_used"] == "Springfield, Ontario, Canada" and data["other_matches"] == []
    data = server.get_weather("Springfield", country="United States", region="missouri")["data"]
    assert data["place_used"] == "Springfield, Missouri, United States"
    assert server.get_weather("Springfield", country="France") == {"error": mcp_text.MESSAGES["no_place"]}


def test_weather_no_match(shop, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([])
    assert server.get_weather("Nowhereville") == {"error": mcp_text.MESSAGES["no_place"]}
    assert weather_api.count("forecast") == 0


def test_weather_bad_input_gives_a_plain_error(shop, weather_api):
    bad_city = {"error": mcp_text.MESSAGES["bad_city"]}
    for bad in ("http://evil.example", "<b>", "a", "", 5, None):
        assert server.get_weather(bad) == bad_city
    assert server.get_weather("Pune", country="<b>") == bad_city
    assert server.get_weather("Pune", region=7) == bad_city
    for lat, lon in ((91, 0), (0, 181), (18.5, None), (None, 73.9), (float("nan"), 0)):
        assert server.get_weather(latitude=lat, longitude=lon) == bad_city
    assert weather_api.calls == []


def test_weather_network_error(shop, weather_api):
    import requests
    weather_api.error["geocoding"] = requests.ConnectionError("down")
    assert server.get_weather("Pune") == {"error": mcp_text.MESSAGES["weather_down"]}
    weather_api.error["forecast"] = weather_api.error["air"] = requests.ConnectionError("down")
    assert server.get_weather(latitude=18.5, longitude=73.9) == {"error": mcp_text.MESSAGES["weather_down"]}


def test_weather_with_one_service_down_still_names_the_place(shop, weather_api):
    import requests
    weather_api.error["air"] = requests.ConnectionError("down")
    data = server.get_weather("Pune")["data"]
    assert data["place_used"] == "Pune, Maharashtra, India"
    assert data["aqi"] is None and "air_quality" in data["missing"] and data["uv"] is not None


# ---- find_studies ------------------------------------------------------------------------------ #

def test_find_studies_lists_papers_with_a_source_and_a_listing_note(shop, pubmed_api):
    pubmed_api.add(11, "Niacinamide and the skin barrier", types=("Review",))
    pubmed_api.add(12, "A trial of niacinamide", types=("Randomized Controlled Trial",))
    answer = server.find_studies("Niacinamide")
    assert answer["source"] == mcp_text.SOURCES["studies"]
    assert answer["data"]["query"] == "niacinamide AND skin"
    assert [p["pmid"] for p in answer["data"]["papers"]] == ["11", "12"]
    assert answer["data"]["result_origin"] == "live"
    assert "does not mean a product works" in answer["note"]


def test_find_studies_reuses_a_saved_search(shop, pubmed_api):
    pubmed_api.add(11, "A paper")
    server.find_studies("retinol")
    calls = len(pubmed_api.calls)
    again = server.find_studies("retinol")
    assert again["data"]["result_origin"] == "cache" and len(pubmed_api.calls) == calls


def test_find_studies_bad_input_and_outage(shop, pubmed_api):
    import requests
    for bad in ("http://x.com", "a", "niacinamide: [x]", 4, None):
        assert server.find_studies(bad) == {"error": mcp_text.MESSAGES["bad_ingredient_study"]}
    assert pubmed_api.calls == []
    pubmed_api.error["esearch"] = requests.ConnectionError("down")
    assert server.find_studies("retinol") == {"error": mcp_text.MESSAGES["studies_down"]}


def test_find_studies_with_no_papers_is_an_empty_list_not_an_error(shop, pubmed_api):
    assert server.find_studies("unobtainium")["data"]["papers"] == []


# ---- check_avoid_list -------------------------------------------------------------------------- #

def test_avoid_list_found_with_the_matching_ingredient_names(shop):
    answer = server.check_avoid_list(shop["f1"], ["Fragrance", "alcohol", "paraben"])
    data = answer["data"]
    assert data["status"] == "found"
    assert [(m["term"], m["ingredients"]) for m in data["matches"]] == [
        ("fragrance", ["Parfum"]), ("alcohol", ["Alcohol Denat."])]   # fragrance = parfum, whole words
    assert data["lists"] == ["fragrance", "alcohol"]
    assert "Check the product label" in answer["note"] and "dermatologist" in answer["note"]


def test_avoid_list_matches_the_same_way_as_the_site(shop):
    assert server.check_avoid_list(shop["n2"], ["water"])["data"]["matches"][0]["ingredients"] == ["Aqua"]
    assert server.check_avoid_list(shop["n1"], ["niacin"])["data"]["status"] == "not_found"    # no partial words
    assert server.check_avoid_list(shop["n1"], ["NIACINAMIDE"])["data"]["status"] == "found"   # ignoring case


def test_avoid_list_not_found_is_never_called_safe(shop):
    answer = server.check_avoid_list(shop["n1"], ["fragrance"])
    assert answer["data"]["status"] == "not_found"
    assert answer["data"]["message"] == "None found in the listed ingredients."
    assert "only means nothing on the list was found" in answer["note"]


def test_avoid_list_product_without_ingredients_cannot_be_checked(shop):
    data = server.check_avoid_list(shop["bare"], ["fragrance"])["data"]
    assert data["status"] == "no_ingredients"
    assert data["message"] == "Ingredient list not available, can't check"


def test_avoid_list_bad_input(shop):
    assert "must be a list of 1 to 20" in server.check_avoid_list(shop["n1"], [])["error"]
    assert "must be a list of 1 to 20" in server.check_avoid_list(shop["n1"], ["x"] * 21)["error"]
    assert "must be a list of 1 to 20" in server.check_avoid_list(shop["n1"], "fragrance")["error"]
    assert server.check_avoid_list(shop["n1"], ["<b>", "a", 5]) == {"error": mcp_text.MESSAGES["no_usable_words"]}
    assert server.check_avoid_list(99999, ["fragrance"]) == {"error": "No product has the id 99999."}
    assert server.check_avoid_list(0, ["fragrance"]) == {"error": "product_id must be a whole number above 0."}


def test_avoid_list_words_are_not_stored(shop, caplog):
    server.check_avoid_list(shop["n1"], ["secretword"])
    with closing(get_db(shop["db"])) as conn:
        dump = "\n".join(conn.iterdump())
    assert "secretword" not in dump and "secretword" not in caplog.text


# ---- friendly errors and wording --------------------------------------------------------------- #

def test_an_unexpected_failure_hides_the_detail(shop, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail at C:\\path")
    monkeypatch.setattr(server.services, "list_groups", boom)
    assert server.list_groups() == {"error": mcp_text.MESSAGES["failed"]}


def test_our_fixed_texts_have_no_banned_wording():
    for name in ("SOURCES", "NOTES", "COMPARE_MESSAGES", "MESSAGES"):
        for key, value in getattr(mcp_text, name).items():
            assert not BANNED.search(value), f"{name}[{key}]"


def test_tool_descriptions_and_instructions_have_no_banned_wording():
    for tool in asyncio.run(server.mcp.list_tools()):
        assert not BANNED.search(tool.description), tool.name
        for prop, schema in tool.inputSchema.get("properties", {}).items():
            assert not BANNED.search(schema.get("description", "")), f"{tool.name}.{prop}"
    assert not BANNED.search(server.mcp.instructions)


def test_every_answer_has_a_named_source_and_clean_wording(shop, weather_api, pubmed_api):
    pubmed_api.add(1, "A paper")
    for _ in range(5):
        add(shop["db"], "Toner", group="Toners")
    answers = [
        server.search_products("serum"), server.get_product_detail(shop["n1"]),
        server.compare_products(shop["n1"], shop["n2"]), server.compare_products(shop["n1"], shop["m1"]),
        server.get_insights("Toners"), server.list_groups(), server.get_weather("Pune"),
        server.find_studies("niacinamide"), server.check_avoid_list(shop["f1"], ["fragrance"]),
        server.check_avoid_list(shop["n1"], ["fragrance"]), server.check_avoid_list(shop["bare"], ["fragrance"]),
        server.get_product_detail(0), server.get_weather("<b>"),
    ]
    for answer in answers:
        if "error" in answer:
            assert set(answer) == {"error"}
        else:
            assert answer["source"] in mcp_text.SOURCES.values()
        for line in own_text(answer):
            assert not BANNED.search(line), line
