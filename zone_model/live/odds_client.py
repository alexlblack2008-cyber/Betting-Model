"""
The Odds API client — live MLB over/under market totals.
https://the-odds-api.com  (free tier: 500 requests/month)

API key is read from the ODDS_API_KEY environment variable.
Set it once in the CCR environment or in a local .env file.

Endpoint used:
  GET /v4/sports/baseball_mlb/odds
  ?regions=us&markets=totals&oddsFormat=american&bookmakers=draftkings,fanduel,betmgm

We aggregate the best available total across three major books and use
the consensus closing number as market_total fed into the Zone Model.
"""

from __future__ import annotations
import json
import os
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timezone
from typing import Optional
import time

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
SPORT_KEY     = "baseball_mlb"
BOOKMAKERS    = "draftkings,fanduel,betmgm,williamhill_us,bovada"
REGIONS       = "us"
MARKETS       = "totals"
ODDS_FORMAT   = "american"


def _api_key() -> str:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "ODDS_API_KEY environment variable is not set.\n"
            "Sign up free at https://the-odds-api.com and set the key:\n"
            "  export ODDS_API_KEY=your_key_here\n"
            "Or add it to zone_model/.env and it will be loaded automatically."
        )
    return key


def _get(path: str, params: dict) -> dict | list:
    params["apiKey"] = _api_key()
    qs  = urllib.parse.urlencode(params)
    url = f"{ODDS_API_BASE}{path}?{qs}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                remaining = resp.headers.get("x-requests-remaining", "?")
                used      = resp.headers.get("x-requests-used", "?")
                data      = json.loads(resp.read())
                # Attach quota info for monitoring
                if isinstance(data, list):
                    return {"events": data, "_quota": {"remaining": remaining, "used": used}}
                data["_quota"] = {"remaining": remaining, "used": used}
                return data
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise EnvironmentError("ODDS_API_KEY is invalid or expired.") from e
            if e.code == 429:
                raise RuntimeError("Odds API monthly quota exceeded (500 req/month on free tier).") from e
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


# ── Main fetch ────────────────────────────────────────────────────────────────

def get_mlb_totals(game_date: str | None = None) -> dict[str, float]:
    """
    Fetches today's MLB game totals from The Odds API.

    Returns a dict keyed by a matchup string:
      "Home Team|Away Team" → consensus over/under total (float)

    Example:
      {"New York Yankees|Houston Astros": 8.5,
       "Los Angeles Dodgers|San Francisco Giants": 7.5}

    game_date: YYYY-MM-DD — used to filter by commence_time.
                            Defaults to today.
    """
    target_date = game_date or date.today().isoformat()

    result = _get(f"/sports/{SPORT_KEY}/odds", {
        "regions":    REGIONS,
        "markets":    MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": BOOKMAKERS,
        "dateFormat": "iso",
    })

    events = result.get("events") if isinstance(result, dict) else result
    if not events and isinstance(result, dict):
        events = result.get("events", [])

    quota = result.get("_quota", {}) if isinstance(result, dict) else {}

    totals: dict[str, float] = {}

    for event in events:
        # Filter to target date
        commence = event.get("commence_time", "")
        if target_date not in commence:
            continue

        home = event.get("home_team", "")
        away = event.get("away_team", "")
        key  = f"{home}|{away}"

        # Collect all total lines from all bookmakers
        lines: list[float] = []
        for bm in event.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") != "totals":
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == "Over":
                        point = outcome.get("point")
                        if point is not None:
                            lines.append(float(point))

        if lines:
            # Consensus = median to avoid outlier books
            lines.sort()
            mid = len(lines) // 2
            consensus = lines[mid] if len(lines) % 2 else (lines[mid-1] + lines[mid]) / 2
            totals[key] = consensus

    if quota:
        print(f"  [Odds API] Requests used: {quota.get('used')} / "
              f"remaining: {quota.get('remaining')}")

    return totals


def match_total(
    home_team: str,
    away_team: str,
    totals_cache: dict[str, float],
    fallback: float = 8.5,
) -> float:
    """
    Looks up the market total for a given matchup from a pre-fetched cache.

    Uses flexible name matching because the Odds API team names can differ
    slightly from the MLB Stats API names (e.g. "NY Yankees" vs "New York Yankees").
    """
    # Exact match first
    key = f"{home_team}|{away_team}"
    if key in totals_cache:
        return totals_cache[key]

    # Fuzzy: try partial name overlap
    home_words = set(home_team.lower().split())
    away_words = set(away_team.lower().split())
    best_score = 0
    best_val   = fallback

    for k, v in totals_cache.items():
        k_home, _, k_away = k.partition("|")
        kh_words = set(k_home.lower().split())
        ka_words = set(k_away.lower().split())
        score = len(home_words & kh_words) + len(away_words & ka_words)
        if score > best_score:
            best_score = score
            best_val   = v

    if best_score >= 2:
        return best_val

    return fallback


# ── .env loader (optional convenience) ───────────────────────────────────────

def load_dotenv(path: str | None = None) -> None:
    """
    Loads KEY=VALUE pairs from zone_model/.env into os.environ.
    Call this at the top of any script that needs the API key locally.
    """
    import pathlib
    dotenv_path = pathlib.Path(path or __file__).parent.parent / ".env"
    if not dotenv_path.exists():
        return
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
