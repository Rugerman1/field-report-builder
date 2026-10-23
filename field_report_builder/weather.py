"""Weather for the report date from Open-Meteo (free, no key).

Recent days come from the forecast API (it keeps about three months of past
data); older days from the historical archive.  `parse_weather` is pure so
the tests can feed it a saved response.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
from collections import Counter

from .model import Weather

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# WMO weather interpretation codes, as Open-Meteo documents them.
WMO = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Heavy rain showers", 85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorms", 96: "Thunderstorms with hail", 99: "Thunderstorms with hail",
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}


class WeatherError(RuntimeError):
    pass


def _get(url: str, params: dict, timeout: float = 20.0) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"user-agent": "FieldReportBuilder"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except (OSError, ValueError) as e:
        raise WeatherError(f"Weather lookup failed: {e}") from e


def request_params(lat: float, lon: float, day: dt.date) -> tuple[str, dict]:
    url = FORECAST_URL if (dt.date.today() - day).days <= 80 else ARCHIVE_URL
    return url, {
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}",
        "start_date": day.isoformat(), "end_date": day.isoformat(),
        "hourly": "temperature_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "timezone": "auto",
    }


def _worst(codes: list[int]) -> str:
    """The day-part's description: precipitation wins over sky cover, else the most common sky."""
    codes = [c for c in codes if c is not None]
    if not codes:
        return ""
    wet = [c for c in codes if c >= 45]
    if wet:
        return WMO.get(max(wet), f"Code {max(wet)}")
    return WMO.get(Counter(codes).most_common(1)[0][0], "")


def parse_weather(data: dict) -> Weather:
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        raise WeatherError("No weather data for that date and place")
    temps = hourly.get("temperature_2m") or []
    codes = hourly.get("weather_code") or []
    by_hour = {int(t[11:13]): i for i, t in enumerate(times)}

    def temp_at(h):
        i = by_hour.get(h)
        return round(temps[i], 0) if i is not None and i < len(temps) and temps[i] is not None else None

    am = [codes[by_hour[h]] for h in range(7, 12) if h in by_hour and by_hour[h] < len(codes)]
    pm = [codes[by_hour[h]] for h in range(12, 18) if h in by_hour and by_hour[h] < len(codes)]
    daily = data.get("daily") or {}

    def first(key):
        v = daily.get(key) or [None]
        return v[0]

    return Weather(
        conditions_am=_worst(am), conditions_pm=_worst(pm),
        temp_high_f=first("temperature_2m_max"), temp_low_f=first("temperature_2m_min"),
        temp_7am_f=temp_at(7), temp_noon_f=temp_at(12), temp_4pm_f=temp_at(16),
        precip_in=first("precipitation_sum"), wind_max_mph=first("wind_speed_10m_max"),
        source="Open-Meteo",
    )


def fetch_weather(lat: float, lon: float, day: dt.date) -> Weather:
    url, params = request_params(lat, lon, day)
    data = _get(url, params)
    if data.get("error"):
        raise WeatherError(str(data.get("reason", "Open-Meteo returned an error")))
    return parse_weather(data)


def geocode_params(place: str) -> tuple[str, str | None]:
    """'Clemson, SC' -> ('Clemson', 'South Carolina').  Open-Meteo matches the name only."""
    name, _, region = place.partition(",")
    region = region.strip()
    if region.upper() in US_STATES:
        region = US_STATES[region.upper()]
    return name.strip(), region or None


def pick_place(data: dict, region: str | None) -> tuple[float, float, str]:
    results = data.get("results") or []
    if region:
        matching = [r for r in results if (r.get("admin1") or "").lower() == region.lower()
                    or (r.get("country") or "").lower() == region.lower()]
        results = matching or results
    if not results:
        raise WeatherError("Place not found")
    r = results[0]
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country_code")) if x)
    return r["latitude"], r["longitude"], label


def geocode(place: str) -> tuple[float, float, str]:
    name, region = geocode_params(place)
    if not name:
        raise WeatherError("Type a town or city name")
    data = _get(GEOCODE_URL, {"name": name, "count": 10, "language": "en", "format": "json"})
    return pick_place(data, region)
