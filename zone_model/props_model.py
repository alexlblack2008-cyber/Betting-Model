"""
Player Props Model
==================
Identifies edges on niche player prop markets across MLB, NFL, and NBA.

MLB Props:
  - Pitcher strikeouts (K line)
  - Batter hits
  - Batter total bases
  - Pitcher outs recorded

NFL Props:
  - QB passing yards / attempts / TDs
  - RB rushing yards / attempts
  - WR/TE receiving yards / receptions

NBA Props:
  - Points
  - Rebounds
  - Assists
  - Blocks / steals
  - Points + rebounds + assists (PRA)

Methodology:
  1. Fetch player's last 10 game log from ESPN
  2. Compute rolling average and standard deviation
  3. Compare to market line (from The Odds API props endpoint)
  4. Edge = (avg - line) / std_dev → z-score based conviction
  5. Filter: |z| >= 0.5 AND line is accessible (not a juice trap)
  6. Adjust for matchup: opponent's allowed stat rate vs position average

Output: list of PropPick objects with rationale
"""
from __future__ import annotations
import json
import math
import urllib.request
import urllib.error
import urllib.parse
import time
from dataclasses import dataclass, field
from typing import Optional
from datetime import date

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ODDS_BASE = "https://api.the-odds-api.com/v4"

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class PropPick:
    sport:         str
    player:        str
    team:          str
    prop_type:     str        # "passing_yards", "strikeouts", "points", etc.
    line:          float
    recommendation: str       # "OVER" or "UNDER"
    player_avg:    float
    player_std:    float
    z_score:       float      # (avg - line) / std
    confidence:    float      # 0-1
    rationale:     list[str]
    matchup_note:  str = ""
    last_n_games:  list[float] = field(default_factory=list)


# ── ESPN stat fetchers ─────────────────────────────────────────────────────────

def _espn_get(sport_path: str, endpoint: str) -> dict:
    url = f"{ESPN_BASE}/{sport_path}/{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _find_player_id(sport_path: str, player_name: str) -> Optional[str]:
    try:
        data = _espn_get(sport_path, f"athletes?limit=1000&search={urllib.parse.quote(player_name)}")
        items = data.get("items", []) or data.get("athletes", [])
        if items:
            return str(items[0].get("id") or items[0].get("$ref", "").split("/")[-1])
    except Exception:
        pass
    return None


def _get_player_game_log(sport_path: str, player_id: str, stat_key: str, n: int = 10) -> list[float]:
    """Fetch last n game values for a specific stat from ESPN game log."""
    try:
        data = _espn_get(sport_path, f"athletes/{player_id}/gamelog")
        # ESPN gamelog structure varies by sport; extract relevant stat column
        events = data.get("events", {})
        labels = data.get("labels", [])

        if stat_key not in labels:
            # Try case-insensitive match
            stat_key = next((l for l in labels if l.lower() == stat_key.lower()), None)
            if not stat_key:
                return []

        idx = labels.index(stat_key)
        values = []
        # events is keyed by game ID; iterate in order
        for game_id, stats_list in list(events.items())[-n:]:
            if isinstance(stats_list, list) and idx < len(stats_list):
                try:
                    values.append(float(stats_list[idx]))
                except (ValueError, TypeError):
                    pass
        return values[-n:]
    except Exception:
        return []


# ── Odds API props fetcher ─────────────────────────────────────────────────────

def _get_player_props(sport_key: str, event_id: str, markets: list[str], api_key: str) -> dict:
    """Fetch player props for a specific game from The Odds API."""
    try:
        qs = urllib.parse.urlencode({
            "apiKey":     api_key,
            "regions":    "us",
            "markets":    ",".join(markets),
            "oddsFormat": "american",
        })
        url = f"{ODDS_BASE}/sports/{sport_key}/events/{event_id}/odds?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return {}


# ── Stat mapping per sport ─────────────────────────────────────────────────────

MLB_PROP_MARKETS = ["pitcher_strikeouts", "batter_hits", "batter_total_bases",
                    "pitcher_outs", "batter_runs_scored", "batter_rbis"]
NFL_PROP_MARKETS = ["player_pass_yds", "player_pass_attempts", "player_pass_tds",
                    "player_rush_yds", "player_rush_attempts",
                    "player_reception_yds", "player_receptions"]
NBA_PROP_MARKETS = ["player_points", "player_rebounds", "player_assists",
                    "player_blocks", "player_steals", "player_points_rebounds_assists",
                    "player_threes"]

# ESPN stat label → prop type mapping
ESPN_STAT_KEYS = {
    "mlb_pitcher": {"SO": "strikeouts", "IP": "outs_recorded"},
    "mlb_batter":  {"H": "hits", "TB": "total_bases", "R": "runs", "RBI": "rbis"},
    "nfl_qb":      {"YDS": "passing_yards", "ATT": "pass_attempts", "TD": "pass_tds"},
    "nfl_rb":      {"YDS": "rushing_yards", "ATT": "rush_attempts"},
    "nfl_wr":      {"YDS": "receiving_yards", "REC": "receptions"},
    "nba":         {"PTS": "points", "REB": "rebounds", "AST": "assists",
                    "BLK": "blocks", "STL": "steals", "3PM": "threes"},
}


# ── Opponent adjustment ────────────────────────────────────────────────────────

# How much each team allows relative to league average (1.0 = average, >1 = generous)
# These are rough 2024-25 season approximations
NBA_OPP_ALLOWED = {
    "points":   {
        "Golden State Warriors": 1.08, "Phoenix Suns": 1.12, "Brooklyn Nets": 1.14,
        "Charlotte Hornets": 1.15, "Washington Wizards": 1.18, "Atlanta Hawks": 1.10,
        "Boston Celtics": 0.88, "Oklahoma City Thunder": 0.90, "Minnesota Timberwolves": 0.91,
        "Cleveland Cavaliers": 0.92, "New York Knicks": 0.93,
        # default for unlisted teams
        "__default__": 1.0,
    },
    "rebounds": {"__default__": 1.0},
    "assists":  {"__default__": 1.0},
}


def _opp_adjustment(prop_type: str, opponent: str, sport: str) -> float:
    """Returns multiplier (e.g. 1.08 = opponent allows 8% more of this stat)."""
    if sport == "nba" and prop_type in NBA_OPP_ALLOWED:
        table = NBA_OPP_ALLOWED[prop_type]
        return table.get(opponent, table.get("__default__", 1.0))
    return 1.0


# ── Core prop analyser ─────────────────────────────────────────────────────────

def analyse_prop(
    player_name: str,
    team: str,
    opponent: str,
    sport: str,          # "mlb", "nfl", "nba"
    prop_type: str,      # e.g. "strikeouts", "points", "passing_yards"
    line: float,
    last_n: list[float] = None,   # pre-supplied game log (overrides ESPN fetch)
    espn_stat_key: str = None,
) -> Optional[PropPick]:
    """
    Analyses a single player prop.
    Returns PropPick if there's an edge, None if the line is fair.
    """
    sport_paths = {"mlb": "baseball/mlb", "nfl": "football/nfl", "nba": "basketball/nba"}
    sport_path  = sport_paths.get(sport, "basketball/nba")

    # Get game log
    values = last_n or []
    if not values and espn_stat_key:
        try:
            pid = _find_player_id(sport_path, player_name)
            if pid:
                values = _get_player_game_log(sport_path, pid, espn_stat_key, n=10)
        except Exception:
            pass

    if len(values) < 3:
        return None   # not enough data

    avg = sum(values) / len(values)
    std = math.sqrt(sum((v - avg) ** 2 for v in values) / len(values)) or 0.5

    # Opponent adjustment
    opp_mult = _opp_adjustment(prop_type, opponent, sport)
    adj_avg   = avg * opp_mult

    z = (adj_avg - line) / std
    confidence = min(0.85, 0.50 + abs(z) * 0.12)

    if abs(z) < 0.4:
        return None   # no meaningful edge

    rec = "OVER" if z > 0 else "UNDER"
    last5 = values[:5]

    rationale = [
        f"Last {len(values)} games avg: {avg:.1f} {prop_type} (line: {line})",
        f"Std dev: {std:.1f}  →  z-score vs line: {z:+.2f}",
        f"Opponent ({opponent}) allows {opp_mult:.2f}x avg {prop_type}",
        f"Adjusted avg vs this opponent: {adj_avg:.1f}",
        f"Last 5 game log: {[round(v,1) for v in last5]}",
    ]

    return PropPick(
        sport          = sport,
        player         = player_name,
        team           = team,
        prop_type      = prop_type,
        line           = line,
        recommendation = rec,
        player_avg     = round(avg, 2),
        player_std     = round(std, 2),
        z_score        = round(z, 3),
        confidence     = round(confidence, 3),
        rationale      = rationale,
        matchup_note   = f"opp multiplier {opp_mult:.2f}x",
        last_n_games   = values,
    )


def format_prop_pick(pick: PropPick) -> str:
    """Formats a PropPick for inclusion in daily report."""
    sym = "▲" if pick.recommendation == "OVER" else "▼"
    conf_bar = "█" * round(pick.confidence * 10) + "░" * (10 - round(pick.confidence * 10))
    lines = [
        f"  ⬡ PROP: {pick.player} ({pick.team})  {sym} {pick.recommendation} {pick.line} {pick.prop_type.upper().replace('_',' ')}",
        f"    Avg: {pick.player_avg:.1f}  Std: {pick.player_std:.1f}  z={pick.z_score:+.2f}  Conf: {pick.confidence:.0%}  [{conf_bar}]",
    ]
    for r in pick.rationale:
        lines.append(f"    • {r}")
    lines.append(f"  **THE PROP PICK: {pick.recommendation} {pick.line} {pick.player} {pick.prop_type.replace('_',' ')}**")
    return "\n".join(lines)


def scan_props_from_odds_api(sport_key: str, api_key: str, game_date: str) -> list[PropPick]:
    """
    Pulls all player props for today's games from The Odds API and
    runs analyse_prop on each one. Returns picks with edge.
    """
    sport_map = {
        "baseball_mlb":        ("mlb", MLB_PROP_MARKETS),
        "americanfootball_nfl":("nfl", NFL_PROP_MARKETS),
        "basketball_nba":      ("nba", NBA_PROP_MARKETS),
    }
    if sport_key not in sport_map:
        return []

    sport, markets = sport_map[sport_key]
    picks: list[PropPick] = []

    try:
        qs = urllib.parse.urlencode({"apiKey": api_key, "dateFormat": "iso", "oddsFormat": "american"})
        url = f"{ODDS_BASE}/sports/{sport_key}/odds?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            events = json.loads(r.read())
    except Exception:
        return []

    for event in events:
        if game_date not in event.get("commence_time", ""):
            continue
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        event_id = event.get("id", "")

        props_data = _get_player_props(sport_key, event_id, markets, api_key)

        for bm in props_data.get("bookmakers", [])[:2]:   # first 2 books enough
            for market in bm.get("markets", []):
                prop_type = market["key"].replace("player_", "")
                for outcome in market.get("outcomes", []):
                    player  = outcome.get("description", outcome.get("name", ""))
                    line    = outcome.get("point")
                    rec_raw = outcome.get("name", "")   # "Over" / "Under"
                    if line is None or rec_raw.lower() not in ("over", "under"):
                        continue

                    # determine opponent
                    team     = home   # crude — real impl maps player → team
                    opponent = away

                    pick = analyse_prop(
                        player_name  = player,
                        team         = team,
                        opponent     = opponent,
                        sport        = sport,
                        prop_type    = prop_type,
                        line         = float(line),
                    )
                    if pick:
                        picks.append(pick)

    # Deduplicate by player+prop, keep best z-score
    seen: dict[str, PropPick] = {}
    for p in picks:
        key = f"{p.player}:{p.prop_type}"
        if key not in seen or abs(p.z_score) > abs(seen[key].z_score):
            seen[key] = p

    return sorted(seen.values(), key=lambda p: abs(p.z_score), reverse=True)[:5]
