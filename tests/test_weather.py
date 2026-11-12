import math

import pytest
import requests

import live.weather as weather
from database.services import (
    TODAY_CONFIG, clean_place_text, get_today_conditions, parse_coordinates, uv_timeline, whole_number,
)
from live.weather import WeatherError, fetch_air_quality, fetch_forecast, search_places

PUNE = (18.51957, 73.85535)


def place(name, region="Region", country="Country", lat=10.0, lon=20.0):
    return {"name": name, "region": region, "country": country, "latitude": lat, "longitude": lon}


# ---------------------------------------------------------------- places (geocoding)

def test_search_places_reads_the_fields_and_asks_for_five_with_a_timeout(weather_api):
    [found] = search_places("Pune")
    assert found == {"name": "Pune", "region": "Maharashtra", "country": "India", "latitude": 18.51957,
                     "longitude": 73.85535, "timezone": "Asia/Kolkata"}
    [(service, params, timeout)] = weather_api.calls
    assert service == "geocoding" and timeout == 5
    assert params == {"name": "Pune", "count": 5, "language": "en", "format": "json"}


def test_search_places_never_returns_more_than_five(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding(
        [weather_api.place(f"Town {i}", "R", "C", 10.0 + i, 20.0) for i in range(8)])
    assert len(search_places("Town")) == 5


def test_search_places_no_match_has_no_results_key_and_gives_an_empty_list(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([])
    assert "results" not in weather_api.payload["geocoding"]
    assert search_places("zzzzqqqxx") == []


def test_search_places_skips_unusable_results_and_missing_region(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([
        weather_api.place("No Region", None, "Country", 1.0, 2.0),
        {"name": "No Coordinates", "country": "C"},
        weather_api.place("Bad Latitude", "R", "C", 95.0, 2.0),
        weather_api.place("Bad Longitude", "R", "C", 5.0, 200.0),
        {"latitude": 1.0, "longitude": 2.0},                    # no name
        "not a dict",
    ])
    assert [(p["name"], p["region"]) for p in search_places("x")] == [("No Region", None)]


@pytest.mark.parametrize("error", [requests.Timeout("slow"), requests.ConnectionError("down")])
def test_search_places_network_errors_become_weather_error(weather_api, error):
    weather_api.error["geocoding"] = error
    with pytest.raises(WeatherError, match="Could not reach the weather service"):
        search_places("Pune")


def test_search_places_http_error_bad_json_and_error_replies(weather_api):
    weather_api.status["geocoding"] = 500
    with pytest.raises(WeatherError):
        search_places("a1")
    weather_api.status["geocoding"] = 200
    weather_api.payload["geocoding"] = ValueError("not json")
    with pytest.raises(WeatherError):
        search_places("a2")
    weather_api.payload["geocoding"] = ["a", "list"]
    with pytest.raises(WeatherError, match="could not read"):
        search_places("a3")
    weather_api.payload["geocoding"] = {"error": True, "reason": "Parameter count must be between 1 and 100."}
    with pytest.raises(WeatherError, match="Parameter count"):
        search_places("a4")


# ---------------------------------------------------------------- forecast

def test_fetch_forecast_reads_current_and_todays_max_and_sends_the_right_request(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=2.6, uv_max=6.85, humidity=37, temperature=26.7)
    got = fetch_forecast(*PUNE)
    assert got == {"time": "2026-11-12T18:15", "temperature_c": 26.7, "humidity": 37.0, "uv_now": 2.6, "uv_max": 6.85,
                   "uv_hourly": []}
    [(service, params, timeout)] = weather_api.calls
    assert service == "forecast" and timeout == 5
    assert params == {
        "latitude": 18.52, "longitude": 73.86,                       # coordinates rounded to 2 decimals
        "current": "temperature_2m,relative_humidity_2m,uv_index", "hourly": "uv_index",
        "daily": "uv_index_max", "forecast_days": 1, "timezone": "auto",
    }


@pytest.mark.parametrize("field, value", [
    ("humidity", 150), ("humidity", -1), ("uv_now", -0.5), ("uv_now", 99), ("temperature", 200), ("temperature", -200),
    ("humidity", "80"), ("uv_now", True), ("humidity", float("nan")),
])
def test_implausible_forecast_values_become_missing_not_repaired(weather_api, field, value):
    kwargs = {"uv_now": 3.0, "uv_max": 6.0, "humidity": 50, "temperature": 20.0}
    kwargs[field] = value
    weather_api.payload["forecast"] = weather_api.forecast(**kwargs)
    got = fetch_forecast(*PUNE)
    key = {"humidity": "humidity", "uv_now": "uv_now", "temperature": "temperature_c"}[field]
    assert got[key] is None
    assert sum(v is not None for k, v in got.items() if k not in ("time", "uv_hourly")) == 3      # the rest survive


def test_partial_forecast_keeps_what_is_there(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=None, uv_max=None, humidity=61, temperature=None)
    got = fetch_forecast(*PUNE)
    assert got["humidity"] == 61.0 and got["uv_now"] is None and got["uv_max"] is None and got["temperature_c"] is None


def test_forecast_with_nothing_usable_is_an_error(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=None, uv_max=None, humidity=None, temperature=None)
    with pytest.raises(WeatherError, match="no usable conditions"):
        fetch_forecast(*PUNE)
    weather_api.payload["forecast"] = {"latitude": 1}
    with pytest.raises(WeatherError):
        fetch_forecast(1.0, 2.0)


def test_a_bad_daily_list_is_just_missing(weather_api):
    payload = weather_api.forecast()
    payload["daily"]["uv_index_max"] = []
    weather_api.payload["forecast"] = payload
    assert fetch_forecast(*PUNE)["uv_max"] is None
    payload["daily"]["uv_index_max"] = "7"
    assert fetch_forecast(1.0, 1.0)["uv_max"] is None


def test_a_bad_reading_time_is_dropped(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(time="not a time")
    assert fetch_forecast(*PUNE)["time"] is None


# ---------------------------------------------------------------- air quality

def test_fetch_air_quality_reads_aqi_and_pm25_and_sends_the_right_request(weather_api):
    weather_api.payload["air"] = weather_api.air(us_aqi=116, pm2_5=24.6)
    assert fetch_air_quality(*PUNE) == {"time": "2026-11-12T17:30", "us_aqi": 116.0, "pm2_5": 24.6}
    [(service, params, timeout)] = weather_api.calls
    assert service == "air" and timeout == 5
    assert params == {"latitude": 18.52, "longitude": 73.86, "current": "us_aqi,pm2_5", "timezone": "auto"}


def test_air_quality_partial_and_empty(weather_api):
    weather_api.payload["air"] = weather_api.air(us_aqi=None, pm2_5=12.0)
    assert fetch_air_quality(*PUNE)["us_aqi"] is None
    weather_api.payload["air"] = weather_api.air(us_aqi=None, pm2_5=None)
    with pytest.raises(WeatherError, match="no usable values"):
        fetch_air_quality(1.0, 1.0)
    weather_api.payload["air"] = weather_api.air(us_aqi=5000, pm2_5=-3)
    with pytest.raises(WeatherError):
        fetch_air_quality(2.0, 2.0)


def test_air_quality_errors(weather_api):
    weather_api.error["air"] = requests.Timeout("slow")
    with pytest.raises(WeatherError):
        fetch_air_quality(*PUNE)


# ---------------------------------------------------------------- cache

def test_a_repeat_within_fifteen_minutes_makes_no_new_request(weather_api, weather_clock):
    fetch_forecast(*PUNE)
    weather_clock.advance(14 * 60 + 59)
    fetch_forecast(*PUNE)
    assert weather_api.count("forecast") == 1
    weather_clock.advance(2)                                       # past 15 minutes
    fetch_forecast(*PUNE)
    assert weather_api.count("forecast") == 2


def test_each_service_and_place_has_its_own_cache_entry(weather_api):
    fetch_forecast(*PUNE)
    fetch_air_quality(*PUNE)
    fetch_forecast(10.0, 20.0)
    search_places("Pune")
    assert [c[0] for c in weather_api.calls] == ["forecast", "air", "forecast", "geocoding"]
    fetch_forecast(18.5201, 73.8551)                               # rounds to the same grid point as PUNE (18.52, 73.86)
    search_places("PUNE")                                          # same name, other case
    assert len(weather_api.calls) == 4
    fetch_forecast(18.5201, 73.8449)                               # (18.52, 73.84): a different point
    assert len(weather_api.calls) == 5


def test_places_are_cached_ignoring_case(weather_api):
    search_places("Pune")
    search_places("pune")
    search_places("PUNE")
    assert weather_api.count("geocoding") == 1


def test_a_failure_is_remembered_for_a_few_seconds_so_an_outage_is_not_hammered(weather_api, weather_clock):
    weather_api.error["forecast"] = requests.Timeout("slow")
    for _ in range(3):
        with pytest.raises(WeatherError):
            fetch_forecast(*PUNE)
    assert weather_api.count("forecast") == 1
    weather_clock.advance(9)
    with pytest.raises(WeatherError):
        fetch_forecast(*PUNE)
    assert weather_api.count("forecast") == 1       # still inside the 10 seconds
    weather_clock.advance(2)
    weather_api.error["forecast"] = None
    assert fetch_forecast(*PUNE)["humidity"] == 37.0
    assert weather_api.count("forecast") == 2


def test_a_cached_answer_is_a_copy_so_callers_cannot_change_it(weather_api):
    first = fetch_forecast(*PUNE)
    first["humidity"] = 0.0
    assert fetch_forecast(*PUNE)["humidity"] == 37.0


def test_the_cache_is_bounded(weather_api, weather_clock):
    for i in range(weather.WEATHER_CONFIG["cache_max_entries"] + 50):
        weather_clock.advance(1)
        search_places(f"Town {i}")
    assert len(weather._cache) <= weather.WEATHER_CONFIG["cache_max_entries"]
    assert ("places", "town 249") in weather._cache and ("places", "town 0") not in weather._cache   # oldest left first


# ---------------------------------------------------------------- text and coordinate cleaning

@pytest.mark.parametrize("raw, cleaned", [
    ("Pune", "Pune"), ("  Pune  ", "Pune"), ("New\n   York", "New York"), ("St. Louis", "St. Louis"),
    ("Saint-Denis", "Saint-Denis"), ("Côte d’Ivoire", "Côte d’Ivoire"), ("O'Fallon", "O'Fallon"),
    ("Springfield, Illinois", "Springfield, Illinois"), ("411001", "411001"), ("München", "München"),
    ("a" * 60, "a" * 60), ("São Paulo", "São Paulo"),
])
def test_clean_place_text_keeps_real_city_names(raw, cleaned):
    assert clean_place_text(raw, 60) == cleaned


@pytest.mark.parametrize("raw", [
    "", " ", "a", "a" * 61, None, 5, "http://evil.example", "https://evil.example/path", "www.evil.example",
    "evil.example", "a/b", "a\\b", "a:b", "<script>alert(1)</script>", "a%20b", "a_b", "...", "--", "a@b.com",
    "?q=1", "Pune; DROP TABLE", "Pune&x=1", "Pune#top", "{city}", "Pune (India)", "ftp://x",
])
def test_clean_place_text_refuses_links_markup_and_odd_characters(raw):
    assert clean_place_text(raw, 60) is None


def test_a_label_may_have_brackets_but_nothing_else_odd():
    assert clean_place_text("Kamphaeng Phet (Province)", 100, allow_parentheses=True) == "Kamphaeng Phet (Province)"
    assert clean_place_text("Kamphaeng Phet (Province)", 100) is None
    assert clean_place_text("x" * 101, 100, allow_parentheses=True) is None


@pytest.mark.parametrize("lat, lon, expected", [
    ("18.5", "73.8", (18.5, 73.8)), (18.5, 73.8, (18.5, 73.8)), (-90, 180, (-90.0, 180.0)), (90, -180, (90.0, -180.0)),
])
def test_parse_coordinates_valid(lat, lon, expected):
    assert parse_coordinates(lat, lon) == expected


@pytest.mark.parametrize("lat, lon", [
    ("abc", "1"), ("1", "abc"), (None, "1"), ("1", None), (91, 0), (-91, 0), (0, 181), (0, -181),
    (float("nan"), 0), (0, float("inf")), ("nan", "1"), ("inf", "1"), (True, 0), ("", ""),
])
def test_parse_coordinates_invalid(lat, lon):
    assert parse_coordinates(lat, lon) is None


# ---------------------------------------------------------------- categories and rounding

def test_config_holds_every_threshold_and_label():
    assert TODAY_CONFIG["uv_categories"] == [(2, "Low"), (5, "Moderate"), (7, "High"), (10, "Very high"), (None, "Extreme")]
    assert [label for _, label in TODAY_CONFIG["aqi_categories"]] == [
        "Good", "Moderate", "Unhealthy for sensitive groups", "Unhealthy", "Very unhealthy", "Hazardous"]
    assert [high for high, _ in TODAY_CONFIG["aqi_categories"]] == [50, 100, 150, 200, 300, None]
    assert TODAY_CONFIG["sun_protection_from_uv"] == 3 and TODAY_CONFIG["very_high_from_uv"] == 8
    assert TODAY_CONFIG["advisory_above_aqi"] == 100
    assert (TODAY_CONFIG["cool_at_or_below_c"], TODAY_CONFIG["dry_at_or_below_percent"]) == (15, 35)
    assert (TODAY_CONFIG["hot_at_or_above_c"], TODAY_CONFIG["humid_at_or_above_percent"]) == (30, 60)


@pytest.mark.parametrize("value, expected", [(2.4, 2), (2.5, 3), (0.5, 1), (5.5, 6), (10.49, 10), (6.85, 7), (0, 0)])
def test_whole_number_rounds_half_up(value, expected):
    assert whole_number(value) == expected


def uv_category(weather_api, uv_now, uv_max=None):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=uv_now, uv_max=uv_max)
    weather.clear_cache()
    return get_today_conditions()["uv"]


@pytest.mark.parametrize("uv, label", [
    (0, "Low"), (1, "Low"), (2, "Low"), (2.4, "Low"), (2.5, "Moderate"), (3, "Moderate"), (5, "Moderate"),
    (5.4, "Moderate"), (5.5, "High"), (6, "High"), (7, "High"), (7.4, "High"), (7.5, "Very high"), (8, "Very high"),
    (10, "Very high"), (10.4, "Very high"), (10.5, "Extreme"), (11, "Extreme"), (14, "Extreme"),
])
def test_uv_categories_at_their_boundaries(weather_api, uv, label):
    got = uv_category(weather_api, uv, uv)
    assert got["now_category"] == label and got["max_category"] == label
    assert got["now"] == got["max"] == whole_number(uv)


@pytest.mark.parametrize("aqi, label", [
    (0, "Good"), (50, "Good"), (51, "Moderate"), (100, "Moderate"), (101, "Unhealthy for sensitive groups"),
    (150, "Unhealthy for sensitive groups"), (151, "Unhealthy"), (200, "Unhealthy"), (201, "Very unhealthy"),
    (300, "Very unhealthy"), (301, "Hazardous"), (500, "Hazardous"),
])
def test_aqi_categories_at_their_boundaries(weather_api, aqi, label):
    weather_api.payload["air"] = weather_api.air(us_aqi=aqi, pm2_5=10.0)
    got = get_today_conditions()["aqi"]
    assert got == {"value": aqi, "category": label, "pm2_5": 10.0}


# ---------------------------------------------------------------- hourly UV in the forecast

def test_fetch_forecast_reads_hourly_uv_as_hours_ending_at_each_time(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(hourly={10: 2.5, 11: 4.0, 12: 6.8})
    got = fetch_forecast(*PUNE)
    assert len(got["uv_hourly"]) == 24
    assert got["uv_hourly"][11] == {"time": "2026-11-12T11:00", "uv": 4.0}
    assert got["uv_hourly"][0] == {"time": "2026-11-12T00:00", "uv": 0.0}


def test_hourly_entries_that_are_unusable_are_left_out(weather_api):
    payload = weather_api.forecast(hourly=[0.0] * 24)
    payload["hourly"]["uv_index"][5] = None
    payload["hourly"]["uv_index"][6] = 99
    payload["hourly"]["uv_index"][7] = "3"
    payload["hourly"]["uv_index"][8] = True
    payload["hourly"]["time"][9] = "not a time"
    weather_api.payload["forecast"] = payload
    assert len(fetch_forecast(*PUNE)["uv_hourly"]) == 24 - 5


@pytest.mark.parametrize("hourly", [None, {"time": "x", "uv_index": 5}, {"time": [], "uv_index": []}, ["not", "a", "dict"]])
def test_missing_or_odd_hourly_data_is_just_an_empty_list(weather_api, hourly):
    payload = weather_api.forecast()
    if hourly is not None:
        payload["hourly"] = hourly
    weather_api.payload["forecast"] = payload
    assert fetch_forecast(*PUNE)["uv_hourly"] == []


def test_hourly_uv_alone_counts_as_usable(weather_api):
    payload = weather_api.forecast(uv_now=None, uv_max=None, humidity=None, temperature=None, hourly={12: 5.0})
    weather_api.payload["forecast"] = payload
    got = fetch_forecast(*PUNE)
    assert got["uv_now"] is None and len(got["uv_hourly"]) == 24


# ---------------------------------------------------------------- the UV timeline

def hours(values):
    """{hour_ending: uv} -> the hourly list the service reads (24 entries)."""
    return [{"time": f"2026-11-12T{h:02d}:00", "uv": values.get(h, 0.0)} for h in range(24)]


def test_timeline_joins_hours_at_or_above_3_into_one_range_labelled_by_the_hour_each_value_covers():
    got = uv_timeline(hours({10: 2.5, 11: 4.0, 12: 6.8, 13: 7.2, 14: 4.1, 15: 2.4}))
    assert got["available"] and got["reaches"]
    assert got["ranges"] == [{"from": "09:00", "to": "14:00"}]         # the value at 10:00 covers 09:00-10:00
    assert got["peak"] == {"from": "12:00", "to": "13:00", "uv": 7}     # 7.2 is the highest hour


def test_timeline_can_have_more_than_one_range():
    got = uv_timeline(hours({10: 3, 11: 4, 12: 1, 13: 2, 14: 5, 15: 3}))
    assert got["ranges"] == [{"from": "09:00", "to": "11:00"}, {"from": "13:00", "to": "15:00"}]


def test_timeline_for_a_day_with_no_hour_at_3_or_higher():
    got = uv_timeline(hours({10: 1.0, 11: 2.4, 12: 2.4, 13: 1.0}))
    assert got["available"] is True and got["reaches"] is False and got["ranges"] == []
    assert got["peak"] == {"from": "10:00", "to": "11:00", "uv": 2}      # the first of the two equal highest hours


def test_timeline_for_a_day_of_zeros():
    got = uv_timeline(hours({}))
    assert got["reaches"] is False and got["peak"]["uv"] == 0


@pytest.mark.parametrize("uv, counts", [(2.4, False), (2.5, True), (3, True), (2.99, True), (1.0, False)])
def test_timeline_threshold_uses_the_whole_number_uv(uv, counts):
    assert uv_timeline(hours({12: uv}))["reaches"] is counts


def test_timeline_hour_labels_can_cross_midnight():
    got = uv_timeline([{"time": "2026-11-12T00:00", "uv": 3.0}, {"time": "2026-11-12T01:00", "uv": 3.0}])
    assert got["ranges"] == [{"from": "23:00", "to": "01:00"}]


def test_timeline_without_hourly_data_is_not_available():
    for empty in (None, []):
        assert uv_timeline(empty) == {"available": False, "reaches": False, "ranges": [], "peak": None}


def test_today_conditions_carry_the_timeline(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(hourly={11: 4.0, 12: 6.8, 13: 5.0})
    got = get_today_conditions()["timeline"]
    assert got["ranges"] == [{"from": "10:00", "to": "13:00"}] and got["peak"]["uv"] == 7


def test_no_hourly_data_still_gives_the_rest(weather_api):
    got = get_today_conditions()
    assert got["timeline"]["available"] is False and got["uv"]["max"] == 7 and got["status"] == "ok"


# ---------------------------------------------------------------- extra steps and the sunscreen link

def guidance(weather_api, uv_now, uv_max=None, aqi=42):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=uv_now, uv_max=uv_max)
    weather_api.payload["air"] = weather_api.air(us_aqi=aqi)
    weather.clear_cache()
    return get_today_conditions()["guidance"]


@pytest.mark.parametrize("peak, steps", [
    (0, "none"), (1, "none"), (2, "none"), (2.4, "none"),
    (2.5, "moderate_to_high"), (3, "moderate_to_high"), (5, "moderate_to_high"), (7, "moderate_to_high"),
    (7.4, "moderate_to_high"), (7.5, "very_high"), (8, "very_high"), (10, "very_high"), (11, "very_high"),
])
def test_extra_steps_follow_todays_peak_uv(weather_api, peak, steps):
    assert guidance(weather_api, 0, peak)["extra_steps"] == steps          # UV now does not matter


def test_uv_now_is_used_only_when_there_is_no_peak(weather_api):
    assert guidance(weather_api, 6, None)["extra_steps"] == "moderate_to_high"
    assert guidance(weather_api, 1, None)["extra_steps"] == "none"
    assert guidance(weather_api, 9, 2)["extra_steps"] == "none"            # a peak below now still wins (odd data)


@pytest.mark.parametrize("peak, card", [
    (0, "very_low"), (0.4, "very_low"),                       # rounds to 0: below 1
    (0.5, "low"), (1, "low"), (2, "low"), (2.4, "low"),       # rounds to 1 or 2
    (2.5, "full"), (3, "full"), (7, "full"), (11, "full"),    # rounds to 3 or more
])
def test_the_uv_card_follows_todays_peak_uv(weather_api, peak, card):
    assert guidance(weather_api, 0, peak)["uv_card"] == card          # UV now does not matter


def test_the_uv_card_uses_uv_now_only_when_there_is_no_peak(weather_api):
    assert guidance(weather_api, 6, None)["uv_card"] == "full"
    assert guidance(weather_api, 1, None)["uv_card"] == "low"
    assert guidance(weather_api, 0, None)["uv_card"] == "very_low"
    assert guidance(weather_api, None, None)["uv_card"] is None


def test_no_uv_at_all_gives_no_extra_steps_level(weather_api):
    assert guidance(weather_api, None, None)["extra_steps"] is None


@pytest.mark.parametrize("peak, shown", [(0, False), (2, False), (2.4, False), (2.5, True), (3, True), (11, True)])
def test_the_sunscreen_link_shows_when_todays_peak_reaches_3(weather_api, peak, shown):
    assert guidance(weather_api, 0, peak)["show_sunscreen_link"] is shown


@pytest.mark.parametrize("aqi, check", [(0, False), (50, False), (100, False), (101, True), (301, True)])
def test_health_advisory_line_only_above_moderate(weather_api, aqi, check):
    assert guidance(weather_api, 1, 1, aqi=aqi)["check_advisories"] is check


def test_the_guidance_flags_never_say_anything_is_not_needed(weather_api):
    assert "not_needed" not in str(guidance(weather_api, 0, 1)) and "needed" not in str(guidance(weather_api, 0, 1))


# ---------------------------------------------------------------- weather tip groups

def tips(weather_api, temperature, humidity):
    weather_api.payload["forecast"] = weather_api.forecast(temperature=temperature, humidity=humidity)
    weather.clear_cache()
    return get_today_conditions()["tips"]


@pytest.mark.parametrize("temperature, humidity, groups, headline", [
    (15.0, 50, ["cool_dry"], "cool"),              # at the cool cutoff
    (15.1, 50, [], None),                            # just above
    (20.0, 35, ["cool_dry"], "dry"),               # at the dry cutoff
    (20.0, 35.1, [], None),                          # just above
    (15.0, 35, ["cool_dry"], "cool_dry"),          # both
    (5.0, 20, ["cool_dry"], "cool_dry"),
    (30.0, 60, ["hot_humid"], "hot_humid"),        # at both hot-and-humid cutoffs
    (29.9, 60, [], None),                            # just below hot
    (30.0, 59.9, [], None),                          # just below humid
    (35.0, 90, ["hot_humid"], "hot_humid"),
    (30.0, 35, ["cool_dry"], "dry"),               # hot but dry: the dry tips, not hot and humid
    (22.0, 50, [], None),                            # neither
])
def test_tip_groups_at_the_cutoffs(weather_api, temperature, humidity, groups, headline):
    assert tips(weather_api, temperature, humidity) == {"groups": groups, "headline": headline}


@pytest.mark.parametrize("temperature, humidity, groups, headline", [
    (None, 30, ["cool_dry"], "dry"),               # humidity alone can decide cool-or-dry
    (10.0, None, ["cool_dry"], "cool"),            # so can temperature alone
    (None, 80, [], None),                            # hot-and-humid needs both, so nothing applies
    (35.0, None, [], None),
    (None, None, [], None),
    (None, 50, [], None),
])
def test_a_missing_temperature_or_humidity_never_triggers_a_group_by_itself(weather_api, temperature, humidity, groups, headline):
    assert tips(weather_api, temperature, humidity) == {"groups": groups, "headline": headline}


def test_when_the_weather_is_unavailable_no_tip_group_applies(weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    got = get_today_conditions()
    assert got["tips"] == {"groups": [], "headline": None}
    assert got["guidance"]["uv_card"] is None and got["guidance"]["extra_steps"] is None and got["timeline"]["available"] is False


# ---------------------------------------------------------------- places in get_today_conditions

def test_no_arguments_uses_the_default_place_without_looking_it_up(weather_api):
    got = get_today_conditions()
    assert got["status"] == "ok" and got["place"]["name"] == "Pune" and got["place"]["country"] == "India"
    assert weather_api.count("geocoding") == 0 and weather_api.count("forecast") == 1 and weather_api.count("air") == 1
    assert got["query"] is None and got["choices"] == []


def test_a_blank_city_counts_as_no_city(weather_api):
    assert get_today_conditions(city="   ")["place"]["name"] == "Pune"
    assert weather_api.count("geocoding") == 0


def test_one_match_is_used_directly(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([weather_api.place("Oslo", "Oslo", "Norway", 59.9, 10.7)])
    got = get_today_conditions(city="  Oslo ")
    assert got["status"] == "ok" and got["query"] == "Oslo"
    assert (got["place"]["name"], got["place"]["latitude"]) == ("Oslo", 59.9)
    assert weather_api.calls[0][1]["name"] == "Oslo"                   # the cleaned text went to the service


def test_several_matches_are_offered_to_choose_from(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding(
        [weather_api.place("Springfield", f"State {i}", "United States", 30.0 + i, -90.0) for i in range(5)])
    got = get_today_conditions(city="Springfield")
    assert got["status"] == "choose" and len(got["choices"]) == 5 and got["place"] is None
    assert got["choices"][0] == {"name": "Springfield", "region": "State 0", "country": "United States",
                                 "latitude": 30.0, "longitude": -90.0, "timezone": "Asia/Kolkata"}
    assert weather_api.count("forecast") == 0                          # nothing is fetched until one is picked


def test_no_match(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([])
    got = get_today_conditions(city="zzzzqqqxx")
    assert got["status"] == "no_match" and got["query"] == "zzzzqqqxx" and got["place"] is None
    assert weather_api.count("forecast") == 0


def test_geocoding_failure_is_unavailable_and_never_invents_a_place(weather_api):
    weather_api.error["geocoding"] = requests.Timeout("slow")
    got = get_today_conditions(city="Pune")
    assert got["status"] == "unavailable" and got["place"] is None and got["uv"] is None and got["aqi"] is None


@pytest.mark.parametrize("city", ["http://evil.example", "a/b", "<b>x</b>", "a" * 61, "x", "...", "www.evil.example"])
def test_unusable_city_text_makes_no_request(weather_api, city):
    got = get_today_conditions(city=city)
    assert got["status"] == "invalid" and got["query"] is None and weather_api.calls == []


def test_coordinates_with_a_label_skip_the_lookup(weather_api):
    got = get_today_conditions(latitude="59.9", longitude="10.7", label="Oslo, Norway")
    assert got["status"] == "ok" and got["place"] == {"name": "Oslo, Norway", "region": None, "country": None,
                                                      "latitude": 59.9, "longitude": 10.7}
    assert weather_api.count("geocoding") == 0
    assert weather_api.calls[0][1]["latitude"] == 59.9


def test_a_bad_label_is_replaced_not_echoed(weather_api):
    got = get_today_conditions(latitude="1", longitude="2", label="<script>alert(1)</script>")
    assert got["place"]["name"] == "Selected place"


@pytest.mark.parametrize("lat, lon", [("999", "10"), ("abc", "10"), ("10", None), (None, "10"), ("nan", "nan")])
def test_bad_coordinates_are_invalid_and_make_no_request(weather_api, lat, lon):
    got = get_today_conditions(latitude=lat, longitude=lon)
    assert got["status"] == "invalid" and weather_api.calls == []


# ---------------------------------------------------------------- failures and partial data

def test_both_services_down_is_unavailable_with_no_values(weather_api):
    weather_api.error["forecast"] = requests.ConnectionError("down")
    weather_api.error["air"] = requests.Timeout("slow")
    got = get_today_conditions()
    assert got["status"] == "unavailable" and got["place"]["name"] == "Pune"
    assert got["uv"] is None and got["humidity"] is None and got["temperature_c"] is None and got["aqi"] is None
    assert set(got["missing"]) == {"conditions", "air_quality"}


def test_air_quality_down_still_shows_the_weather(weather_api):
    weather_api.error["air"] = requests.Timeout("slow")
    got = get_today_conditions()
    assert got["status"] == "ok" and got["aqi"] is None and got["missing"] == ["air_quality"]
    assert got["humidity"] == 37.0 and got["uv"]["max"] == 7 and got["temperature_c"] == 26.7


def test_forecast_down_still_shows_the_air_quality(weather_api):
    weather_api.error["forecast"] = requests.Timeout("slow")
    weather_api.payload["air"] = weather_api.air(us_aqi=116, pm2_5=24.6)
    got = get_today_conditions()
    assert got["status"] == "ok" and got["uv"] is None and got["humidity"] is None and got["missing"] == ["conditions"]
    assert got["aqi"]["value"] == 116 and got["local_time"] == "2026-11-12T17:30"
    assert got["guidance"]["extra_steps"] is None


def test_single_missing_values_are_listed_and_the_rest_shown(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(humidity=None, temperature=None, uv_now=None, uv_max=None)
    weather_api.payload["forecast"]["current"]["temperature_2m"] = 20.0
    got = get_today_conditions()
    assert got["temperature_c"] == 20.0 and got["humidity"] is None and got["uv"] is None
    assert set(got["missing"]) == {"uv", "humidity"}


def test_aqi_missing_but_pm25_present_counts_as_missing_air_quality(weather_api):
    weather_api.payload["air"] = weather_api.air(us_aqi=None, pm2_5=12.0)
    got = get_today_conditions()
    assert got["aqi"] is None and "air_quality" in got["missing"]


def test_nothing_is_invented_when_values_are_implausible(weather_api):
    weather_api.payload["forecast"] = weather_api.forecast(uv_now=99, uv_max=99, humidity=500, temperature=900)
    weather_api.payload["air"] = weather_api.air(us_aqi=99999, pm2_5=-5)
    got = get_today_conditions()
    assert got["status"] == "unavailable" and got["uv"] is None and got["aqi"] is None


def test_repeat_calls_use_the_cache_and_a_new_quarter_hour_fetches_again(weather_api, weather_clock):
    get_today_conditions()
    get_today_conditions()
    assert len(weather_api.calls) == 2                                  # one forecast, one air quality
    weather_clock.advance(15 * 60 + 1)
    get_today_conditions()
    assert len(weather_api.calls) == 4


def test_the_result_is_plain_data_with_no_markup_or_formatting(weather_api):
    weather_api.payload["geocoding"] = weather_api.geocoding([weather_api.place("Pune", "Maharashtra", "India", 18.5, 73.8)])
    got = get_today_conditions(city="Pune")

    def walk(value):
        if isinstance(value, dict):
            for v in value.values():
                yield from walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                yield from walk(v)
        else:
            yield value

    assert set(got) == {"status", "query", "place", "choices", "local_time", "uv", "humidity", "temperature_c",
                        "aqi", "timeline", "guidance", "tips", "missing"}
    assert all(v is None or isinstance(v, (bool, int, float, str)) for v in walk(got))
    assert not any(isinstance(v, str) and ("<" in v or "$" in v or "°" in v or "%" in v) for v in walk(got))
    assert all(not isinstance(v, float) or math.isfinite(v) for v in walk(got))
