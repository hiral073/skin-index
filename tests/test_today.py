import html as html_lib
import re
from contextlib import closing
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from content import today_tips as tips_content
from database.db import get_db
from live.weather import clear_cache

# Words the Today page must never use. ("recommend" is not here: the dermatologists' own guidance says
# "dermatologists recommend ...", quoted with its source.)
BANNED = ["safe", "best for", "treats", "cures", "good for", "suitable", "ideal for", "skin type", "acne",
          "wrinkle", "heals", "dupe", "not needed", "generally not needed", "unnecessary", "no need"]
SEASONS = ["winter", "summer", "monsoon", "spring", "autumn", "fall"]

AAD, WHO, JHM = tips_content.AAD, tips_content.WHO, tips_content.JHM
AAD_SUNSCREEN_TEXT = ("Dermatologists recommend broad-spectrum, SPF 30 or higher, water-resistant sunscreen on skin "
                      "not covered by clothing, reapplied about every two hours when outdoors and after swimming or sweating.")


def page(client, url="/today"):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def text(html):
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def content(html):
    """The Today section only (not the navigation bar or footer)."""
    return html.split('class="today-page"', 1)[1].split("</section>", 1)[0]


def card(html, card_id):
    return html.split(f'id="{card_id}">', 1)[1].split("</div>", 1)[0]


def items(block):
    return [text(li) for li in re.findall(r"<li>(.*?)</li>", block, re.S)]


def tiles(html):
    found = re.findall(r'tile-label">([^<]*)</div>\s*<div class="tile-value">(.*?)</div>(?:\s*<div class="tile-sub">(.*?)</div>)?',
                       html, re.S)
    return {text(label): (text(value), text(sub)) for label, value, sub in found}


def set_conditions(weather_api, uv_now=0.0, uv_max=6.85, aqi=42, humidity=37, temperature=26.7, pm2_5=8.1, hourly=None):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=uv_now, uv_max=uv_max, humidity=humidity,
                                                           temperature=temperature, hourly=hourly)
    weather_api.payload["air"] = weather_api.air(us_aqi=aqi, pm2_5=pm2_5)
    clear_cache()


def fresh(client, weather_api, url="/today", **conditions):
    set_conditions(weather_api, **conditions)
    return page(client, url)


# ---------------------------------------------------------------- the page

def test_default_page_shows_live_conditions_for_pune(client, weather_api):
    set_conditions(weather_api, uv_now=0, uv_max=6.85, aqi=116, humidity=37, temperature=26.7, pm2_5=24.6)
    html = page(client)
    t = text(content(html))
    assert "Pune, Maharashtra, India" in t and "Local time there: 2026-11-12 18:15" in t
    assert tiles(html) == {
        "UV now": ("0", "Low"),
        "UV today's max": ("7", "High"),
        "Humidity": ("37%", ""),
        "Temperature": ("26.7 °C", ""),
        "US AQI": ("116", "Unhealthy for sensitive groups · PM2.5 24.6 µg/m³"),
    }
    assert 'value="Pune"' in html
    assert weather_api.count("geocoding") == 0 and len(weather_api.calls) == 2


def test_requests_use_timezone_auto_hourly_uv_and_a_five_second_timeout(client, weather_api):
    page(client)
    assert all(timeout == 5 for _s, _p, timeout in weather_api.calls)
    assert all(params["timezone"] == "auto" for service, params, _t in weather_api.calls if service != "geocoding")
    forecast = [params for service, params, _t in weather_api.calls if service == "forecast"][0]
    assert forecast["hourly"] == "uv_index" and forecast["daily"] == "uv_index_max"


def test_labels_disclaimer_and_attribution(client, weather_api):
    for url in ("/today", "/today?city=zzzz", "/today?city=http://x.example"):
        html = page(client, url)
        assert "Live conditions, general information only. Not medical or dermatological advice." in text(html)
        assert "Weather data by Open-Meteo.com" in text(html)
        assert '<a href="https://open-meteo.com/">Open-Meteo.com</a>' in html
    t = text(page(client))
    assert "Air quality data from CAMS (Copernicus Atmosphere Monitoring Service), via Open-Meteo.com." in t
    assert "Location data from GeoNames" in t


def test_today_is_in_the_navigation_on_every_page(client, weather_api):
    for url in ("/", "/products", "/compare", "/insights", "/today"):
        assert '<a href="/today">Today</a>' in page(client, url)


def test_the_page_loads_on_an_empty_database_and_offline(client):
    html = page(client)                                                 # the network is blocked in tests
    assert "We couldn't get live conditions for Pune, Maharashtra, India right now." in text(html)
    assert "tile-value" not in html                                      # no made-up numbers


# ---------------------------------------------------------------- choosing a city

def test_one_match_goes_straight_to_the_conditions(client, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([weather_api.place("Oslo", "Oslo", "Norway", 59.9, 10.7)])
    html = page(client, "/today?city=Oslo")
    assert "Oslo, Oslo, Norway" in text(content(html)) and "tile-value" in html
    assert 'value="Oslo"' in html


def test_several_matches_show_up_to_five_choices_with_name_region_and_country(client, weather_api):
    places = [weather_api.place("Springfield", region, "United States", 37.0 + i, -90.0 - i)
              for i, region in enumerate(["Missouri", "Illinois", "Massachusetts", "Ohio", "Tennessee"])]
    weather_api.payload["geocoding"] = weather_api.geocoding(places)
    html = page(client, "/today?city=Springfield")
    assert "Several places match “Springfield”" in text(html)
    found = re.findall(r'<li><a href="([^"]+)">(.*?)</a></li>', content(html))
    assert [label for _href, label in found] == [
        "Springfield, Missouri, United States", "Springfield, Illinois, United States",
        "Springfield, Massachusetts, United States", "Springfield, Ohio, United States",
        "Springfield, Tennessee, United States",
    ]
    href = found[1][0].replace("&amp;", "&")
    assert urlparse(href).path == "/today"
    assert parse_qs(urlparse(href).query) == {"lat": ["38.0"], "lon": ["-91.0"],
                                              "label": ["Springfield, Illinois, United States"]}
    assert "tile-value" not in html and weather_api.count("forecast") == 0


def test_picking_a_choice_shows_that_place(client, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([
        weather_api.place("Springfield", "Missouri", "United States", 37.2, -93.3),
        weather_api.place("Springfield", "Illinois", "United States", 39.8, -89.6)])
    html = page(client, "/today?city=Springfield")
    href = re.findall(r'<li><a href="([^"]+)"', content(html))[1].replace("&amp;", "&")
    html = page(client, href)
    assert "Springfield, Illinois, United States" in text(content(html))
    _service, params, _t = weather_api.calls[-1]
    assert (params["latitude"], params["longitude"]) == (39.8, -89.6)


def test_no_match_shows_a_friendly_message(client, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([])
    html = page(client, "/today?city=zzzzqqqxx")
    assert "We couldn't find a place called “zzzzqqqxx”." in text(html)
    assert "tile-value" not in html and 'value="zzzzqqqxx"' in html


def test_geocoding_down_shows_a_friendly_message(client, weather_api):
    weather_api.error["geocoding"] = requests.Timeout("slow")
    html = page(client, "/today?city=Oslo")
    assert "We couldn't look up that city right now." in text(html) and "tile-value" not in html


# ---------------------------------------------------------------- input cleaning

def test_city_text_is_cleaned_before_it_is_used(client, weather_api):
    page(client, "/today?city=%20%20New%20%20%20York%20")
    assert weather_api.calls[0][1]["name"] == "New York"


@pytest.mark.parametrize("city", ["http://evil.example/x", "www.evil.example", "<script>alert(1)</script>",
                                  "a" * 61, "a/b", "%00", "x"])
def test_bad_city_text_is_refused_without_calling_anything(client, weather_api, city):
    html = client.get("/today", query_string={"city": city}).get_data(as_text=True)
    assert "Please enter a city name using letters" in text(html)
    assert weather_api.calls == [] and "<script>alert(1)</script>" not in html


def test_the_city_box_never_echoes_markup_and_has_a_length_limit(client, weather_api):
    html = client.get("/today", query_string={"city": "<b>x</b>"}).get_data(as_text=True)
    assert 'value="&lt;b&gt;x&lt;/b&gt;"' in html and "<b>x</b>" not in html
    assert 'maxlength="60"' in html


@pytest.mark.parametrize("query", ["lat=999&lon=10", "lat=abc&lon=10", "lat=10", "lon=10", "lat=nan&lon=nan"])
def test_bad_coordinates_in_the_link_are_refused(client, weather_api, query):
    html = page(client, f"/today?{query}")
    assert "That place link isn't valid." in text(html) and weather_api.calls == []


def test_a_label_in_the_link_is_cleaned_not_echoed(client, weather_api):
    html = client.get("/today", query_string={"lat": "1", "lon": "2", "label": "<script>x</script>"}).get_data(as_text=True)
    assert "Selected place" in text(content(html)) and "<script>x</script>" not in html
    html = client.get("/today", query_string={"lat": "1", "lon": "2", "label": "Oslo, Norway"}).get_data(as_text=True)
    assert "Oslo, Norway" in text(content(html))


def test_place_names_from_the_service_are_escaped(client, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([weather_api.place("<i>Odd</i> & Co", "R", "C", 1.0, 2.0)])
    html = page(client, "/today?city=Odd")
    assert "<i>Odd</i>" not in html and "&lt;i&gt;Odd&lt;/i&gt; &amp; Co" in html


# ---------------------------------------------------------------- partial data and failures

SUNSCREEN_ADVICE = "broad-spectrum, SPF 30 or higher"     # the AAD sunscreen sentence, full version
UV_LOW_LINE = ("UV is low right now. Dermatologists still recommend daily sunscreen on exposed skin "
               "when you're outdoors.")
SOURCES_NOTE = "General information from the sources named. Not medical advice."
DERMATOLOGIST_LINE = "see a board-certified dermatologist"
DAILY_ESSENTIAL = "Sun protection is a daily essential"


def uv_card_text(html):
    return text(card(html, "sun-protection"))


def test_both_services_down_shows_a_friendly_message_and_no_numbers(client, weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    weather_api.error["air"] = requests.ConnectionError("down")
    html = page(client)
    assert "We couldn't get live conditions for Pune, Maharashtra, India right now." in text(html)
    assert "tile-value" not in html                                      # not one made-up number
    assert uv_card_text(html) == "The UV index isn't available right now."
    assert 'id="weather-tips"' not in html and SUNSCREEN_ADVICE not in text(html)
    assert text(html).count(SOURCES_NOTE) == 1                           # the bottom note is still there


def test_air_quality_down_still_shows_the_rest(client, weather_api):
    weather_api.error["air"] = requests.Timeout("slow")
    html = page(client)
    shown = tiles(html)
    assert shown["US AQI"][0] == "Not available" and shown["Humidity"][0] == "37%" and shown["UV today's max"][0] == "7"
    assert "Air quality isn't available right now." in text(html)


def test_forecast_down_still_shows_the_air_quality(client, weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    html = page(client)
    shown = tiles(html)
    assert shown["US AQI"][0] == "42" and shown["UV now"][0] == "Not available" and shown["Humidity"][0] == "Not available"
    assert "Temperature, humidity and UV aren't available right now." in text(html)
    assert uv_card_text(html) == "The UV index isn't available right now."


def test_a_single_missing_value_is_marked_not_available(client, weather_api):
    html = fresh(client, weather_api, humidity=None)
    shown = tiles(html)
    assert shown["Humidity"][0] == "Not available" and shown["Temperature"][0] == "26.7 °C"


def test_missing_uv_alone_gives_the_unavailable_line_and_no_sunscreen_advice(client, weather_api):
    html = fresh(client, weather_api, uv_now=None, uv_max=None)
    assert uv_card_text(html) == "The UV index isn't available right now."
    assert SUNSCREEN_ADVICE not in text(html) and "sunscreen" not in text(content(html)).lower()


# ---------------------------------------------------------------- layout

def test_the_tips_card_comes_before_the_uv_card(client, weather_api):
    html = fresh(client, weather_api, temperature=10, humidity=50, uv_now=5, uv_max=5)
    assert html.index('id="weather-tips"') < html.index('id="sun-protection"')
    body = text(content(html))
    assert body.index("Skin-care tips for today's weather") < body.index("Sun protection today")


def test_there_is_no_every_day_box_and_no_always_tips(client, weather_api):
    for kwargs in ({}, {"temperature": 10, "humidity": 50}, {"temperature": 32, "humidity": 70},
                   {"uv_now": 0, "uv_max": 0}, {"uv_now": 1, "uv_max": 1}):
        body = text(fresh(client, weather_api, **kwargs))
        assert "Every day" not in body and DAILY_ESSENTIAL not in body


def test_the_dermatologist_line_is_gone_from_the_page_everywhere(client, weather_api):
    scenarios = [{}, {"temperature": 10, "humidity": 50}, {"temperature": 32, "humidity": 70}, {"uv_now": 0, "uv_max": 0},
                 {"uv_now": 1, "uv_max": 1}, {"uv_now": 9, "uv_max": 9}, {"uv_now": None, "uv_max": None}]
    for kwargs in scenarios:
        body = text(fresh(client, weather_api, **kwargs)).lower()
        assert DERMATOLOGIST_LINE not in body and "home care" not in body and "board-certified" not in body
    weather_api.error["forecast"] = weather_api.error["air"] = requests.Timeout("x")
    clear_cache()
    assert DERMATOLOGIST_LINE not in text(page(client)).lower()


def test_the_small_sources_note_is_at_the_bottom_once(client, weather_api):
    for kwargs in ({}, {"temperature": 10, "humidity": 50}, {"uv_now": 0, "uv_max": 0}, {"uv_now": 1, "uv_max": 1}):
        html = fresh(client, weather_api, **kwargs)
        assert text(html).count(SOURCES_NOTE) == 1
        assert html.index(SOURCES_NOTE) > html.index('id="sun-protection"')                       # below the UV card
        assert html.index(SOURCES_NOTE) < html.index("Live conditions, general information only.")  # above the label
        assert SOURCES_NOTE not in card(html, "sun-protection")                                    # not inside a card


def test_the_sources_note_is_not_shown_before_a_place_is_chosen(client, weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([])
    assert SOURCES_NOTE not in text(page(client, "/today?city=zzzz"))
    assert 'id="sun-protection"' not in page(client, "/today?city=http://x.example")


@pytest.mark.parametrize("scenario", ["choose", "no_match", "invalid", "geocoding_down"])
def test_the_cards_do_not_show_before_a_place_is_chosen(client, weather_api, scenario):
    url = "/today?city=Springfield"
    if scenario == "choose":
        weather_api.payload["geocoding"] = weather_api.geocoding(
            [weather_api.place("Springfield", f"S{i}", "US", 30.0 + i, -90.0) for i in range(3)])
    elif scenario == "no_match":
        weather_api.payload["geocoding"] = weather_api.geocoding([])
    elif scenario == "invalid":
        url = "/today?city=http://x.example"
    else:
        weather_api.error["geocoding"] = requests.Timeout("slow")
    html = page(client, url)
    assert 'id="sun-protection"' not in html and 'id="weather-tips"' not in html


# ---------------------------------------------------------------- the UV card

MODERATE = tips_content.EXTRA_STEPS["moderate_to_high"]["text"]
VERY_HIGH = tips_content.EXTRA_STEPS["very_high"]["text"]
REMINDERS = [
    "Sunscreen should not be used to extend the time you spend in the sun.",
    "Shade and clothing protect best.",
    "Reapply sunscreen even on cloudy days.",
    "Bright surfaces such as water and sand reflect UV.",
]


@pytest.mark.parametrize("peak", [2.5, 3, 5, 7, 8, 11])
def test_at_uv_3_or_higher_the_full_card_shows_everything_once(client, weather_api, peak):
    html = fresh(client, weather_api, uv_now=0, uv_max=peak, hourly={10: 3.2, 11: 4.0, 12: 6.8, 13: 5.0, 14: 3.1})
    block = uv_card_text(html)
    assert "UV today" in block and "UV is 3 or higher from 09:00 to 14:00." in block
    assert "Peak hour: 11:00–12:00, UV 7 (hourly average)." in block
    assert AAD_SUNSCREEN_TEXT + " Source: American Academy of Dermatology" in block
    assert "Also worth remembering" in block and items(card(html, "sun-protection")) == REMINDERS
    assert re.search(r'<a class="btn-primary" href="/products\?category=Sunscreen">Browse sunscreens</a>', html)
    assert "Check for SPF and broad-spectrum on the label." in block
    assert UV_LOW_LINE not in text(html) and "UV is very low today." not in text(html)
    assert text(html).count(SUNSCREEN_ADVICE) == 1 and text(html).lower().count("dermatologists") == 1


def test_the_full_card_can_list_several_ranges(client, weather_api):
    html = fresh(client, weather_api, uv_now=0, uv_max=5, hourly={10: 3, 11: 4, 12: 1, 13: 2, 14: 5, 15: 3})
    assert "UV is 3 or higher from 09:00 to 11:00 and 13:00 to 15:00." in uv_card_text(html)


def test_the_full_card_without_hourly_data_says_the_timeline_is_not_available(client, weather_api):
    html = fresh(client, weather_api, uv_now=0, uv_max=7)                # the fake sends no hourly data
    block = uv_card_text(html)
    assert "The hourly UV timeline isn't available right now." in block and "Peak hour" not in block
    assert AAD_SUNSCREEN_TEXT in block and MODERATE in block             # the rest of the full card still shows


def test_when_no_hourly_average_reaches_3_the_full_card_gives_only_the_peak_hour(client, weather_api):
    html = fresh(client, weather_api, uv_now=0, uv_max=3.2, hourly={11: 2.0, 12: 2.4})
    block = uv_card_text(html)
    assert "UV is 3 or higher from" not in block and "Peak hour: 11:00–12:00, UV 2 (hourly average)." in block
    assert AAD_SUNSCREEN_TEXT in block


@pytest.mark.parametrize("peak", [0.5, 1, 2, 2.4])
def test_from_uv_1_to_2_the_card_is_the_one_low_line_with_its_source(client, weather_api, peak):
    html = fresh(client, weather_api, uv_now=0, uv_max=peak, hourly={11: 2.0, 12: 2.4})
    block = card(html, "sun-protection")
    assert uv_card_text(html) == UV_LOW_LINE + " Source: American Academy of Dermatology"
    assert items(block) == [] and "<h3>" not in block and "btn-primary" not in block      # nothing else in the card
    body = text(html)
    assert "Peak hour" not in body and "UV is 3 or higher" not in body and "Also worth remembering" not in body
    assert SUNSCREEN_ADVICE not in body and MODERATE not in body and VERY_HIGH not in body
    assert "Browse sunscreens" not in html and "category=Sunscreen" not in html
    assert body.lower().count("dermatologists") == 1 and body.count("daily sunscreen") == 1


@pytest.mark.parametrize("peak", [0, 0.4])
def test_below_uv_1_the_card_says_only_that_uv_is_very_low(client, weather_api, peak):
    html = fresh(client, weather_api, uv_now=0, uv_max=peak, hourly={11: 0.4, 12: 0.4})
    assert uv_card_text(html) == "UV is very low today."
    body = text(html)
    assert "Peak hour" not in body and "sunscreen" not in text(content(html)).lower()
    assert "Dermatologists" not in body and "Browse sunscreens" not in html


def test_the_peak_hour_line_is_shown_only_at_uv_3_or_higher(client, weather_api):
    for peak, shown in ((0, False), (0.4, False), (1, False), (2.4, False), (2.5, True), (3, True)):
        html = fresh(client, weather_api, uv_now=0, uv_max=peak, hourly={12: max(peak, 0.1)})
        assert ("Peak hour" in text(html)) is shown, peak


@pytest.mark.parametrize("peak, card_kind", [(0.4, "very low"), (0.5, "low"), (2.4, "low"), (2.5, "full")])
def test_the_card_switches_at_the_rounded_boundaries(client, weather_api, peak, card_kind):
    body = uv_card_text(fresh(client, weather_api, uv_now=0, uv_max=peak, hourly={12: 3.0}))
    assert ("UV is very low today." in body) is (card_kind == "very low")
    assert (UV_LOW_LINE in body) is (card_kind == "low")
    assert ("Also worth remembering" in body) is (card_kind == "full")


def test_the_card_follows_the_days_peak_not_uv_now(client, weather_api):
    assert "Also worth remembering" in uv_card_text(fresh(client, weather_api, uv_now=0, uv_max=9))   # an evening visit
    assert uv_card_text(fresh(client, weather_api, uv_now=9, uv_max=1)) == UV_LOW_LINE + " Source: American Academy of Dermatology"


def test_with_no_peak_the_card_uses_uv_now(client, weather_api):
    assert "Also worth remembering" in uv_card_text(fresh(client, weather_api, uv_now=6, uv_max=None))
    assert uv_card_text(fresh(client, weather_api, uv_now=0, uv_max=None)) == "UV is very low today."


@pytest.mark.parametrize("peak", [2.5, 3, 5, 7, 7.4])
def test_who_steps_at_uv_3_to_7(client, weather_api, peak):
    block = uv_card_text(fresh(client, weather_api, uv_now=0, uv_max=peak))
    assert MODERATE + " Source: World Health Organization" in block and VERY_HIGH not in block


@pytest.mark.parametrize("peak", [7.5, 8, 10, 11])
def test_who_steps_at_uv_8_and_above(client, weather_api, peak):
    block = uv_card_text(fresh(client, weather_api, uv_now=0, uv_max=peak))
    assert VERY_HIGH + " Source: World Health Organization" in block and MODERATE not in block
    assert "Avoid being outside during midday hours where possible." in block


@pytest.mark.parametrize("peak", [0, 0.4, 1, 2, 2.4])
def test_no_who_steps_below_uv_3(client, weather_api, peak):
    assert "World Health Organization" not in text(fresh(client, weather_api, uv_now=0, uv_max=peak))


def test_the_sunscreens_link_leads_to_the_existing_products_page_filtered_to_sunscreen(app, client, weather_api):
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        for name, category, group in (("Day Shield", "Sunscreen", "Sunscreen"), ("Night Serum", "Treatments", "Face Serums")):
            conn.execute("INSERT INTO products (name, brand, category, compare_group, price, size_text, price_per_ml) VALUES (?, 'B', ?, ?, 10, '50 mL', 0.2)",
                         (name, category, group))
    html = fresh(client, weather_api, uv_now=5, uv_max=5)
    href = re.search(r'<a class="btn-primary" href="([^"]+)">Browse sunscreens', html).group(1)
    assert href == "/products?category=Sunscreen"
    listing = page(client, href)
    assert "Day Shield" in listing and "Night Serum" not in listing


@pytest.mark.parametrize("peak", [0, 0.4, 1, 2.4, 2.5, 3, 7, 8, 11])
def test_the_sunscreen_sentence_never_appears_twice_whatever_the_weather(client, weather_api, peak):
    for temperature, humidity in ((22, 50), (10, 20), (33, 80)):
        body = text(fresh(client, weather_api, uv_now=0, uv_max=peak, temperature=temperature, humidity=humidity))
        assert body.count(SUNSCREEN_ADVICE) <= 1 and body.lower().count("dermatologists") <= 1
        assert body.count("Dermatologists") + body.count("dermatologists") <= 1


@pytest.mark.parametrize("uv", [0, 0.4, 1, 2, 2.4, 2.5, 3, 8, 11])
def test_no_line_says_sun_protection_is_not_needed_at_any_uv(client, weather_api, uv):
    body = text(fresh(client, weather_api, uv_now=uv, uv_max=uv)).lower()
    for phrase in ("not needed", "generally not needed", "unnecessary", "no need", "don't need", "do not need", "most people"):
        assert phrase not in body, (uv, phrase)


@pytest.mark.parametrize("aqi, shown", [(50, False), (100, False), (101, True), (180, True), (350, True)])
def test_the_health_advisory_line_appears_only_above_moderate_and_is_all_there_is(client, weather_api, aqi, shown):
    html = fresh(client, weather_api, aqi=aqi)
    t = text(content(html))
    assert ("Air quality is above Moderate. Check your local health advisories." in t) is shown
    assert "Humidity, temperature and air quality are shown for information only." in t


# ---------------------------------------------------------------- "Skin-care tips for today's weather"

COOL_DRY = [t["text"] for t in tips_content.COOL_DRY_TIPS]
HOT_HUMID = [t["text"] for t in tips_content.HOT_HUMID_TIPS]


def tip_items(html):
    return items(card(html, "weather-tips"))


def tip_text(item):
    return item.split(" Source: ")[0]


def headlines(html):
    return [text(h) for h in re.findall(r"<h3>(.*?)</h3>", card(html, "weather-tips"), re.S)]


@pytest.mark.parametrize("temperature, humidity, headline", [
    (15.0, 50, "Cool air today"),                    # at the cool cutoff
    (20.0, 35.0, "Dry air today"),                   # at the dry cutoff
    (15.0, 35.0, "Cool, dry air today"),
    (5.0, 20, "Cool, dry air today"),
])
def test_cool_or_dry_tips_show_at_and_beyond_the_cutoffs(client, weather_api, temperature, humidity, headline):
    html = fresh(client, weather_api, temperature=temperature, humidity=humidity)
    assert "Skin-care tips for today's weather" in text(content(html))
    assert headlines(html) == [headline]
    assert [tip_text(i) for i in tip_items(html)] == COOL_DRY


@pytest.mark.parametrize("temperature, humidity", [(15.1, 50), (20.0, 35.1), (22.0, 40), (29.9, 60), (30.0, 59.9)])
def test_just_above_the_cool_or_dry_cutoffs_and_just_below_hot_and_humid_there_is_no_tips_card(client, weather_api, temperature, humidity):
    html = fresh(client, weather_api, temperature=temperature, humidity=humidity)
    assert 'id="weather-tips"' not in html and "Skin-care tips for today's weather" not in text(html)
    assert 'id="sun-protection"' in html                                 # the UV card still shows


@pytest.mark.parametrize("temperature, humidity", [(30.0, 60), (35.0, 90), (30.1, 61)])
def test_hot_and_humid_tips_show_at_and_beyond_the_cutoffs(client, weather_api, temperature, humidity):
    html = fresh(client, weather_api, temperature=temperature, humidity=humidity)
    assert headlines(html) == ["Hot and humid today"]
    assert [tip_text(i) for i in tip_items(html)] == HOT_HUMID


def test_hot_but_dry_air_gets_the_dry_tips_not_the_hot_and_humid_ones(client, weather_api):
    html = fresh(client, weather_api, temperature=32, humidity=30)
    assert headlines(html) == ["Dry air today"]
    assert not any(t in text(card(html, "weather-tips")) for t in HOT_HUMID)


@pytest.mark.parametrize("temperature, humidity, expected", [
    (None, 30, "Dry air today"), (10.0, None, "Cool air today"),           # one reading is enough for cool or dry
    (None, 80, None), (35.0, None, None), (None, None, None), (None, 50, None),   # hot and humid needs both
])
def test_a_missing_temperature_or_humidity_never_makes_up_a_group(client, weather_api, temperature, humidity, expected):
    html = fresh(client, weather_api, temperature=temperature, humidity=humidity)
    if expected:
        assert headlines(html) == [expected]
    else:
        assert 'id="weather-tips"' not in html


def test_when_the_weather_is_unavailable_there_is_no_tips_card(client, weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    assert 'id="weather-tips"' not in page(client)


def test_air_quality_never_changes_the_tips(client, weather_api):
    assert 'id="weather-tips"' not in fresh(client, weather_api, temperature=22, humidity=50, aqi=400)
    assert headlines(fresh(client, weather_api, temperature=10, humidity=50, aqi=400)) == ["Cool air today"]


def test_every_tip_shows_its_source_label(client, weather_api):
    for temperature, humidity in ((10, 20), (32, 70)):
        shown = tip_items(fresh(client, weather_api, temperature=temperature, humidity=humidity))
        assert shown and all(re.search(r" Source: (American Academy of Dermatology|Johns Hopkins Medicine)$", i) for i in shown)
    html = fresh(client, weather_api, temperature=32, humidity=70)
    by_text = {tip_text(i): i.split(" Source: ")[1] for i in tip_items(html)}
    assert by_text["Shower, cool down and dry off when you are hot and sweaty; use a mild cleanser daily and avoid heavy makeup."] == JHM
    assert by_text["Wash sweaty clothes, headbands, towels and hats before wearing them again."] == AAD


def test_only_the_supplied_tips_are_shown_never_extra_ones(client, weather_api):
    allowed = set(COOL_DRY + HOT_HUMID)
    for temperature, humidity in ((10, 20), (32, 70), (22, 50), (None, None)):
        html = fresh(client, weather_api, temperature=temperature, humidity=humidity)
        assert {tip_text(i) for i in tip_items(html)} <= allowed if 'id="weather-tips"' in html else True


def hrefs(html):
    return [(h.replace("&amp;", "&"), text(label)) for h, label in
            re.findall(r'<a class="btn-ghost" href="([^"]+)">(.*?)</a>', card(html, "weather-tips"))]


def test_cool_dry_link_goes_to_moisturizers_filtered_by_cream(client, weather_api):
    found = hrefs(fresh(client, weather_api, temperature=10, humidity=50))
    assert [label for _h, label in found] == ["Browse moisturizers with 'cream' in the name"]
    parsed = urlparse(found[0][0])
    assert parsed.path == "/products" and parse_qs(parsed.query) == {"category": ["Moisturizers"], "q": ["cream"]}


def test_hot_humid_links_go_to_cleansers_and_moisturizers(client, weather_api):
    found = hrefs(fresh(client, weather_api, temperature=32, humidity=70))
    assert [label for _h, label in found] == ["Browse cleansers", "Browse moisturizers"]
    assert [parse_qs(urlparse(h).query) for h, _l in found] == [{"category": ["Face Wash & Cleansers"]}, {"category": ["Moisturizers"]}]


def test_the_browse_links_lead_to_existing_group_filters(app, client, weather_api):
    with closing(get_db(app.config["DATABASE"])) as conn, conn:
        for name, category, group in (("Rich Cream", "Moisturizers", "Moisturizers"), ("Light Lotion", "Moisturizers", "Moisturizers"),
                                      ("Foam Wash", "Cleansers", "Face Wash & Cleansers"), ("Day Shield", "Sunscreen", "Sunscreen")):
            conn.execute("INSERT INTO products (name, brand, category, compare_group, price, size_text, price_per_ml) VALUES (?, 'B', ?, ?, 10, '50 mL', 0.2)",
                         (name, category, group))
    products = page(client, "/products")
    assert '<option value="Moisturizers"' in products and '<option value="Face Wash &amp; Cleansers"' in products

    cool = hrefs(fresh(client, weather_api, temperature=10, humidity=50))[0][0]
    listing = page(client, cool)
    assert "Rich Cream" in listing and "Light Lotion" not in listing and "Foam Wash" not in listing

    hot = dict((label, h) for h, label in hrefs(fresh(client, weather_api, temperature=32, humidity=70)))
    listing = page(client, hot["Browse cleansers"])
    assert "Foam Wash" in listing and "Rich Cream" not in listing
    listing = page(client, hot["Browse moisturizers"])
    assert "Rich Cream" in listing and "Light Lotion" in listing and "Foam Wash" not in listing


def test_the_only_product_links_on_the_page_are_the_sunscreen_and_the_browse_links(client, weather_api):
    allowed = {"/products?category=Sunscreen", "/products?category=Moisturizers&q=cream",
               "/products?category=Face+Wash+%26+Cleansers", "/products?category=Moisturizers"}
    for temperature, humidity, uv in ((10, 20, 9), (32, 70, 5), (22, 50, 0), (10, 50, 1)):
        html = fresh(client, weather_api, temperature=temperature, humidity=humidity, uv_now=uv, uv_max=uv)
        found = {h.replace("&amp;", "&") for h in re.findall(r'href="(/products[^"]*)"', content(html))}
        assert found <= allowed


def test_the_headlines_name_conditions_never_seasons(client, weather_api):
    for temperature, humidity in ((10, 20), (32, 70), (22, 50), (10, 50), (20, 20)):
        body = text(content(fresh(client, weather_api, temperature=temperature, humidity=humidity))).lower()
        assert not any(re.search(rf"\b{season}\b", body) for season in SEASONS)


# ---------------------------------------------------------------- the content file

# The texts exactly as supplied, written out here so an edit to the content file is caught
SUPPLIED_COOL_DRY = [(text_, "American Academy of Dermatology") for text_ in (
    "Apply moisturizer right after washing to help trap moisture.",
    "Creams and ointments are usually more effective and less irritating than lotions for dry skin.",
    "Use warm, not hot, water for baths and showers.",
    "Gentle, fragrance-free skin care products tend to suit dry, sensitive skin.",
    "A cool-mist humidifier in the bedroom can help with indoor dryness.",
)]
SUPPLIED_HOT_HUMID = [
    ("Blot sweat with a clean towel; wiping it off can irritate skin and lead to a breakout.",
     "American Academy of Dermatology"),
    ("Wash sweaty clothes, headbands, towels and hats before wearing them again.",
     "American Academy of Dermatology"),
    ("Shower, cool down and dry off when you are hot and sweaty; use a mild cleanser daily and avoid heavy makeup.",
     "Johns Hopkins Medicine"),
    ("Humid air can still leave skin dry and irritated, especially after sun, pools and air-conditioning.",
     "American Academy of Dermatology"),
]


def test_the_texts_and_sources_are_exactly_the_supplied_ones():
    c = tips_content
    as_pairs = lambda tips_: [(t_["text"], t_["source"]) for t_ in tips_]    # noqa: E731
    assert as_pairs(c.COOL_DRY_TIPS) == SUPPLIED_COOL_DRY
    assert as_pairs(c.HOT_HUMID_TIPS) == SUPPLIED_HOT_HUMID
    assert c.HEADLINES == {"cool_dry": "Cool, dry air today", "cool": "Cool air today",
                           "dry": "Dry air today", "hot_humid": "Hot and humid today"}
    assert c.SOURCES_NOTE == SOURCES_NOTE
    assert c.REMINDERS["tips"] == REMINDERS
    assert c.SUN_PROTECTION["text"] == AAD_SUNSCREEN_TEXT and c.SUN_PROTECTION["source"] == AAD
    assert c.UV_LOW == {"text": UV_LOW_LINE, "source": AAD}
    assert c.UV_VERY_LOW == "UV is very low today."
    assert c.EXTRA_STEPS["moderate_to_high"] == {
        "text": "Seek shade during midday hours, cover up with clothing, wear a hat and use sunscreen.", "source": WHO}
    assert c.EXTRA_STEPS["very_high"] == {
        "text": "Avoid being outside during midday hours where possible. Seek shade, and wear a shirt, a hat and sunscreen.",
        "source": WHO}
    assert c.SUNSCREEN_LINK == {"label": "Browse sunscreens", "note": "Check for SPF and broad-spectrum on the label."}
    assert c.TIP_LINKS == {
        "cool_dry": [{"label": "Browse moisturizers with 'cream' in the name", "category": "Moisturizers", "q": "cream"}],
        "hot_humid": [{"label": "Browse cleansers", "category": "Face Wash & Cleansers"},
                      {"label": "Browse moisturizers", "category": "Moisturizers"}],
    }


def test_the_every_day_tips_and_the_dermatologist_line_are_gone_from_the_content_file():
    assert not hasattr(tips_content, "ALWAYS_TIPS") and not hasattr(tips_content, "ALWAYS_TITLE")
    assert not hasattr(tips_content, "TIPS_FOOTER")
    source_code = open(tips_content.__file__, encoding="utf-8").read().lower()
    for phrase in ("board-certified", "home care", "daily essential", "every day", "always_tips"):
        assert phrase not in source_code, phrase


def all_content_texts():
    c = tips_content
    texts = [c.SUN_PROTECTION["text"], c.SOURCES_NOTE, c.SUNSCREEN_LINK["note"], c.UV_LOW["text"], c.UV_VERY_LOW]
    texts += c.REMINDERS["tips"] + [s["text"] for s in c.EXTRA_STEPS.values()]
    texts += [t["text"] for group in (c.COOL_DRY_TIPS, c.HOT_HUMID_TIPS) for t in group]
    texts += list(c.HEADLINES.values()) + list(c.TIMELINE.values())
    texts += [link["label"] for links in c.TIP_LINKS.values() for link in links]
    return texts


def test_every_attributed_text_has_a_known_source_and_no_text_is_blank():
    c = tips_content
    attributed = c.COOL_DRY_TIPS + c.HOT_HUMID_TIPS + list(c.EXTRA_STEPS.values()) + [c.SUN_PROTECTION, c.UV_LOW]
    assert all(item["text"].strip() and item["source"] in (AAD, WHO, JHM) for item in attributed)
    assert all(text_.strip() for text_ in all_content_texts())
    assert len(c.COOL_DRY_TIPS) == 5 and len(c.HOT_HUMID_TIPS) == 4


def test_the_content_file_uses_none_of_the_banned_words():
    for text_ in all_content_texts():
        for word in BANNED:
            assert word not in text_.lower(), (word, text_)


def test_the_tip_groups_and_links_match_what_the_service_can_return():
    assert set(tips_content.TIP_GROUPS) == {"cool_dry", "hot_humid"}
    assert set(tips_content.HEADLINES) == {"cool_dry", "cool", "dry", "hot_humid"}
    assert set(tips_content.TIP_LINKS) == {"cool_dry", "hot_humid"}
    assert set(tips_content.EXTRA_STEPS) == {"moderate_to_high", "very_high"}


# ---------------------------------------------------------------- wording on the whole page

SCENARIOS = {
    "default": {}, "uv_high": {"uv_now": 9, "uv_max": 9}, "uv_low": {"uv_now": 1, "uv_max": 1},
    "uv_very_low": {"uv_now": 0, "uv_max": 0}, "no_uv": {"uv_now": None, "uv_max": None},
    "hours": {"hourly": {10: 3, 11: 6, 12: 8}}, "extreme_aqi": {"aqi": 400, "humidity": 99},
    "cool_dry": {"temperature": 5, "humidity": 20}, "hot_humid": {"temperature": 33, "humidity": 80},
    "peak": {"uv_now": 0, "uv_max": 8},
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_the_whole_page_never_uses_the_banned_wording(client, weather_api, scenario):
    html = fresh(client, weather_api, **SCENARIOS[scenario])
    body = text(html).lower()                                           # navigation and footer included
    for word in BANNED:
        assert word not in body, (scenario, word)


@pytest.mark.parametrize("state", ["choose", "no_match", "down", "partial", "bad_city", "unavailable_place"])
def test_error_and_choice_pages_never_use_the_banned_wording(client, weather_api, state):
    url = "/today"
    if state == "choose":
        weather_api.payload["geocoding"] = weather_api.geocoding(
            [weather_api.place("Springfield", f"State {i}", "United States", 30.0 + i, -90.0) for i in range(3)])
        url = "/today?city=Springfield"
    elif state == "no_match":
        weather_api.payload["geocoding"] = weather_api.geocoding([])
        url = "/today?city=zzzz"
    elif state == "down":
        weather_api.error["forecast"] = requests.Timeout("x")
        weather_api.error["air"] = requests.Timeout("x")
    elif state == "partial":
        weather_api.error["air"] = requests.Timeout("x")
    elif state == "bad_city":
        url = "/today?city=http://x.example"
    elif state == "unavailable_place":
        weather_api.error["geocoding"] = requests.Timeout("x")
        url = "/today?city=Oslo"
    body = text(page(client, url)).lower()
    for word in BANNED:
        assert word not in body, (state, word)


# ---------------------------------------------------------------- cache through the page

def test_repeat_visits_within_fifteen_minutes_do_not_call_the_api_again(client, weather_api, weather_clock):
    page(client)
    page(client)
    page(client, "/today?city=")
    assert len(weather_api.calls) == 2
    weather_clock.advance(15 * 60 + 1)
    page(client)
    assert len(weather_api.calls) == 4


def test_a_different_city_is_a_separate_cache_entry(client, weather_api):
    page(client)
    page(client, "/today?lat=59.9&lon=10.7&label=Oslo")
    assert len(weather_api.calls) == 4
    page(client, "/today?lat=59.9&lon=10.7&label=Oslo")
    assert len(weather_api.calls) == 4


def test_an_outage_is_not_hammered_by_repeat_visits(client, weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    weather_api.error["air"] = requests.Timeout("slow")
    for _ in range(4):
        page(client)
    assert len(weather_api.calls) == 2                                  # one try each, then remembered for 10 seconds
