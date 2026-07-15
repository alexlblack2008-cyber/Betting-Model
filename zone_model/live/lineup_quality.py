"""
Lineup Quality Layer
=====================
Adjusts the expected run total based on how good each team's lineup is
versus the opposing starter's handedness.

Metric: wOBA (weighted On-Base Average) — the single best predictor of
        offensive run production at the team level.

League average wOBA: ~0.320 (right-handed pitchers)
                     ~0.315 (left-handed pitchers, due to platoon effects)

Run conversion: 1 wOBA point above average ≈ 0.04 extra runs per game
                at the team level (calibrated to 2019-2024 MLB data).

Sources:
  - Baseball Savant (statcast.baseball.savant.com)
  - FanGraphs wOBA constants
  - MLB Stats API (used for live player OBP as wOBA proxy)
"""

from __future__ import annotations

# League average wOBA vs each hand (2024 season)
LEAGUE_AVG_WOBA_VS_RHP = 0.318
LEAGUE_AVG_WOBA_VS_LHP = 0.314

# How many extra runs per wOBA point above average (per team per game)
RUNS_PER_WOBA_POINT = 0.04   # per 0.001 wOBA → 0.04 * delta

# Static wOBA lookup table per team (2024 season data, vs RHP / vs LHP).
# In production this is pulled from Baseball Savant splits CSVs.
# Updated periodically; the live API overlay in mlb_api.get_lineup_woba()
# replaces these when fresh data is available.
TEAM_WOBA_2024: dict[str, dict] = {
    "New York Yankees":         {"vs_rhp": 0.341, "vs_lhp": 0.328},
    "Houston Astros":           {"vs_rhp": 0.322, "vs_lhp": 0.318},
    "Atlanta Braves":           {"vs_rhp": 0.339, "vs_lhp": 0.331},
    "Los Angeles Dodgers":      {"vs_rhp": 0.345, "vs_lhp": 0.336},
    "Philadelphia Phillies":    {"vs_rhp": 0.334, "vs_lhp": 0.321},
    "Baltimore Orioles":        {"vs_rhp": 0.333, "vs_lhp": 0.320},
    "Minnesota Twins":          {"vs_rhp": 0.326, "vs_lhp": 0.315},
    "Texas Rangers":            {"vs_rhp": 0.328, "vs_lhp": 0.317},
    "Seattle Mariners":         {"vs_rhp": 0.304, "vs_lhp": 0.300},
    "San Diego Padres":         {"vs_rhp": 0.318, "vs_lhp": 0.313},
    "Cleveland Guardians":      {"vs_rhp": 0.321, "vs_lhp": 0.316},
    "Boston Red Sox":           {"vs_rhp": 0.330, "vs_lhp": 0.322},
    "San Francisco Giants":     {"vs_rhp": 0.308, "vs_lhp": 0.305},
    "Detroit Tigers":           {"vs_rhp": 0.305, "vs_lhp": 0.299},
    "Kansas City Royals":       {"vs_rhp": 0.320, "vs_lhp": 0.314},
    "St. Louis Cardinals":      {"vs_rhp": 0.309, "vs_lhp": 0.304},
    "Tampa Bay Rays":           {"vs_rhp": 0.315, "vs_lhp": 0.311},
    "Toronto Blue Jays":        {"vs_rhp": 0.323, "vs_lhp": 0.319},
    "New York Mets":            {"vs_rhp": 0.312, "vs_lhp": 0.308},
    "Milwaukee Brewers":        {"vs_rhp": 0.306, "vs_lhp": 0.302},
    "Pittsburgh Pirates":       {"vs_rhp": 0.296, "vs_lhp": 0.291},
    "Colorado Rockies":         {"vs_rhp": 0.310, "vs_lhp": 0.307},
    "Chicago Cubs":             {"vs_rhp": 0.313, "vs_lhp": 0.308},
    "Arizona Diamondbacks":     {"vs_rhp": 0.319, "vs_lhp": 0.315},
    "Miami Marlins":            {"vs_rhp": 0.289, "vs_lhp": 0.284},
    "Washington Nationals":     {"vs_rhp": 0.294, "vs_lhp": 0.289},
    "Chicago White Sox":        {"vs_rhp": 0.272, "vs_lhp": 0.268},
    "Oakland Athletics":        {"vs_rhp": 0.287, "vs_lhp": 0.282},
    "Los Angeles Angels":       {"vs_rhp": 0.295, "vs_lhp": 0.290},
    "Cincinnati Reds":          {"vs_rhp": 0.316, "vs_lhp": 0.311},
}


def get_team_woba(team_name: str, pitcher_hand: str,
                  live_woba: float | None = None) -> float:
    """
    Returns the team's expected wOBA against a given pitcher hand.

    live_woba: if provided (from mlb_api.get_lineup_woba), overrides the
               static table and is used directly.
    """
    if live_woba is not None and 0.200 < live_woba < 0.450:
        return live_woba

    row = TEAM_WOBA_2024.get(team_name)
    if row is None:
        # Fuzzy name match
        for k in TEAM_WOBA_2024:
            if any(w in team_name for w in k.split()):
                row = TEAM_WOBA_2024[k]
                break

    if row is None:
        return LEAGUE_AVG_WOBA_VS_RHP if pitcher_hand == "R" else LEAGUE_AVG_WOBA_VS_LHP

    return row["vs_rhp"] if pitcher_hand == "R" else row["vs_lhp"]


def lineup_run_adjustment(
    batting_team: str,
    opposing_pitcher_hand: str,
    live_woba: float | None = None,
) -> float:
    """
    Returns the run-scoring adjustment for this team's lineup vs. the
    opposing pitcher's handedness.

    Positive  → team expected to score more than average (adds to total)
    Negative  → team expected to score less than average (subtracts from total)
    """
    woba = get_team_woba(batting_team, opposing_pitcher_hand, live_woba)
    baseline = LEAGUE_AVG_WOBA_VS_RHP if opposing_pitcher_hand == "R" \
               else LEAGUE_AVG_WOBA_VS_LHP

    delta_woba = woba - baseline              # e.g. +0.023 for a good lineup
    run_adj = delta_woba * 1000 * RUNS_PER_WOBA_POINT  # scale to runs

    return round(run_adj, 3)


def total_lineup_adjustment(
    home_team: str, away_team: str,
    home_starter_hand: str, away_starter_hand: str,
    home_live_woba: float | None = None,
    away_live_woba: float | None = None,
) -> dict:
    """
    Computes lineup quality adjustment for BOTH teams and returns a summary.

    home_adj: away team's offense vs. home starter (away team scoring more/less)
    away_adj: home team's offense vs. away starter (home team scoring more/less)
    total_adj: combined effect on the run total
    """
    # Away offense vs. home starter hand
    away_off_adj = lineup_run_adjustment(away_team, home_starter_hand, away_live_woba)
    # Home offense vs. away starter hand
    home_off_adj = lineup_run_adjustment(home_team, away_starter_hand, home_live_woba)

    return {
        "home_offense_adj": home_off_adj,    # home team scores more/less
        "away_offense_adj": away_off_adj,    # away team scores more/less
        "total_lineup_adj": round(home_off_adj + away_off_adj, 3),
    }
