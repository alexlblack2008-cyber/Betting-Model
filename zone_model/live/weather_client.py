"""
Weather client using Open-Meteo API (free, no key required).
https://open-meteo.com/

Fetches current conditions at each stadium and computes:
  - wind_out_factor : +1.0 = full wind blowing out to CF (runs increase)
                      -1.0 = full wind blowing in from CF (runs decrease)
  - temp_factor     : run adjustment for temperature vs. 72°F baseline
  - weather_run_adj : total run adjustment to apply to fair total

Stadium orientations (degrees from true north that "out to center" points):
  Derived from ballpark orientation databases and satellite imagery.
  "out_bearing" = compass bearing a ball travels when hit to dead center field.
"""

from __future__ import annotations
import json
import math
import urllib.request
import urllib.error
from typing import Optional


# ── Stadium database ──────────────────────────────────────────────────────────
# lat, lon, out_bearing (degrees, 0=N, 90=E, 180=S, 270=W), has_roof
STADIUMS: dict[str, dict] = {
    # American League
    "Yankee Stadium":           {"lat": 40.8296, "lon": -73.9262, "out_bearing": 315, "roof": False},
    "Fenway Park":              {"lat": 42.3467, "lon": -71.0972, "out_bearing": 95,  "roof": False},
    "Camden Yards":             {"lat": 39.2838, "lon": -76.6217, "out_bearing": 350, "roof": False},
    "Tropicana Field":          {"lat": 27.7683, "lon": -82.6534, "out_bearing": 0,   "roof": True},
    "Rogers Centre":            {"lat": 43.6414, "lon": -79.3894, "out_bearing": 355, "roof": True},
    "Guaranteed Rate Field":    {"lat": 41.8300, "lon": -87.6339, "out_bearing": 5,   "roof": False},
    "Progressive Field":        {"lat": 41.4962, "lon": -81.6852, "out_bearing": 356, "roof": False},
    "Comerica Park":            {"lat": 42.3390, "lon": -83.0485, "out_bearing": 350, "roof": False},
    "Kauffman Stadium":         {"lat": 39.0516, "lon": -94.4803, "out_bearing": 350, "roof": False},
    "Target Field":             {"lat": 44.9817, "lon": -93.2781, "out_bearing": 340, "roof": False},
    "Minute Maid Park":         {"lat": 29.7573, "lon": -95.3555, "out_bearing": 340, "roof": True},
    "Globe Life Field":         {"lat": 32.7473, "lon": -97.0825, "out_bearing": 330, "roof": True},
    "T-Mobile Park":            {"lat": 47.5914, "lon": -122.3325,"out_bearing": 345, "roof": True},
    "Oakland Coliseum":         {"lat": 37.7516, "lon": -122.2005,"out_bearing": 60,  "roof": False},
    "Angel Stadium":            {"lat": 33.8003, "lon": -117.8827,"out_bearing": 335, "roof": False},
    # National League
    "Dodger Stadium":           {"lat": 34.0739, "lon": -118.2400,"out_bearing": 330, "roof": False},
    "Oracle Park":              {"lat": 37.7786, "lon": -122.3893,"out_bearing": 95,  "roof": False},
    "Petco Park":               {"lat": 32.7076, "lon": -117.1570,"out_bearing": 305, "roof": False},
    "Chase Field":              {"lat": 33.4453, "lon": -112.0667,"out_bearing": 340, "roof": True},
    "Coors Field":              {"lat": 39.7559, "lon": -104.9942,"out_bearing": 347, "roof": False},
    "American Family Field":    {"lat": 43.0280, "lon": -87.9712, "out_bearing": 5,   "roof": True},
    "Wrigley Field":            {"lat": 41.9484, "lon": -87.6553, "out_bearing": 355, "roof": False},
    "Busch Stadium":            {"lat": 38.6226, "lon": -90.1928, "out_bearing": 5,   "roof": False},
    "Great American Ball Park": {"lat": 39.0978, "lon": -84.5082, "out_bearing": 345, "roof": False},
    "PNC Park":                 {"lat": 40.4469, "lon": -80.0057, "out_bearing": 330, "roof": False},
    "Citizens Bank Park":       {"lat": 39.9061, "lon": -75.1665, "out_bearing": 345, "roof": False},
    "Truist Park":              {"lat": 33.8908, "lon": -84.4678, "out_bearing": 30,  "roof": False},
    "loanDepot park":           {"lat": 25.7781, "lon": -80.2197, "out_bearing": 5,   "roof": True},
    "Citi Field":               {"lat": 40.7571, "lon": -73.8458, "out_bearing": 355, "roof": False},
    "Nationals Park":           {"lat": 38.8730, "lon": -77.0074, "out_bearing": 350, "roof": False},
}

# Temperature baseline and run-per-degree effect
TEMP_BASELINE_F   = 72.0
RUNS_PER_10DEG_F  = 0.12   # each 10°F above baseline adds ~0.12 runs (ball carries further)

# Wind effect: max impact when wind blows directly out or in
MAX_WIND_RUN_ADJ  = 0.80   # full gale directly out = +0.8 runs to expected total


def _get_weather(lat: float, lon: float) -> dict:
    """Calls Open-Meteo current weather endpoint."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,wind_speed_10m,wind_direction_10m,relative_humidity_2m"
        f"&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        cur = data.get("current", {})
        return {
            "temp_f":       float(cur.get("temperature_2m", 72)),
            "wind_mph":     float(cur.get("wind_speed_10m", 0)),
            "wind_dir_deg": float(cur.get("wind_direction_10m", 0)),
            "humidity":     float(cur.get("relative_humidity_2m", 50)),
        }
    except Exception:
        return {"temp_f": 72.0, "wind_mph": 0.0, "wind_dir_deg": 0.0, "humidity": 50.0}


def _wind_out_factor(wind_dir_deg: float, stadium_out_bearing: float) -> float:
    """
    Returns a value in [-1, +1] representing how much the wind is blowing
    toward center field (positive = out to CF, negative = in from CF).

    Uses the cosine of the angle between wind direction and the CF bearing.
    Wind direction convention: direction wind is COMING FROM (meteorological).
    We convert to the direction it blows TOWARD.
    """
    # Wind blows TOWARD = wind_dir_deg + 180
    wind_toward = (wind_dir_deg + 180) % 360
    angle_diff  = abs(wind_toward - stadium_out_bearing) % 360
    if angle_diff > 180:
        angle_diff = 360 - angle_diff
    # cos(0°) = 1.0 (straight out), cos(90°) = 0 (crosswind), cos(180°) = -1 (straight in)
    return math.cos(math.radians(angle_diff))


def get_weather_adjustment(venue_name: str) -> dict:
    """
    Main entry point. Returns a dict with:
      weather_run_adj  - total run adjustment to add to fair total
      temp_f, wind_mph, wind_dir_deg, wind_out_factor, humidity
      is_indoor        - True if retractable roof is closed (no weather effect)
      note             - human-readable description
    """
    stadium = STADIUMS.get(venue_name)
    if stadium is None:
        # Try fuzzy match on partial name
        for k in STADIUMS:
            if k.lower() in venue_name.lower() or venue_name.lower() in k.lower():
                stadium = STADIUMS[k]
                break

    if stadium is None:
        return {
            "weather_run_adj": 0.0, "temp_f": 72.0, "wind_mph": 0.0,
            "wind_dir_deg": 0.0, "wind_out_factor": 0.0, "humidity": 50.0,
            "is_indoor": False,
            "note": f"Stadium '{venue_name}' not in database — no weather adjustment",
        }

    if stadium["roof"]:
        return {
            "weather_run_adj": 0.0, "temp_f": 72.0, "wind_mph": 0.0,
            "wind_dir_deg": 0.0, "wind_out_factor": 0.0, "humidity": 50.0,
            "is_indoor": True,
            "note": "Retractable roof stadium — weather adjustment skipped",
        }

    wx = _get_weather(stadium["lat"], stadium["lon"])
    temp_f       = wx["temp_f"]
    wind_mph     = wx["wind_mph"]
    wind_dir_deg = wx["wind_dir_deg"]
    humidity     = wx["humidity"]

    # Temperature adjustment
    temp_adj = ((temp_f - TEMP_BASELINE_F) / 10.0) * RUNS_PER_10DEG_F

    # Wind adjustment: scaled by (wind_mph / 15) then clipped
    wind_factor = _wind_out_factor(wind_dir_deg, stadium["out_bearing"])
    wind_speed_scaled = min(wind_mph / 15.0, 2.0)
    wind_adj = wind_factor * wind_speed_scaled * MAX_WIND_RUN_ADJ
    wind_adj = max(min(wind_adj, MAX_WIND_RUN_ADJ), -MAX_WIND_RUN_ADJ)

    # Humidity: thin air (low humidity + high altitude) carries ball further
    # Coors is handled by temp/altitude proxy; here just a minor tweak
    humidity_adj = (50.0 - humidity) / 100.0 * 0.05

    total_adj = round(temp_adj + wind_adj + humidity_adj, 3)

    direction_label = "out to CF" if wind_factor > 0.3 else \
                      "in from CF" if wind_factor < -0.3 else "crosswind"
    note = (
        f"{temp_f:.0f}°F, wind {wind_mph:.0f}mph {direction_label} "
        f"(factor {wind_factor:+.2f})"
    )

    return {
        "weather_run_adj": total_adj,
        "temp_f":          temp_f,
        "wind_mph":        wind_mph,
        "wind_dir_deg":    wind_dir_deg,
        "wind_out_factor": round(wind_factor, 3),
        "humidity":        humidity,
        "is_indoor":       False,
        "note":            note,
    }
