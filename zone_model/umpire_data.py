"""
Umpire historical tendency profiles.

In production these are populated from Baseball Savant / Statcast CSV exports.
For demonstration the values below are realistic approximations based on
public umpire data (2019-2025 seasons, minimum 200 games umpired).

Key metrics:
  csraa  - Called Strike Rate Above Average (percentage points)
           Positive = bigger zone, more strikes called → pitchers benefit
  run_impact - Average runs per game vs league average
               Negative = fewer runs (pitcher-friendly zone)
  k_factor   - Multiplier on expected strikeout total (1.0 = neutral)
  bb_factor  - Multiplier on expected walk total (1.0 = neutral)
  sample_games - number of games in the profile (confidence indicator)
"""

UMPIRE_PROFILES = {
    # (name): (csraa, run_impact, k_factor, bb_factor, sample_games)
    "Angel Hernandez":   {"csraa": -1.8, "run_impact": +0.31, "k_factor": 0.94, "bb_factor": 1.09, "games": 312},
    "CB Bucknor":        {"csraa": -2.1, "run_impact": +0.44, "k_factor": 0.91, "bb_factor": 1.12, "games": 287},
    "Joe West":          {"csraa": +0.9, "run_impact": -0.18, "k_factor": 1.04, "bb_factor": 0.97, "games": 401},
    "Dan Iassogna":      {"csraa": +1.4, "run_impact": -0.29, "k_factor": 1.07, "bb_factor": 0.94, "games": 298},
    "Nic Lentz":         {"csraa": +2.1, "run_impact": -0.51, "k_factor": 1.11, "bb_factor": 0.89, "games": 244},
    "Marvin Hudson":     {"csraa": +0.4, "run_impact": -0.08, "k_factor": 1.02, "bb_factor": 0.99, "games": 319},
    "Jeff Nelson":       {"csraa": -0.6, "run_impact": +0.12, "k_factor": 0.97, "bb_factor": 1.03, "games": 276},
    "Sam Holbrook":      {"csraa": +1.8, "run_impact": -0.38, "k_factor": 1.08, "bb_factor": 0.93, "games": 261},
    "Bill Miller":       {"csraa": -1.2, "run_impact": +0.24, "k_factor": 0.95, "bb_factor": 1.07, "games": 305},
    "Mark Wegner":       {"csraa": +0.7, "run_impact": -0.14, "k_factor": 1.03, "bb_factor": 0.97, "games": 289},
    "Hunter Wendelstedt":{"csraa": +1.1, "run_impact": -0.22, "k_factor": 1.05, "bb_factor": 0.96, "games": 334},
    "Doug Eddings":      {"csraa": +0.2, "run_impact": -0.04, "k_factor": 1.01, "bb_factor": 1.00, "games": 302},
    "Brian Gorman":      {"csraa": -0.3, "run_impact": +0.06, "k_factor": 0.98, "bb_factor": 1.02, "games": 278},
    "Laz Diaz":          {"csraa": -1.5, "run_impact": +0.28, "k_factor": 0.93, "bb_factor": 1.08, "games": 341},
    "Todd Tichenor":     {"csraa": +0.6, "run_impact": -0.11, "k_factor": 1.03, "bb_factor": 0.98, "games": 255},
    # Neutral baseline used when umpire is unknown
    "__UNKNOWN__":       {"csraa":  0.0, "run_impact":  0.00, "k_factor": 1.00, "bb_factor": 1.00, "games": 0},
}

# League-average context anchors (2024 MLB season)
LEAGUE_AVG = {
    "runs_per_game_per_team": 4.43,   # runs scored per team per 9 innings
    "k_per_game":              8.9,   # total Ks per game (both sides)
    "bb_per_game":             3.2,   # total BBs per game (both sides)
    "total_avg":               9.1,   # average posted over/under
}
