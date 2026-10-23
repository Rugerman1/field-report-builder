import datetime as dt
import json
import os

import pytest

from conftest import FIXTURES, LIVE
from field_report_builder import weather


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def test_parse_day():
    w = weather.parse_weather(_load("open_meteo_day.json"))
    assert (w.temp_high_f, w.temp_low_f) == (76.3, 45.9)
    assert (w.temp_7am_f, w.temp_noon_f, w.temp_4pm_f) == (55, 71, 76)
    assert w.conditions_am == "Clear"  # 7 to 11 AM: three clear hours, two mostly clear
    assert w.conditions_pm == "Rain"  # the 5 PM rain beats the cloudy hours
    assert w.precip_in == 0.1 and w.wind_max_mph == 11.2
    assert "high 76 F, low 46 F" in w.summary()


def test_empty_response_raises():
    with pytest.raises(weather.WeatherError):
        weather.parse_weather({"hourly": {"time": []}})


def test_recent_dates_use_forecast_api_old_dates_use_archive():
    today = dt.date.today()
    assert weather.request_params(34.7, -82.8, today - dt.timedelta(days=3))[0] == weather.FORECAST_URL
    url, params = weather.request_params(34.7, -82.8, dt.date(2024, 7, 4))
    assert url == weather.ARCHIVE_URL
    assert params["start_date"] == params["end_date"] == "2024-07-04"
    assert params["temperature_unit"] == "fahrenheit"


def test_geocode_picks_the_right_state():
    assert weather.geocode_params("Clemson, SC") == ("Clemson", "South Carolina")
    lat, lon, label = weather.pick_place(_load("geocode_clemson.json"), "South Carolina")
    assert (round(lat, 2), round(lon, 2)) == (34.68, -82.84)
    assert label == "Clemson, South Carolina, US"
    assert weather.pick_place(_load("geocode_clemson.json"), "North Carolina")[0] == 34.5


@pytest.mark.skipif(not LIVE, reason="set FRB_LIVE=1 to call Open-Meteo")
def test_live_weather_and_geocode():
    lat, lon, _ = weather.geocode("Clemson, SC")
    assert abs(lat - 34.68) < 0.1
    w = weather.fetch_weather(lat, lon, dt.date(2025, 7, 15))  # archive
    assert w.temp_high_f is not None and 70 < w.temp_high_f < 110
    recent = weather.fetch_weather(lat, lon, dt.date.today() - dt.timedelta(days=2))  # forecast API
    assert recent.temp_low_f is not None
