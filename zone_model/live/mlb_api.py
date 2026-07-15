"""
MLB Stats API client (free, no key required).
Base: https://statsapi.mlb.com/api/v1/

Endpoints used:
  /schedule          - today's games
  /game/{pk}/boxscore - confirmed lineups + umpire assignments
  /people/{id}/stats  - per-player season stats (K%, BB%, wOBA, etc.)
"""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import date, datetime, timezone
from typing import Optional
import time

MLB_BASE = "https://statsapi.mlb.com/api/v1"

# ── simple HTTP helper ────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict:
    """GETs a JSON endpoint from the MLB Stats API with basic retry."""
    url = MLB_BASE + path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + qs
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


# ── schedule ──────────────────────────────────────────────────────────────────

def get_todays_games(game_date: str | None = None) -> list[dict]:
    """
    Returns list of games scheduled for `game_date` (YYYY-MM-DD).
    Defaults to today (ET).

    Each dict has:
      gamePk, status, home_team, away_team, venue_name, game_time_utc
    """
    if game_date is None:
        game_date = date.today().isoformat()

    data = _get("/schedule", {
        "sportId": "1",
        "date": game_date,
        "hydrate": "team,venue,linescore",
    })

    games = []
    for date_entry in data.get("dates", []):
        for g in date_entry.get("games", []):
            status = g.get("status", {}).get("abstractGameState", "Unknown")
            games.append({
                "gamePk":       g["gamePk"],
                "status":       status,
                "home_team":    g["teams"]["home"]["team"]["name"],
                "home_team_id": g["teams"]["home"]["team"]["id"],
                "away_team":    g["teams"]["away"]["team"]["name"],
                "away_team_id": g["teams"]["away"]["team"]["id"],
                "venue_name":   g.get("venue", {}).get("name", "Unknown"),
                "venue_id":     g.get("venue", {}).get("id"),
                "game_time_utc": g.get("gameDate", ""),
            })
    return games


# ── boxscore (lineups + umpires) ──────────────────────────────────────────────

def get_game_detail(game_pk: int) -> dict:
    """
    Returns enriched game detail including:
      - home_starter / away_starter (name, id, throws)
      - home_lineup / away_lineup   (list of player dicts)
      - umpire_name                 (home plate umpire)
    """
    data = _get(f"/game/{game_pk}/boxscore")

    teams = data.get("teams", {})
    officials = data.get("officials", [])

    def extract_starter(side_data: dict) -> dict:
        pitchers = side_data.get("pitchers", [])
        if not pitchers:
            return {"name": "TBD", "id": None, "throws": "R"}
        pid = pitchers[0]
        info = side_data.get("players", {}).get(f"ID{pid}", {})
        person = info.get("person", {})
        pos = info.get("position", {})
        return {
            "name":   person.get("fullName", "TBD"),
            "id":     person.get("id"),
            "throws": info.get("pitchHand", {}).get("code", "R"),
        }

    def extract_lineup(side_data: dict) -> list[dict]:
        batters = side_data.get("batters", [])
        players = side_data.get("players", {})
        lineup = []
        for pid in batters:
            info = players.get(f"ID{pid}", {})
            person = info.get("person", {})
            lineup.append({
                "name": person.get("fullName", ""),
                "id":   person.get("id"),
                "bats": info.get("batSide", {}).get("code", "R"),
                "position": info.get("position", {}).get("abbreviation", ""),
            })
        return lineup

    home = teams.get("home", {})
    away = teams.get("away", {})

    # Home plate umpire
    hp_ump = "Unknown"
    for off in officials:
        if off.get("officialType") == "Home Plate":
            hp_ump = off.get("official", {}).get("fullName", "Unknown")
            break

    return {
        "home_starter": extract_starter(home),
        "away_starter": extract_starter(away),
        "home_lineup":  extract_lineup(home),
        "away_lineup":  extract_lineup(away),
        "umpire_name":  hp_ump,
    }


# ── player season stats ───────────────────────────────────────────────────────

_PLAYER_STAT_CACHE: dict[int, dict] = {}


def get_pitcher_season_stats(player_id: int, season: int | None = None) -> dict:
    """
    Returns pitcher stats for the current (or given) season.
    Keys: era, k_pct, bb_pct, gbpct, ip, hand
    Falls back to league averages if unavailable.
    """
    if player_id in _PLAYER_STAT_CACHE:
        return _PLAYER_STAT_CACHE[player_id]

    season = season or date.today().year
    defaults = {
        "era": 4.20, "k_pct": 0.220, "bb_pct": 0.080,
        "gbpct": 0.440, "ip": 0.0, "hand": "R",
    }
    try:
        data = _get(f"/people/{player_id}/stats", {
            "stats":  "season",
            "group":  "pitching",
            "season": str(season),
        })
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return defaults
        s = splits[0].get("stat", {})
        pa  = s.get("battersFaced", 1) or 1
        so  = s.get("strikeOuts", 0)
        bb  = s.get("baseOnBalls", 0)
        gb  = s.get("groundOuts", 0)
        fb  = s.get("flyOuts", 0) + s.get("airOuts", 0)
        total_batted = (gb + fb) or 1
        result = {
            "era":    float(s.get("era", 4.20) or 4.20),
            "k_pct":  round(so / pa, 3),
            "bb_pct": round(bb / pa, 3),
            "gbpct":  round(gb / total_batted, 3),
            "ip":     float(s.get("inningsPitched", 0) or 0),
            "hand":   "R",  # populated separately from people endpoint
        }
        _PLAYER_STAT_CACHE[player_id] = result
        return result
    except Exception:
        return defaults


def get_lineup_woba(lineup: list[dict], pitcher_hand: str) -> float:
    """
    Computes average wOBA for a lineup vs. the given pitcher hand.
    Uses the MLB Stats API hitting splits when available.
    Returns league average (0.320) on failure.
    """
    if not lineup:
        return 0.320

    total_woba = 0.0
    count = 0
    for player in lineup[:9]:   # top 9 batters only
        pid = player.get("id")
        if not pid:
            continue
        try:
            split_group = "vsLeft" if pitcher_hand == "L" else "vsRight"
            data = _get(f"/people/{pid}/stats", {
                "stats":  "season",
                "group":  "hitting",
                "season": str(date.today().year),
            })
            splits = data.get("stats", [{}])[0].get("splits", [])
            # Find the relevant vs-hand split
            woba_found = False
            for sp in splits:
                if sp.get("split", {}).get("code", "") == split_group[:1].upper():
                    s = sp.get("stat", {})
                    woba_str = s.get("obp", "0.320")   # MLB API gives OBP; wOBA approximated
                    total_woba += float(woba_str or 0.320)
                    count += 1
                    woba_found = True
                    break
            if not woba_found:
                # Fallback: use overall OBP as wOBA proxy
                for sp in splits[:1]:
                    s = sp.get("stat", {})
                    total_woba += float(s.get("obp", "0.320") or 0.320)
                    count += 1
        except Exception:
            total_woba += 0.320
            count += 1

    return round(total_woba / count, 3) if count else 0.320
