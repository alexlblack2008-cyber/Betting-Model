"""
Historical game data loader for backtesting.

Data format expected (CSV, one row per game):
  date, home_team, away_team, umpire, home_starter, away_starter,
  home_starter_hand, away_starter_hand,
  home_days_rest, away_days_rest,
  home_bp_era_7d, away_bp_era_7d,
  home_bp_ip_3d, away_bp_ip_3d,
  home_tz_change, away_tz_change,
  home_off_rating, away_off_rating,
  home_bp_highlev_yest, away_bp_highlev_yest,
  venue_name,
  open_total, close_total,      # posted and closing over/under
  actual_runs                    # final combined runs scored

Since we cannot download a multi-year CSV at runtime, this module ships
with a synthetic 500-game dataset that statistically mirrors 2022-2024 MLB
distributions. The synthetic data is generated deterministically (seeded)
so results are reproducible.

To replace with real data: drop a CSV at the path returned by data_path()
with the columns above. The loader detects and uses it automatically.
"""

from __future__ import annotations
import csv
import os
import random
import math
from pathlib import Path

DATA_DIR  = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "historical_games.csv"

TEAMS = [
    "New York Yankees", "Houston Astros", "Los Angeles Dodgers",
    "Atlanta Braves", "Philadelphia Phillies", "Baltimore Orioles",
    "Texas Rangers", "Seattle Mariners", "San Diego Padres",
    "Cleveland Guardians", "Boston Red Sox", "Minnesota Twins",
    "Toronto Blue Jays", "Tampa Bay Rays", "Chicago Cubs",
    "Milwaukee Brewers", "St. Louis Cardinals", "San Francisco Giants",
    "Arizona Diamondbacks", "Cincinnati Reds",
]

UMPIRES = list({
    "Angel Hernandez", "CB Bucknor", "Joe West", "Dan Iassogna",
    "Nic Lentz", "Marvin Hudson", "Jeff Nelson", "Sam Holbrook",
    "Bill Miller", "Mark Wegner", "Hunter Wendelstedt", "Laz Diaz",
})

STARTERS = {
    "R": ["Gerrit Cole", "Zack Wheeler", "Dylan Cease", "Sandy Alcantara",
          "Logan Webb", "Max Scherzer", "Spencer Strider"],
    "L": ["Blake Snell", "Clayton Kershaw", "Julio Urias", "Patrick Corbin"],
}

VENUES = [
    "Yankee Stadium", "Fenway Park", "Dodger Stadium", "Truist Park",
    "Citizens Bank Park", "Camden Yards", "Globe Life Field",
    "T-Mobile Park", "Petco Park", "Progressive Field",
    "Wrigley Field", "American Family Field", "Busch Stadium",
    "Oracle Park", "Chase Field", "Great American Ball Park",
]


def _synthetic_game(rng: random.Random, game_id: int) -> dict:
    """Generates one plausible synthetic game row."""
    home = rng.choice(TEAMS)
    away = rng.choice([t for t in TEAMS if t != home])
    ump  = rng.choice(UMPIRES)
    h_hand = rng.choice(["R", "R", "R", "L"])
    a_hand = rng.choice(["R", "R", "R", "L"])

    home_starter = rng.choice(STARTERS[h_hand])
    away_starter = rng.choice(STARTERS[a_hand])
    venue        = rng.choice(VENUES)

    # Simulate realistic open/close totals
    base_total = rng.gauss(9.1, 0.6)
    open_total = round(max(7.0, min(12.0, base_total)) * 2) / 2   # nearest 0.5
    close_total = open_total + rng.gauss(0, 0.12)
    close_total = round(close_total * 2) / 2

    # Simulate actual runs: correlated with total but with variance
    actual_runs = max(0, rng.gauss(base_total + rng.gauss(0, 0.3), 3.1))
    actual_runs = round(actual_runs)

    year = rng.choice([2022, 2023, 2024])
    month = rng.randint(4, 10)
    day   = rng.randint(1, 28)
    game_date = f"{year}-{month:02d}-{day:02d}"

    return {
        "game_id":             game_id,
        "date":                game_date,
        "home_team":           home,
        "away_team":           away,
        "umpire":              ump,
        "home_starter":        home_starter,
        "away_starter":        away_starter,
        "home_starter_hand":   h_hand,
        "away_starter_hand":   a_hand,
        "home_days_rest":      rng.choice([4, 4, 4, 5, 5, 3, 6]),
        "away_days_rest":      rng.choice([4, 4, 4, 5, 5, 3, 6]),
        "home_bp_era_7d":      round(rng.gauss(4.20, 0.80), 2),
        "away_bp_era_7d":      round(rng.gauss(4.20, 0.80), 2),
        "home_bp_ip_3d":       round(rng.gauss(5.0, 1.2), 1),
        "away_bp_ip_3d":       round(rng.gauss(5.0, 1.2), 1),
        "home_tz_change":      rng.choice([0, 0, 0, 1, -1, 2, -2]),
        "away_tz_change":      rng.choice([0, 0, 0, 1, -1, 2, -2]),
        "home_off_rating":     round(rng.gauss(100, 12)),
        "away_off_rating":     round(rng.gauss(100, 12)),
        "home_bp_highlev_yest": rng.random() < 0.20,
        "away_bp_highlev_yest": rng.random() < 0.20,
        "venue_name":          venue,
        "open_total":          open_total,
        "close_total":         close_total,
        "actual_runs":         actual_runs,
    }


def generate_synthetic_dataset(n: int = 500, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    return [_synthetic_game(rng, i) for i in range(n)]


def load_games(csv_path: Path | None = None) -> list[dict]:
    """
    Loads game rows. Uses real CSV if present, else generates synthetic data.
    """
    path = csv_path or DATA_FILE
    if path.exists():
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # coerce types
                for int_col in ["home_days_rest", "away_days_rest", "home_off_rating",
                                 "away_off_rating", "home_tz_change", "away_tz_change",
                                 "actual_runs"]:
                    row[int_col] = int(row.get(int_col, 0) or 0)
                for float_col in ["home_bp_era_7d", "away_bp_era_7d",
                                   "home_bp_ip_3d", "away_bp_ip_3d",
                                   "open_total", "close_total"]:
                    row[float_col] = float(row.get(float_col, 4.20) or 4.20)
                for bool_col in ["home_bp_highlev_yest", "away_bp_highlev_yest"]:
                    row[bool_col] = str(row.get(bool_col, "False")).lower() in ("1", "true", "yes")
                rows.append(row)
        return rows
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        games = generate_synthetic_dataset()
        # Persist for reproducibility
        if games:
            fieldnames = list(games[0].keys())
            with open(DATA_FILE, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(games)
        return games
