"""
ESPN public API client.
Endpoint: https://site.api.espn.com/apis/site/v2/sports/
No API key required. Used as fallback/supplement for:
  - MLB schedule and scores  (replaces statsapi.mlb.com when blocked)
  - World Cup live scores    (feeds Bonus Pick engine)
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import date
from typing import Optional

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# Sport path segments for ESPN
SPORT_PATHS = {
    "mlb":        "baseball/mlb",
    "world_cup":  "soccer/fifa.world",
    "nfl":        "football/nfl",
    "nba":        "basketball/nba",
    "nhl":        "hockey/nhl",
    "ufc":        "mma/ufc",
}


def _get(sport: str, endpoint: str, date_str: Optional[str] = None) -> dict:
    path = SPORT_PATHS.get(sport, sport)
    url  = f"{ESPN_BASE}/{path}/{endpoint}"
    if date_str:
        compact = date_str.replace("-", "")
        url += f"?dates={compact}"
    req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_mlb_scoreboard(game_date: Optional[str] = None) -> list[dict]:
    """
    Returns today's MLB games from ESPN with home/away teams, status, and score.
    Each dict: { game_id, home_team, away_team, status, home_score, away_score,
                 total_runs, venue, home_abbr, away_abbr }
    """
    d = game_date or date.today().isoformat()
    try:
        data = _get("mlb", "scoreboard", d)
    except Exception:
        return []

    games = []
    for ev in data.get("events", []):
        comps = ev.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        if len(competitors) < 2:
            continue

        # ESPN uses home/away as "homeAway" field
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)
        status     = ev.get("status", {}).get("type", {}).get("name", "scheduled")

        games.append({
            "game_id":     ev.get("id"),
            "home_team":   home.get("team", {}).get("displayName", ""),
            "away_team":   away.get("team", {}).get("displayName", ""),
            "home_abbr":   home.get("team", {}).get("abbreviation", ""),
            "away_abbr":   away.get("team", {}).get("abbreviation", ""),
            "status":      status,
            "home_score":  home_score,
            "away_score":  away_score,
            "total_runs":  home_score + away_score,
            "venue":       comps.get("venue", {}).get("fullName", ""),
            "completed":   status.lower() in ("final", "completed"),
        })
    return games


def get_world_cup_scoreboard(game_date: Optional[str] = None) -> list[dict]:
    """
    Returns today's World Cup matches from ESPN.
    Each dict: { game_id, home_team, away_team, status, home_score, away_score,
                 total_goals, completed, venue, round_name }
    """
    d = game_date or date.today().isoformat()
    try:
        data = _get("world_cup", "scoreboard", d)
    except Exception:
        return []

    matches = []
    for ev in data.get("events", []):
        comps       = ev.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        if len(competitors) < 2:
            continue

        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)
        status     = ev.get("status", {}).get("type", {}).get("name", "scheduled")
        round_name = ev.get("season", {}).get("slug", "") or \
                     comps.get("notes", [{}])[0].get("headline", "World Cup")

        matches.append({
            "game_id":     ev.get("id"),
            "home_team":   home.get("team", {}).get("displayName", ""),
            "away_team":   away.get("team", {}).get("displayName", ""),
            "status":      status,
            "home_score":  home_score,
            "away_score":  away_score,
            "total_goals": home_score + away_score,
            "completed":   status.lower() in ("final", "completed", "ft"),
            "venue":       comps.get("venue", {}).get("fullName", ""),
            "round_name":  round_name,
            "spread":      None,   # ESPN doesn't carry betting lines
        })
    return matches


def auto_settle_mlb(ledger_path: str, game_date: Optional[str] = None) -> list[str]:
    """
    Fetches yesterday's final MLB scores from ESPN and settles any pending picks
    in the ledger automatically. Returns list of settlement messages.
    """
    import json as _json
    import os
    from pathlib import Path

    d = game_date or date.today().isoformat()
    games = get_mlb_scoreboard(d)
    completed = [g for g in games if g["completed"]]

    if not completed:
        return []

    path = Path(ledger_path)
    if not path.exists():
        return []

    with open(path) as f:
        entries = _json.load(f)

    STAKE = 100.0
    WIN_PAYOUT = round(STAKE / 1.10, 2)
    messages = []

    for entry in entries:
        if entry["outcome"] != "pending" or entry["bet_date"] != d:
            continue
        match = next(
            (g for g in completed
             if entry["home_team"].lower() in g["home_team"].lower()
             or g["home_team"].lower() in entry["home_team"].lower()),
            None
        )
        if not match:
            continue

        actual = match["total_runs"]
        total  = entry["market_total"]
        rec    = entry["recommendation"]
        if rec == "OVER":
            result = "won" if actual > total else ("push" if actual == total else "lost")
        else:
            result = "won" if actual < total else ("push" if actual == total else "lost")

        entry["actual_runs"] = actual
        entry["outcome"]     = result
        entry["pnl"]         = WIN_PAYOUT if result == "won" else (-STAKE if result == "lost" else 0.0)
        entry["settled_at"]  = __import__("datetime").datetime.utcnow().isoformat()

        pnl_str = f"+${entry['pnl']:.2f}" if entry["pnl"] >= 0 else f"-${abs(entry['pnl']):.2f}"
        messages.append(
            f"  AUTO-SETTLED: {entry['away_team']} @ {entry['home_team']} "
            f"— actual {actual} runs — {result.upper()} {pnl_str}"
        )

    with open(path, "w") as f:
        _json.dump(entries, f, indent=2)

    return messages
