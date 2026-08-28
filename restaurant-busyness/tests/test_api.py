"""Tests for the busyness API.

These run entirely against the simulated provider — no BestTime key and
no network access required. BestTime response parsing is covered by
feeding recorded-shape payloads through the client's parsers.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import besttime  # noqa: E402
import geocoding  # noqa: E402
import simulated  # noqa: E402
from busyness import CheckinLevel, blend, checkins, score_to_level  # noqa: E402
from cache import TTLCache  # noqa: E402
from main import _is_category_only, _split_query, app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_checkins():
    checkins.clear()
    yield
    checkins.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


SIM_VENUE_ID = next(iter(simulated.DEMO_VENUES))


# -- meta -------------------------------------------------------------

def test_health_reports_simulated_source(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["data_source"] == "simulated"


def test_health_never_leaks_the_api_key(client):
    assert "pri_" not in client.get("/health").text


def test_home_serves_the_web_app(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Busy" in res.text


def test_api_index_lists_endpoints(client):
    body = client.get("/api").json()
    assert any("/v1/busy-now" in e for e in body["endpoints"])


# -- search -----------------------------------------------------------

def test_search_returns_venues_with_busyness(client):
    body = client.get("/v1/venues/search?q=coffee&lat=51.5074&lng=-0.1278").json()
    assert body["source"] == "simulated"
    assert body["count"] > 0
    first = body["results"][0]
    assert 0 <= first["busyness"]["busyness_score"] <= 100
    assert first["busyness"]["level"] in {"not_busy", "moderate", "busy", "very_busy"}


@pytest.mark.parametrize("query,expected_type", [
    ("coffee", "CAFE"),
    ("brunch", "CAFE"),
    ("sushi", "RESTAURANT"),
    ("dinner", "RESTAURANT"),
    ("drinks", "BAR"),
    ("pub", "BAR"),
])
def test_everyday_search_words_map_to_categories(client, query, expected_type):
    body = client.get(f"/v1/venues/search?q={query}&lat=51.5074&lng=-0.1278&radius=50000").json()
    assert body["count"] > 0, f"'{query}' returned nothing"
    assert any(v["venue_type"] == expected_type for v in body["results"])


def test_search_matches_venue_by_name(client):
    body = client.get("/v1/venues/search?q=Copper&lat=51.5074&lng=-0.1278&radius=50000").json()
    assert any("Copper" in v["name"] for v in body["results"])


def test_search_computes_distance_when_given_coordinates(client):
    body = client.get("/v1/venues/search?q=&lat=51.5074&lng=-0.1278").json()
    assert all(v["distance_km"] is not None for v in body["results"])


def test_search_radius_excludes_distant_venues(client):
    near = client.get("/v1/venues/search?q=&lat=51.5074&lng=-0.1278&radius=500").json()
    far = client.get("/v1/venues/search?q=&lat=51.5074&lng=-0.1278&radius=50000").json()
    assert near["count"] < far["count"]


# -- unified search (the main entry point) ----------------------------

def test_search_by_exact_venue_name(client):
    body = client.get("/v1/search?q=The Copper Kettle").json()
    assert body["interpretation"]["mode"] == "venue"
    assert body["results"][0]["name"] == "The Copper Kettle"


def test_search_by_partial_venue_name(client):
    body = client.get("/v1/search?q=copper kettle").json()
    assert body["results"][0]["name"] == "The Copper Kettle"


def test_search_tolerates_typos(client):
    body = client.get("/v1/search?q=coper kettel").json()
    assert body["count"] > 0
    assert body["results"][0]["name"] == "The Copper Kettle"


def test_search_by_city_lists_that_citys_venues(client):
    body = client.get("/v1/search?q=Manchester").json()
    assert body["interpretation"]["mode"] == "area"
    assert body["interpretation"]["place"] == "Manchester, UK"
    assert body["count"] > 1
    assert all("Manchester" in v["address"] for v in body["results"])


def test_search_category_in_a_place(client):
    body = client.get("/v1/search?q=coffee in Leeds").json()
    assert body["interpretation"]["place"] == "Leeds, UK"
    assert body["count"] > 0
    assert all("Leeds" in v["address"] for v in body["results"])


def test_search_every_result_carries_busyness(client):
    for query in ["Manchester", "coffee in Leeds", "The Copper Kettle"]:
        for venue in client.get(f"/v1/search?q={query}").json()["results"]:
            score = venue["busyness"]["busyness_score"]
            assert score is not None and 0 <= score <= 100
            assert venue["busyness"]["level"] in {
                "not_busy", "moderate", "busy", "very_busy"}


def test_search_accepts_raw_coordinates_as_a_place(client):
    body = client.get("/v1/search?q=coffee&near=51.5074,-0.1278").json()
    assert body["count"] > 0


def test_search_unknown_place_returns_404(client):
    res = client.get("/v1/search?q=coffee in Zzzyxqville")
    assert res.status_code == 404


def test_search_unknown_name_returns_empty_not_an_error(client):
    body = client.get("/v1/search?q=zzzz nothing here").json()
    assert body["count"] == 0
    assert body["results"] == []


def test_search_requires_a_query(client):
    assert client.get("/v1/search?q=").status_code == 422


def test_name_search_without_a_place_searches_everywhere(client):
    # "Royal Mile Roasters" is in Edinburgh; no city given.
    body = client.get("/v1/search?q=Royal Mile Roasters").json()
    assert body["count"] > 0
    assert body["results"][0]["name"] == "Royal Mile Roasters"


@pytest.mark.parametrize("query,term,place", [
    ("coffee in Leeds", "coffee", "Leeds"),
    ("sushi near Manchester", "sushi", "Manchester"),
    ("The Ivy in London", "The Ivy", "London"),
    ("Manchester", "Manchester", None),
    ("The Dog in the Pond in Bristol", "The Dog in the Pond", "Bristol"),
])
def test_query_splitting(query, term, place):
    assert _split_query(query) == (term, place)


@pytest.mark.parametrize("term,expected", [
    ("coffee", True), ("restaurants", True), ("best pizza", True),
    ("The Copper Kettle", False), ("Sakura", False),
])
def test_category_only_detection(term, expected):
    assert _is_category_only(term) is expected


# -- geocoding --------------------------------------------------------

def test_geocode_known_city_needs_no_network():
    result = asyncio.run(geocoding.geocode("Manchester"))
    assert result["source"] == "builtin"
    assert round(result["lat"], 1) == 53.5


def test_geocode_parses_raw_coordinates():
    result = asyncio.run(geocoding.geocode("51.5074, -0.1278"))
    assert result["source"] == "coordinates"
    assert result["lat"] == 51.5074


def test_geocode_is_case_insensitive():
    assert asyncio.run(geocoding.geocode("MANCHESTER"))["name"] == "Manchester, UK"


def test_geocode_rejects_out_of_range_coordinates():
    assert geocoding.parse_coordinates("999, 999") is None
    assert geocoding.parse_coordinates("not coords") is None


def test_geocode_endpoint(client):
    body = client.get("/v1/geocode?q=Edinburgh").json()
    assert body["name"] == "Edinburgh, UK"
    assert client.get("/v1/geocode?q=Zzzyxqville").status_code == 404


# -- name matching ----------------------------------------------------

def test_exact_name_outranks_partial_match():
    venue = simulated.DEMO_VENUES[SIM_VENUE_ID]
    exact = simulated.match_score(venue, venue["name"])
    partial = simulated.match_score(venue, venue["name"].split()[-1])
    assert exact > partial > 0


def test_unrelated_query_scores_zero():
    venue = simulated.DEMO_VENUES[SIM_VENUE_ID]
    assert simulated.match_score(venue, "quantum tractor supplies") == 0.0


# -- venue detail and forecast ---------------------------------------

def test_get_venue(client):
    body = client.get(f"/v1/venues/{SIM_VENUE_ID}").json()
    assert body["venue_id"] == SIM_VENUE_ID
    assert body["busyness"]["busyness_score"] is not None


def test_unknown_venue_returns_404(client):
    res = client.get("/v1/venues/sim_doesnotexist")
    assert res.status_code == 404
    assert res.json()["error"] == "Venue not found"


def test_forecast_returns_seven_days_of_24_hours(client):
    body = client.get(f"/v1/venues/{SIM_VENUE_ID}/forecast").json()
    assert len(body["days"]) == 7
    for day in body["days"]:
        assert len(day["hours"]) == 24
        assert [h["hour"] for h in day["hours"]] == list(range(24))


def test_forecast_can_be_filtered_to_one_day(client):
    body = client.get(f"/v1/venues/{SIM_VENUE_ID}/forecast?day=2").json()
    assert len(body["days"]) == 1
    assert body["days"][0]["day_int"] == 2


def test_forecast_rejects_out_of_range_day(client):
    assert client.get(f"/v1/venues/{SIM_VENUE_ID}/forecast?day=9").status_code == 422


# -- check-ins --------------------------------------------------------

def test_checkin_moves_score_towards_the_reported_level(client):
    before = client.get(f"/v1/venues/{SIM_VENUE_ID}").json()["busyness"]["busyness_score"]
    for _ in range(5):
        client.post(f"/v1/venues/{SIM_VENUE_ID}/checkin", json={"level": "packed"})
    after = client.get(f"/v1/venues/{SIM_VENUE_ID}").json()["busyness"]["busyness_score"]
    assert after > before
    assert "checkins" in client.get(f"/v1/venues/{SIM_VENUE_ID}").json()["busyness"]["source"]


def test_checkin_rejects_invalid_level(client):
    res = client.post(f"/v1/venues/{SIM_VENUE_ID}/checkin", json={"level": "rammed"})
    assert res.status_code == 422


def test_checkins_expire_out_of_the_window():
    now = datetime.now(timezone.utc)
    checkins.add("v1", CheckinLevel.packed, now - timedelta(hours=3))
    assert checkins.recent("v1", now) == []


def test_blend_without_baseline_uses_checkins_alone():
    now = datetime.now(timezone.utc)
    checkins.add("v2", CheckinLevel.packed, now)
    result = blend(None, "v2", now)
    assert result["source"] == "checkins"
    assert result["busyness_score"] > 80


def test_blend_without_any_signal_reports_unavailable():
    result = blend(None, "nobody", datetime.now(timezone.utc))
    assert result["source"] == "unavailable"
    assert result["busyness_score"] is None


def test_newer_checkins_outweigh_older_ones():
    now = datetime.now(timezone.utc)
    checkins.add("v3", CheckinLevel.quiet, now - timedelta(minutes=110))
    checkins.add("v3", CheckinLevel.packed, now)
    # The fresh "packed" report should dominate the nearly-expired "quiet" one.
    assert blend(None, "v3", now)["busyness_score"] > 70


# -- busy-now ---------------------------------------------------------

def test_busy_now_is_sorted_descending(client):
    scores = [v["busyness"]["busyness_score"]
              for v in client.get("/v1/busy-now").json()["results"]]
    assert scores == sorted(scores, reverse=True)


def test_busy_now_respects_min_score(client):
    body = client.get("/v1/busy-now?min_score=60").json()
    assert all(v["busyness"]["busyness_score"] >= 60 for v in body["results"])


def test_busy_now_respects_limit(client):
    assert len(client.get("/v1/busy-now?limit=3").json()["results"]) <= 3


# -- endpoints that require BestTime ---------------------------------

def test_adding_a_venue_requires_besttime(client):
    res = client.post("/v1/venues", json={"venue_name": "X", "venue_address": "Y"})
    assert res.status_code == 400


def test_search_progress_requires_besttime(client):
    assert client.get("/v1/venues/search/progress?job_id=abc").status_code == 400


# -- simulated engine -------------------------------------------------

def test_curves_are_deterministic_per_venue_per_day():
    venue = simulated.DEMO_VENUES[SIM_VENUE_ID]
    day = datetime(2026, 3, 14).date()
    assert simulated.day_curve(venue, day) == simulated.day_curve(venue, day)


def test_curves_stay_in_range():
    for venue in simulated.DEMO_VENUES.values():
        curve = simulated.day_curve(venue, datetime(2026, 3, 14).date())
        assert len(curve) == 24
        assert all(0 <= v <= 100 for v in curve)


def test_bars_peak_at_night_and_cafes_in_the_morning():
    monday = datetime(2026, 3, 16).date()  # a weekday
    bar = next(v for v in simulated.DEMO_VENUES.values() if v["venue_type"] == "BAR")
    cafe = next(v for v in simulated.DEMO_VENUES.values() if v["venue_type"] == "CAFE")
    bar_curve = simulated.day_curve(bar, monday)
    cafe_curve = simulated.day_curve(cafe, monday)
    assert bar_curve.index(max(bar_curve)) >= 18
    assert 6 <= cafe_curve.index(max(cafe_curve)) <= 14


def test_score_to_level_boundaries():
    assert score_to_level(0) == "not_busy"
    assert score_to_level(25) == "not_busy"
    assert score_to_level(26) == "moderate"
    assert score_to_level(50) == "moderate"
    assert score_to_level(51) == "busy"
    assert score_to_level(75) == "busy"
    assert score_to_level(76) == "very_busy"
    assert score_to_level(100) == "very_busy"


# -- BestTime response parsing ---------------------------------------

def test_parse_live_reads_documented_fields():
    parsed = besttime.parse_live({
        "analysis": {
            "venue_live_busyness": 82,
            "venue_forecasted_busyness": 60,
            "venue_live_busyness_available": True,
            "venue_forecast_busyness_available": True,
            "venue_live_forecasted_delta": 22,
        },
        "venue_info": {"venue_id": "ven_1", "venue_name": "Cafe",
                       "venue_timezone": "Europe/London"},
        "status": "OK",
    })
    assert parsed["live_busyness"] == 82
    assert parsed["forecasted_busyness"] == 60
    assert parsed["live_available"] is True
    assert parsed["venue_id"] == "ven_1"


def test_parse_live_survives_missing_analysis():
    parsed = besttime.parse_live({"status": "OK"})
    assert parsed["live_busyness"] is None
    assert parsed["live_available"] is False


def test_parse_live_clamps_out_of_range_scores():
    parsed = besttime.parse_live({"analysis": {"venue_live_busyness": 150}})
    assert parsed["live_busyness"] == 100


def test_parse_forecast_builds_a_week():
    parsed = besttime.parse_forecast({
        "venue_info": {"venue_id": "ven_2", "venue_name": "Bar",
                       "venue_lat": 51.5, "venue_lng": -0.1},
        "analysis": [
            {"day_info": {"day_int": i, "day_text": "Monday",
                          "venue_open": 9, "venue_closed": 23},
             "day_raw": list(range(24))}
            for i in range(7)
        ],
    })
    assert parsed["venue"]["venue_id"] == "ven_2"
    assert parsed["venue"]["lat"] == 51.5
    assert len(parsed["week"]) == 7
    assert len(parsed["week"][0]["hourly_busyness"]) == 24


def test_parse_venue_handles_flat_and_nested_shapes():
    nested = besttime.parse_venue({"venue_info": {"venue_id": "a", "venue_name": "N"}})
    flat = besttime.parse_venue({"venue_id": "a", "venue_name": "N"})
    assert nested["venue_id"] == flat["venue_id"] == "a"
    assert nested["name"] == flat["name"] == "N"


def test_venue_list_accepts_alternate_container_keys():
    assert len(besttime._venue_list({"venues": [{"venue_id": "1"}]})) == 1
    assert len(besttime._venue_list({"results": [{"venue_id": "1"}]})) == 1
    assert besttime._venue_list({"nothing": 1}) == []


# -- cache ------------------------------------------------------------

def test_cache_returns_value_then_expires():
    cache = TTLCache()
    cache.set("k", {"v": 1}, ttl=60)
    assert cache.get("k") == {"v": 1}
    cache.set("k2", {"v": 2}, ttl=0)
    assert cache.get("k2") is None


def test_cache_evicts_when_full():
    cache = TTLCache(max_entries=3)
    for i in range(5):
        cache.set(f"k{i}", i, ttl=60)
    assert cache.stats()["entries"] <= 3
