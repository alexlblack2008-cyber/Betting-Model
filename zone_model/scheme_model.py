"""
Scheme Matchup Model
====================
For scheme-heavy sports (NFL, NBA), analyses how offensive and defensive
schemes match up against each other, and factors in historical head-to-head
results between the two teams.

Methodology:
  1. Each team has an offensive scheme profile and a defensive scheme profile
  2. Scheme matchup score = how well offense A exploits defense B (and vice versa)
  3. H2H history: last 5 meetings between the two teams, weighted by recency
  4. Recent form overlay (last 5 games each team)
  5. Output: point total adjustment + side lean + rationale bullets

NFL Offensive Schemes:
  run_heavy, west_coast, spread_option, air_raid, pro_style, RPO

NFL Defensive Schemes:
  4-3, 3-4, tampa_2, cover_2, cover_3, nickel_base, dime_package, 46

NBA Offensive Schemes:
  motion_offense, triangle, pace_and_space, iso_heavy, pick_and_roll, princeton

NBA Defensive Schemes:
  man_to_man, zone_2-3, switch_everything, drop_coverage, help_and_recover, blitz_pick_roll
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional
from datetime import date

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"


# ── NFL Scheme Profiles ────────────────────────────────────────────────────────

NFL_TEAM_SCHEMES: dict[str, dict] = {
    "Kansas City Chiefs":       {"off": "RPO",          "def": "4-3",          "pace": "fast",  "off_rating": 92, "def_rating": 85},
    "San Francisco 49ers":      {"off": "shanahan_wide_zone", "def": "nickel_base", "pace": "medium", "off_rating": 88, "def_rating": 90},
    "Baltimore Ravens":         {"off": "RPO",          "def": "4-3",          "pace": "fast",  "off_rating": 90, "def_rating": 87},
    "Philadelphia Eagles":      {"off": "spread_option","def": "4-3",          "pace": "fast",  "off_rating": 85, "def_rating": 88},
    "Dallas Cowboys":           {"off": "west_coast",   "def": "4-3",          "pace": "medium","off_rating": 83, "def_rating": 82},
    "Buffalo Bills":            {"off": "air_raid",     "def": "4-3",          "pace": "fast",  "off_rating": 89, "def_rating": 86},
    "Cincinnati Bengals":       {"off": "west_coast",   "def": "3-4",          "pace": "medium","off_rating": 87, "def_rating": 78},
    "Detroit Lions":            {"off": "RPO",          "def": "4-3",          "pace": "fast",  "off_rating": 91, "def_rating": 80},
    "Green Bay Packers":        {"off": "west_coast",   "def": "3-4",          "pace": "medium","off_rating": 84, "def_rating": 83},
    "Miami Dolphins":           {"off": "air_raid",     "def": "nickel_base",  "pace": "fast",  "off_rating": 86, "def_rating": 79},
    "New York Jets":            {"off": "pro_style",    "def": "cover_2",      "pace": "slow",  "off_rating": 74, "def_rating": 88},
    "Pittsburgh Steelers":      {"off": "pro_style",    "def": "3-4",          "pace": "slow",  "off_rating": 76, "def_rating": 85},
    "Cleveland Browns":         {"off": "run_heavy",    "def": "4-3",          "pace": "slow",  "off_rating": 79, "def_rating": 84},
    "Houston Texans":           {"off": "RPO",          "def": "4-3",          "pace": "fast",  "off_rating": 82, "def_rating": 81},
    "Jacksonville Jaguars":     {"off": "west_coast",   "def": "cover_3",      "pace": "medium","off_rating": 78, "def_rating": 77},
    "Tennessee Titans":         {"off": "run_heavy",    "def": "3-4",          "pace": "slow",  "off_rating": 72, "def_rating": 80},
    "Indianapolis Colts":       {"off": "pro_style",    "def": "cover_2",      "pace": "medium","off_rating": 77, "def_rating": 79},
    "Los Angeles Rams":         {"off": "air_raid",     "def": "nickel_base",  "pace": "medium","off_rating": 85, "def_rating": 82},
    "Los Angeles Chargers":     {"off": "west_coast",   "def": "cover_3",      "pace": "medium","off_rating": 83, "def_rating": 80},
    "Denver Broncos":           {"off": "pro_style",    "def": "3-4",          "pace": "medium","off_rating": 76, "def_rating": 81},
    "Las Vegas Raiders":        {"off": "west_coast",   "def": "4-3",          "pace": "medium","off_rating": 74, "def_rating": 75},
    "Seattle Seahawks":         {"off": "RPO",          "def": "cover_3",      "pace": "fast",  "off_rating": 81, "def_rating": 78},
    "Arizona Cardinals":        {"off": "spread_option","def": "cover_2",      "pace": "fast",  "off_rating": 75, "def_rating": 74},
    "New Orleans Saints":       {"off": "west_coast",   "def": "4-3",          "pace": "medium","off_rating": 80, "def_rating": 83},
    "Atlanta Falcons":          {"off": "RPO",          "def": "cover_3",      "pace": "medium","off_rating": 82, "def_rating": 76},
    "Carolina Panthers":        {"off": "spread_option","def": "4-3",          "pace": "medium","off_rating": 70, "def_rating": 72},
    "Tampa Bay Buccaneers":     {"off": "air_raid",     "def": "tampa_2",      "pace": "medium","off_rating": 80, "def_rating": 79},
    "Minnesota Vikings":        {"off": "west_coast",   "def": "cover_2",      "pace": "medium","off_rating": 84, "def_rating": 78},
    "Chicago Bears":            {"off": "RPO",          "def": "cover_3",      "pace": "medium","off_rating": 78, "def_rating": 77},
    "New York Giants":          {"off": "pro_style",    "def": "4-3",          "pace": "slow",  "off_rating": 72, "def_rating": 76},
    "Washington Commanders":    {"off": "RPO",          "def": "4-3",          "pace": "medium","off_rating": 79, "def_rating": 80},
    "New England Patriots":     {"off": "pro_style",    "def": "3-4",          "pace": "slow",  "off_rating": 71, "def_rating": 82},
}

# Scheme matchup advantages: offense_scheme → {defense_scheme: advantage}
# Positive = offense has edge, negative = defense has edge. Scale: -2 to +2
NFL_SCHEME_MATCHUPS: dict[str, dict[str, float]] = {
    "air_raid":          {"tampa_2": +1.8, "cover_2": +1.5, "cover_3": +0.5, "4-3": +0.3, "3-4": +0.2, "nickel_base": -0.5, "dime_package": -1.2, "46": -0.8, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "RPO":               {"4-3": +1.2, "3-4": +0.8, "cover_3": +0.5, "nickel_base": -0.3, "cover_2": +0.4, "tampa_2": +0.2, "dime_package": +1.0, "46": -0.5, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "spread_option":     {"4-3": +0.8, "3-4": +1.2, "cover_2": +0.5, "cover_3": +0.2, "nickel_base": +0.3, "tampa_2": +0.6, "dime_package": +0.8, "46": -1.0, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "run_heavy":         {"nickel_base": +1.5, "dime_package": +2.0, "cover_3": +0.8, "tampa_2": +0.5, "4-3": -0.3, "3-4": -0.5, "cover_2": +0.3, "46": -1.5, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "west_coast":        {"4-3": +0.5, "3-4": +0.3, "cover_2": +1.0, "cover_3": +0.8, "nickel_base": +0.2, "tampa_2": -0.5, "dime_package": +0.5, "46": -0.3, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "pro_style":         {"4-3": +0.2, "3-4": +0.1, "cover_2": +0.3, "cover_3": +0.2, "nickel_base": +0.1, "tampa_2": +0.1, "dime_package": +0.4, "46": -0.8, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
    "shanahan_wide_zone":{"4-3": +1.0, "3-4": +1.3, "nickel_base": +0.8, "cover_3": +0.5, "tampa_2": +0.3, "cover_2": +0.5, "dime_package": +1.2, "46": -0.4, "switch_everything": 0.0, "blitz_pick_roll": 0.0},
}

# NBA Team Schemes
NBA_TEAM_SCHEMES: dict[str, dict] = {
    "Boston Celtics":           {"off": "motion_offense",  "def": "switch_everything", "pace": 97,  "off_rating": 122, "def_rating": 108},
    "Denver Nuggets":           {"off": "pick_and_roll",   "def": "drop_coverage",     "pace": 96,  "off_rating": 119, "def_rating": 113},
    "Oklahoma City Thunder":    {"off": "pace_and_space",  "def": "switch_everything", "pace": 101, "off_rating": 120, "def_rating": 109},
    "Cleveland Cavaliers":      {"off": "motion_offense",  "def": "drop_coverage",     "pace": 96,  "off_rating": 116, "def_rating": 107},
    "New York Knicks":          {"off": "iso_heavy",       "def": "man_to_man",        "pace": 93,  "off_rating": 115, "def_rating": 110},
    "Indiana Pacers":           {"off": "pace_and_space",  "def": "help_and_recover",  "pace": 103, "off_rating": 118, "def_rating": 115},
    "Milwaukee Bucks":          {"off": "iso_heavy",       "def": "drop_coverage",     "pace": 97,  "off_rating": 116, "def_rating": 113},
    "Orlando Magic":            {"off": "motion_offense",  "def": "zone_2-3",          "pace": 96,  "off_rating": 113, "def_rating": 109},
    "Miami Heat":               {"off": "motion_offense",  "def": "man_to_man",        "pace": 95,  "off_rating": 112, "def_rating": 111},
    "Chicago Bulls":            {"off": "pick_and_roll",   "def": "drop_coverage",     "pace": 96,  "off_rating": 111, "def_rating": 114},
    "Minnesota Timberwolves":   {"off": "motion_offense",  "def": "switch_everything", "pace": 98,  "off_rating": 117, "def_rating": 108},
    "Dallas Mavericks":         {"off": "iso_heavy",       "def": "drop_coverage",     "pace": 97,  "off_rating": 120, "def_rating": 112},
    "Los Angeles Lakers":       {"off": "iso_heavy",       "def": "help_and_recover",  "pace": 96,  "off_rating": 116, "def_rating": 113},
    "Golden State Warriors":    {"off": "motion_offense",  "def": "switch_everything", "pace": 99,  "off_rating": 115, "def_rating": 114},
    "Phoenix Suns":             {"off": "pick_and_roll",   "def": "drop_coverage",     "pace": 100, "off_rating": 114, "def_rating": 116},
    "LA Clippers":              {"off": "motion_offense",  "def": "man_to_man",        "pace": 97,  "off_rating": 113, "def_rating": 112},
    "Sacramento Kings":         {"off": "pace_and_space",  "def": "help_and_recover",  "pace": 102, "off_rating": 117, "def_rating": 117},
    "Memphis Grizzlies":        {"off": "pick_and_roll",   "def": "man_to_man",        "pace": 100, "off_rating": 114, "def_rating": 113},
    "New Orleans Pelicans":     {"off": "motion_offense",  "def": "help_and_recover",  "pace": 98,  "off_rating": 112, "def_rating": 112},
    "Houston Rockets":          {"off": "pace_and_space",  "def": "switch_everything", "pace": 100, "off_rating": 113, "def_rating": 111},
    "Atlanta Hawks":            {"off": "pace_and_space",  "def": "help_and_recover",  "pace": 102, "off_rating": 115, "def_rating": 117},
    "Toronto Raptors":          {"off": "motion_offense",  "def": "switch_everything", "pace": 97,  "off_rating": 110, "def_rating": 112},
    "Detroit Pistons":          {"off": "pick_and_roll",   "def": "drop_coverage",     "pace": 98,  "off_rating": 109, "def_rating": 116},
    "Charlotte Hornets":        {"off": "pace_and_space",  "def": "zone_2-3",          "pace": 99,  "off_rating": 108, "def_rating": 118},
    "Washington Wizards":       {"off": "iso_heavy",       "def": "drop_coverage",     "pace": 99,  "off_rating": 107, "def_rating": 119},
    "Portland Trail Blazers":   {"off": "motion_offense",  "def": "drop_coverage",     "pace": 98,  "off_rating": 109, "def_rating": 117},
    "Utah Jazz":                {"off": "pick_and_roll",   "def": "drop_coverage",     "pace": 100, "off_rating": 108, "def_rating": 118},
    "San Antonio Spurs":        {"off": "motion_offense",  "def": "help_and_recover",  "pace": 99,  "off_rating": 107, "def_rating": 117},
    "Brooklyn Nets":            {"off": "iso_heavy",       "def": "help_and_recover",  "pace": 98,  "off_rating": 106, "def_rating": 118},
    "Philadelphia 76ers":       {"off": "iso_heavy",       "def": "drop_coverage",     "pace": 95,  "off_rating": 113, "def_rating": 113},
}

NBA_SCHEME_MATCHUPS: dict[str, dict[str, float]] = {
    "motion_offense":    {"man_to_man": +1.2, "switch_everything": -0.5, "zone_2-3": +0.8, "drop_coverage": +0.5, "help_and_recover": +0.3, "blitz_pick_roll": +0.2},
    "pace_and_space":    {"drop_coverage": +1.8, "zone_2-3": +1.2, "man_to_man": +0.5, "help_and_recover": +0.8, "switch_everything": -0.3, "blitz_pick_roll": +0.5},
    "pick_and_roll":     {"drop_coverage": +1.5, "man_to_man": +0.8, "switch_everything": -1.0, "zone_2-3": +0.5, "help_and_recover": +0.3, "blitz_pick_roll": -1.5},
    "iso_heavy":         {"man_to_man": +0.5, "switch_everything": +0.8, "drop_coverage": +0.3, "zone_2-3": +1.0, "help_and_recover": -0.5, "blitz_pick_roll": +0.2},
    "triangle":          {"zone_2-3": +1.0, "man_to_man": +0.5, "drop_coverage": +0.8, "switch_everything": +0.3, "help_and_recover": +0.2, "blitz_pick_roll": +0.5},
    "princeton":         {"man_to_man": +1.5, "switch_everything": +0.5, "zone_2-3": -0.3, "drop_coverage": +1.0, "help_and_recover": +0.8, "blitz_pick_roll": +0.5},
}


# ── H2H History ────────────────────────────────────────────────────────────────

@dataclass
class H2HRecord:
    team_a:      str
    team_b:      str
    games:       list[dict] = field(default_factory=list)   # {date, a_score, b_score, winner}
    a_wins:      int = 0
    b_wins:      int = 0
    avg_total:   float = 0.0
    avg_margin:  float = 0.0   # positive = team_a wins by this much on avg
    available:   bool = False


def _espn_get(sport: str, path: str) -> dict:
    paths = {"nfl": ("football","nfl"), "nba": ("basketball","nba"),
             "mlb": ("baseball","mlb"), "nhl": ("hockey","nhl")}
    s, l = paths.get(sport, ("football","nfl"))
    url = f"{ESPN_BASE}/{s}/{l}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get_h2h_history(sport: str, team_a: str, team_b: str, n: int = 5) -> H2HRecord:
    """
    Fetch last n head-to-head meetings between team_a and team_b via ESPN.
    Falls back gracefully on network failure.
    """
    record = H2HRecord(team_a=team_a, team_b=team_b)
    try:
        # ESPN H2H endpoint
        data = _espn_get(sport, f"teams/{team_a}/schedule")
        events = [
            ev for ev in data.get("events", [])
            if any(
                team_b.lower() in c.get("team", {}).get("displayName", "").lower()
                for c in ev.get("competitions", [{}])[0].get("competitors", [])
            )
            and ev.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed", False)
        ]
        events = events[-n:]

        for ev in events:
            comps = ev.get("competitions", [{}])[0]
            competitors = comps.get("competitors", [])
            a_comp = next((c for c in competitors if team_a.lower() in c.get("team", {}).get("displayName", "").lower()), None)
            b_comp = next((c for c in competitors if a_comp and c is not a_comp), None)
            if not a_comp or not b_comp:
                continue
            a_score = float(a_comp.get("score", 0) or 0)
            b_score = float(b_comp.get("score", 0) or 0)
            winner  = team_a if a_comp.get("winner") else team_b
            record.games.append({
                "date": ev.get("date", "")[:10],
                "a_score": a_score, "b_score": b_score, "winner": winner
            })
            if winner == team_a:
                record.a_wins += 1
            else:
                record.b_wins += 1

        if record.games:
            record.available  = True
            totals  = [g["a_score"] + g["b_score"] for g in record.games]
            margins = [g["a_score"] - g["b_score"]  for g in record.games]
            record.avg_total  = round(sum(totals)  / len(totals),  1)
            record.avg_margin = round(sum(margins) / len(margins), 1)

    except Exception:
        pass
    return record


# ── Scheme Matchup Scorer ──────────────────────────────────────────────────────

@dataclass
class SchemeMatchupOutput:
    home_team:      str
    away_team:      str
    sport:          str
    total_adj:      float        # points to add/subtract from expected total
    side_lean:      str          # "HOME", "AWAY", or "NEUTRAL"
    side_edge:      float        # 0-10 conviction on side lean
    h2h:            H2HRecord    = field(default_factory=H2HRecord)
    rationale:      list[str]    = field(default_factory=list)
    scheme_note:    str          = ""


def score_scheme_matchup(sport: str, home_team: str, away_team: str) -> SchemeMatchupOutput:
    """
    Computes scheme matchup score and H2H analysis for NFL or NBA games.
    Returns total adjustment (+ = lean over, - = lean under) and side lean.
    """
    output = SchemeMatchupOutput(home_team=home_team, away_team=away_team, sport=sport)

    schemes = NFL_TEAM_SCHEMES if sport == "nfl" else NBA_TEAM_SCHEMES
    matchups = NFL_SCHEME_MATCHUPS if sport == "nfl" else NBA_SCHEME_MATCHUPS

    home_scheme = schemes.get(home_team, {})
    away_scheme = schemes.get(away_team, {})

    rationale = []

    if home_scheme and away_scheme:
        home_off = home_scheme.get("off", "pro_style")
        home_def = home_scheme.get("def", "4-3")
        away_off = away_scheme.get("off", "pro_style")
        away_def = away_scheme.get("def", "4-3")

        # How well does home offense do vs away defense, and vice versa
        home_off_edge = matchups.get(home_off, {}).get(away_def, 0.0)
        away_off_edge = matchups.get(away_off, {}).get(home_def, 0.0)

        # Total adjustment: both teams scoring more → higher total
        # Each edge unit = ~1.5 pts in NFL, ~2 pts in NBA
        scale = 1.5 if sport == "nfl" else 2.0
        total_adj = round((home_off_edge + away_off_edge) * scale, 2)
        output.total_adj = total_adj

        # Rating differential for side lean
        home_rtg = home_scheme.get("off_rating", 80) - away_scheme.get("def_rating", 80)
        away_rtg = away_scheme.get("off_rating", 80) - home_scheme.get("def_rating", 80)
        # Home field adds ~3 pts NFL, ~2.5 pts NBA
        home_advantage = 3.0 if sport == "nfl" else 2.5
        net = home_rtg - away_rtg + home_advantage

        output.side_lean  = "HOME" if net > 2 else ("AWAY" if net < -2 else "NEUTRAL")
        output.side_edge  = round(min(10.0, abs(net) / 2), 1)

        rationale += [
            f"{home_team} runs {home_off} offense vs {away_team}'s {away_def} defense → {home_off_edge:+.1f} edge",
            f"{away_team} runs {away_off} offense vs {home_team}'s {home_def} defense → {away_off_edge:+.1f} edge",
            f"Total scheme adjustment: {total_adj:+.1f} points",
            f"Rating-based side lean: {output.side_lean} (edge {output.side_edge}/10)",
        ]

        pace_note = ""
        if sport == "nfl":
            home_pace = home_scheme.get("pace", "medium")
            away_pace = away_scheme.get("pace", "medium")
            if home_pace == "fast" and away_pace == "fast":
                output.total_adj += 3.0
                pace_note = "both teams run fast pace → +3 pts"
            elif home_pace == "slow" and away_pace == "slow":
                output.total_adj -= 3.0
                pace_note = "both teams run slow pace → -3 pts"
        else:
            home_pace = home_scheme.get("pace", 98)
            away_pace = away_scheme.get("pace", 98)
            combined_pace = (home_pace + away_pace) / 2
            pace_adj = (combined_pace - 98) * 0.5
            output.total_adj += pace_adj
            pace_note = f"combined pace {combined_pace:.0f} → {pace_adj:+.1f} pts"

        if pace_note:
            rationale.append(f"Pace: {pace_note}")

        output.scheme_note = f"{home_off} vs {away_def} | {away_off} vs {home_def}"

    # H2H history
    h2h = get_h2h_history(sport, home_team, away_team)
    output.h2h = h2h
    if h2h.available:
        rationale.append(
            f"H2H last {len(h2h.games)} meetings: {team_a_name(h2h)} {h2h.a_wins}-{h2h.b_wins} "
            f"avg total {h2h.avg_total:.1f} pts, avg margin {h2h.avg_margin:+.1f}"
        )
        # If H2H average total differs significantly from market, adjust
        # (used by caller to cross-check)

    output.rationale = rationale
    return output


def team_a_name(h2h: H2HRecord) -> str:
    return h2h.team_a.split()[-1]
