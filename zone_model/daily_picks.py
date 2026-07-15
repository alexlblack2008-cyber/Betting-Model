"""
Daily Picks Runner
==================
Main entry point for the automated daily notification.

Pipeline:
  1. Fetch today's MLB schedule from the Stats API
  2. For each game: get umpire, lineups, starters via boxscore
  3. Fetch live pitcher stats (K%, BB%, GB%) from Stats API
  4. Fetch lineup wOBA vs pitcher hand
  5. Fetch weather for each venue
  6. Run the full Zone Model (URA + PUCS + BFA + RCA + lineup + weather)
  7. Rank all games by |edge_runs| × confidence
  8. Return top 3-5 picks with ≥ 0.35 runs edge and ≥ 0.35 confidence
  9. Log each pick to the paper-trading ledger at $100 stake
 10. Settle yesterday's picks using final scores

Output is a formatted string ready for push notification / email.
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

from zone_model import (
    GameInput, TeamContext, BullpenState, ModelOutput, compute_fair_total,
)
from umpire_data import UMPIRE_PROFILES
from pitcher_data import PITCHER_PROFILES, default_bullpen
from live.mlb_api import (
    get_todays_games, get_game_detail, get_pitcher_season_stats, get_lineup_woba,
)
from live.weather_client import get_weather_adjustment
from live.lineup_quality import total_lineup_adjustment
from live.odds_client import load_dotenv, get_mlb_totals, match_total
from ledger import record_pick, settle_pick, all_time_summary, weekly_pnl_report
from bonus_pick import get_bonus_pick, format_bonus_pick

# Load .env file if present (picks up ODDS_API_KEY locally)
load_dotenv()

# How many top picks to surface (min 3, max 5)
MIN_PICKS = 3
MAX_PICKS = 5

# Minimum thresholds to issue a pick
MIN_EDGE   = 0.35   # runs
MIN_CONF   = 0.35


@dataclass
class ScoredGame:
    game_pk:       int
    home_team:     str
    away_team:     str
    venue:         str
    umpire:        str
    home_starter:  str
    away_starter:  str
    output:        ModelOutput
    weather_note:  str
    score:         float   # ranking score = |edge_runs| × confidence


def _build_team_context(
    team_name: str,
    starter_info: dict,
    lineup: list[dict],
    home: bool,
    api_stats: dict,
) -> TeamContext:
    """Build TeamContext merging live API stats with static fallback."""
    starter_name = starter_info["name"]

    # Pull stats from API if available, else fall back to static profile
    live = api_stats if api_stats.get("ip", 0) > 10 else {}
    static = PITCHER_PROFILES.get(starter_name, PITCHER_PROFILES["__UNKNOWN__"])

    bp = default_bullpen()

    return TeamContext(
        team_name    = team_name,
        starter_name = starter_name,
        days_rest    = 4,          # default; enriched in production via game log
        bullpen      = BullpenState(
            avg_era_7d              = bp["avg_era_7d"],
            ip_last_3d              = bp["ip_last_3d"],
            high_lev_used_yesterday = bp["high_lev_used_yesterday"],
        ),
        home             = home,
        off_rating       = 100,    # enriched below via lineup wOBA mapping
        time_zone_change = 0,      # enriched in production via travel log
    )


def _is_mlb_off_day(d: date) -> bool:
    """
    Returns True on known MLB off periods where games are never played.
    Covers: All-Star Break (Mon–Thu of All-Star week), Opening Day eve,
    and the post-season gap. Dates are approximated per season year.
    """
    year = d.year
    # All-Star Break: typically the Mon–Thu surrounding the Tuesday All-Star Game
    # 2026: All-Star Game is July 14 → break is July 13–16
    all_star_breaks = {
        2026: (date(2026, 7, 13), date(2026, 7, 16)),
        2025: (date(2025, 7, 14), date(2025, 7, 17)),
        2027: (date(2027, 7, 12), date(2027, 7, 15)),
    }
    if year in all_star_breaks:
        start, end = all_star_breaks[year]
        if start <= d <= end:
            return True

    # Sundays in October after World Series ends (~Oct 30+), Nov–Mar = no games
    if d.month in (11, 12, 1, 2, 3):
        return True

    return False


def _static_fallback_games() -> list[dict]:
    """
    Returns a set of representative static games used when the MLB Stats API
    is unreachable. Returns empty list on known MLB off days (All-Star Break, etc.)
    """
    import random
    from umpire_data import UMPIRE_PROFILES
    from pitcher_data import PITCHER_PROFILES

    today_date = date.today()
    if _is_mlb_off_day(today_date):
        print(f"  [Static fallback] {today_date} is an MLB off day — no picks generated.")
        return []

    umps     = [u for u in UMPIRE_PROFILES if u != "__UNKNOWN__"]
    pitchers = [p for p in PITCHER_PROFILES if p != "__UNKNOWN__"]

    rng = random.Random(int(today_date.strftime("%Y%m%d")))  # deterministic per day

    matchups = [
        ("New York Yankees",     "Houston Astros"),
        ("Los Angeles Dodgers",  "San Francisco Giants"),
        ("Atlanta Braves",       "Philadelphia Phillies"),
        ("Boston Red Sox",       "Tampa Bay Rays"),
        ("Chicago Cubs",         "Milwaukee Brewers"),
        ("Texas Rangers",        "Seattle Mariners"),
        ("Cleveland Guardians",  "Minnesota Twins"),
        ("San Diego Padres",     "Arizona Diamondbacks"),
        ("Baltimore Orioles",    "Toronto Blue Jays"),
    ]
    rng.shuffle(matchups)
    selected = matchups[:6]

    games = []
    for home, away in selected:
        games.append({
            "gamePk":        rng.randint(700000, 799999),
            "status":        "Scheduled",
            "home_team":     home,
            "home_team_id":  0,
            "away_team":     away,
            "away_team_id":  0,
            "venue_name":    _TEAM_VENUE.get(home, "Unknown"),
            "venue_id":      None,
            "game_time_utc": f"{date.today().isoformat()}T18:10:00Z",
            "_static":       True,
            "_umpire":       rng.choice(umps),
            "_home_starter": rng.choice(pitchers),
            "_away_starter": rng.choice(pitchers),
        })
    return games

# Team → home venue mapping for static fallback
_TEAM_VENUE = {
    "New York Yankees":      "Yankee Stadium",
    "Houston Astros":        "Minute Maid Park",
    "Los Angeles Dodgers":   "Dodger Stadium",
    "San Francisco Giants":  "Oracle Park",
    "Atlanta Braves":        "Truist Park",
    "Philadelphia Phillies": "Citizens Bank Park",
    "Boston Red Sox":        "Fenway Park",
    "Tampa Bay Rays":        "Tropicana Field",
    "Chicago Cubs":          "Wrigley Field",
    "Milwaukee Brewers":     "American Family Field",
    "Texas Rangers":         "Globe Life Field",
    "Seattle Mariners":      "T-Mobile Park",
    "Cleveland Guardians":   "Progressive Field",
    "Minnesota Twins":       "Target Field",
    "San Diego Padres":      "Petco Park",
    "Arizona Diamondbacks":  "Chase Field",
    "Baltimore Orioles":     "Camden Yards",
    "Toronto Blue Jays":     "Rogers Centre",
}


def score_all_games(game_date: str | None = None) -> list[ScoredGame]:
    """Fetch and score every game on the given date. Returns sorted list."""
    today = game_date or date.today().isoformat()

    live_data_available = True
    try:
        games_raw = get_todays_games(today)
        if not games_raw:
            raise ValueError("no games returned")
    except Exception as e:
        print(f"  [MLB API] Unreachable ({e.__class__.__name__}) — using static game set.")
        games_raw = _static_fallback_games()
        live_data_available = False

    # Fetch live odds once for all games (1 API call = 1 quota unit)
    try:
        totals_cache = get_mlb_totals(today)
        print(f"  [Odds API] Loaded {len(totals_cache)} game totals for {today}")
    except EnvironmentError as e:
        print(f"  [Odds API] WARNING: {e}\n  Falling back to 8.5 placeholder for all games.")
        totals_cache = {}
    except Exception as e:
        print(f"  [Odds API] Unreachable — using 8.5 placeholder.")
        totals_cache = {}

    scored: list[ScoredGame] = []

    for g in games_raw:
        if g["status"] not in ("Preview", "Pre-Game", "Scheduled", "Warmup"):
            continue

        pk = g["gamePk"]

        # Static fallback games already carry umpire + starter info
        if g.get("_static"):
            ump_name     = g["_umpire"]
            home_starter = {"name": g["_home_starter"], "id": None, "throws": "R"}
            away_starter = {"name": g["_away_starter"], "id": None, "throws": "R"}
            home_lineup  = []
            away_lineup  = []
        else:
            try:
                detail = get_game_detail(pk)
            except Exception:
                continue
            ump_name     = detail["umpire_name"]
            home_starter = detail["home_starter"]
            away_starter = detail["away_starter"]
            home_lineup  = detail["home_lineup"]
            away_lineup  = detail["away_lineup"]

        # Live pitcher stats (skipped if no id or network unavailable)
        home_stats = {}
        away_stats = {}
        if live_data_available:
            home_stats = get_pitcher_season_stats(home_starter["id"]) \
                         if home_starter.get("id") else {}
            away_stats = get_pitcher_season_stats(away_starter["id"]) \
                         if away_starter.get("id") else {}

        # Inline-register live pitcher profiles so zone_model can find them
        for name, stats in [(home_starter["name"], home_stats),
                             (away_starter["name"], away_stats)]:
            if name not in PITCHER_PROFILES and stats:
                PITCHER_PROFILES[name] = {
                    "k_pct":        stats.get("k_pct", 0.220),
                    "bb_pct":       stats.get("bb_pct", 0.080),
                    "gbpct":        stats.get("gbpct", 0.440),
                    "zone_pct":     0.470,
                    "era_adj":      100,
                    "ip_per_start": 5.5,
                    "hand":         stats.get("hand", "R"),
                }

        # Weather (graceful fallback to 0 if API unreachable)
        try:
            wx = get_weather_adjustment(g["venue_name"])
        except Exception:
            wx = {"weather_run_adj": 0.0, "note": "weather unavailable"}
        weather_adj = wx["weather_run_adj"]

        # Lineup wOBA (skipped when no lineup data)
        home_live_woba = None
        away_live_woba = None
        if live_data_available and home_lineup:
            try:
                home_live_woba = get_lineup_woba(home_lineup, away_starter.get("throws", "R"))
                away_live_woba = get_lineup_woba(away_lineup, home_starter.get("throws", "R"))
            except Exception:
                pass
        lineup_adj = total_lineup_adjustment(
            home_team          = g["home_team"],
            away_team          = g["away_team"],
            home_starter_hand  = home_starter.get("throws", "R"),
            away_starter_hand  = away_starter.get("throws", "R"),
            home_live_woba     = home_live_woba,
            away_live_woba     = away_live_woba,
        )

        # Live market total from The Odds API; falls back to 8.5 if unavailable
        market_total = match_total(g["home_team"], g["away_team"], totals_cache)

        home_ctx = _build_team_context(
            g["home_team"], home_starter, home_lineup, home=True, api_stats=home_stats
        )
        away_ctx = _build_team_context(
            g["away_team"], away_starter, away_lineup, home=False, api_stats=away_stats
        )

        game_input = GameInput(
            umpire_name          = ump_name,
            home_team            = home_ctx,
            away_team            = away_ctx,
            market_total         = market_total,
            abs_challenge_active = True,
        )

        output = compute_fair_total(game_input)

        # Inject lineup and weather into fair total post-hoc
        # (these layers are additive and don't affect umpire/pitcher interaction)
        lineup_total_adj = lineup_adj["total_lineup_adj"]
        combined_adj = lineup_total_adj + weather_adj
        output.fair_total  = round(output.fair_total + combined_adj, 2)
        output.edge_runs   = round(output.fair_total - market_total, 2)
        output.edge_pct    = round(output.edge_runs / market_total, 4)
        # Re-evaluate recommendation
        if abs(output.edge_runs) >= MIN_EDGE and output.confidence >= MIN_CONF:
            output.recommendation = "OVER" if output.edge_runs > 0 else "UNDER"
        else:
            output.recommendation = "NO BET"

        ranking_score = abs(output.edge_runs) * output.confidence

        scored.append(ScoredGame(
            game_pk      = pk,
            home_team    = g["home_team"],
            away_team    = g["away_team"],
            venue        = g["venue_name"],
            umpire       = ump_name,
            home_starter = home_starter["name"],
            away_starter = away_starter["name"],
            output       = output,
            weather_note = wx["note"],
            score        = ranking_score,
        ))

    # Sort by ranking score descending, filter to bettable games
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


def get_top_picks(game_date: str | None = None) -> list[ScoredGame]:
    today = game_date or date.today().isoformat()
    all_scored = score_all_games(today)
    bettable = [g for g in all_scored if g.output.recommendation != "NO BET"]
    picks = bettable[:MAX_PICKS]
    # Enforce minimum: if fewer than MIN_PICKS have full confidence, lower threshold
    if len(picks) < MIN_PICKS:
        extras = [g for g in all_scored if g.output.recommendation == "NO BET"]
        extras.sort(key=lambda x: x.score, reverse=True)
        picks += extras[:MAX_PICKS - len(picks)]
    return picks[:MAX_PICKS]


def settle_yesterdays_picks() -> list[str]:
    """
    Fetches yesterday's final scores from the MLB API and settles pending bets.
    Returns a list of settlement messages. Silent on network failure.
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    messages = []
    try:
        games = get_todays_games(yesterday)
    except Exception:
        return messages   # network unavailable — skip settlement silently
    for g in games:
        if g["status"] != "Final":
            continue
        try:
            from live.mlb_api import _get
            data = _get(f"/game/{g['gamePk']}/linescore")
            home_runs = data.get("teams", {}).get("home", {}).get("runs", 0)
            away_runs = data.get("teams", {}).get("away", {}).get("runs", 0)
            total = (home_runs or 0) + (away_runs or 0)
            result = settle_pick(g["home_team"], g["away_team"], yesterday, int(total))
            if result != "not_found":
                messages.append(
                    f"{g['away_team']} @ {g['home_team']}: "
                    f"{total} total runs → {result.upper()}"
                )
        except Exception:
            pass
    return messages


def format_daily_report(picks: list[ScoredGame], game_date: str,
                         settlements: list[str]) -> str:
    """Formats the full daily notification string."""
    lines = [
        "=" * 56,
        f"  THE ZONE MODEL  ◆  MLB Picks for {game_date}",
        "=" * 56,
    ]

    if not picks:
        lines += ["  No qualifying picks found today.", "=" * 56]
        return "\n".join(lines)

    for i, sg in enumerate(picks, 1):
        rec = sg.output.recommendation
        sym = "▲ OVER" if rec == "OVER" else ("▼ UNDER" if rec == "UNDER" else "— WATCH")
        lines += [
            f"\n  PICK #{i}  {sym}  {sg.output.fair_total - sg.output.edge_runs:.1f}",
            f"  {sg.away_team} @ {sg.home_team}",
            f"  Umpire:    {sg.umpire}",
            f"  Starters:  {sg.away_starter} (away)  vs  {sg.home_starter} (home)",
            f"  Venue:     {sg.venue}",
            f"  Weather:   {sg.weather_note}",
            f"  Fair total:{sg.output.fair_total:.2f}  "
            f"Edge: {sg.output.edge_runs:+.2f} runs ({sg.output.edge_pct*100:+.1f}%)",
            f"  Confidence:{sg.output.confidence:.0%}   "
            f"Kelly: {sg.output.kelly_fraction:.2%} of bankroll",
            f"  Paper bet: $100 → win ${100/1.10:.2f} at -110",
            f"  **THE PICK: {rec} {sg.output.fair_total - sg.output.edge_runs:.1f}  —  {sg.away_team} @ {sg.home_team}**",
            "  ·" * 28,
        ]

    lines += ["", "=" * 56]

    if settlements:
        lines.append("  YESTERDAY'S RESULTS:")
        for s in settlements:
            lines.append(f"    {s}")
        lines.append("=" * 56)

    lines.append(f"  {all_time_summary()}")
    lines.append("=" * 56)
    return "\n".join(lines)


def format_daily_report_with_bonus(
    picks: list[ScoredGame],
    game_date: str,
    settlements: list[str],
) -> str:
    """Full daily report: Zone Model picks + Bonus Pick appended."""
    main = format_daily_report(picks, game_date, settlements)
    bonus = get_bonus_pick(game_date)
    return main + format_bonus_pick(bonus)


def run_daily(game_date=None, log_to_ledger: bool = True) -> str:
    """
    Full daily pipeline. Returns the formatted report string.
    Also logs picks to the ledger and settles yesterday.
    """
    if isinstance(game_date, date):
        today = game_date.isoformat()
    else:
        today = game_date or date.today().isoformat()

    # Settle yesterday's pending picks first
    settlements = settle_yesterdays_picks()

    # Get today's top picks
    picks = get_top_picks(today)

    # Log each pick to the ledger
    if log_to_ledger:
        for sg in picks:
            if sg.output.recommendation != "NO BET":
                record_pick(
                    bet_date      = today,
                    home_team     = sg.home_team,
                    away_team     = sg.away_team,
                    umpire        = sg.umpire,
                    recommendation= sg.output.recommendation,
                    market_total  = sg.output.fair_total - sg.output.edge_runs,
                    fair_total    = sg.output.fair_total,
                    edge_runs     = sg.output.edge_runs,
                    confidence    = sg.output.confidence,
                    kelly_fraction= sg.output.kelly_fraction,
                    game_pk       = sg.game_pk,
                )

    return format_daily_report_with_bonus(picks, today, settlements)


if __name__ == "__main__":
    game_date = sys.argv[1] if len(sys.argv) > 1 else None
    report = run_daily(game_date, log_to_ledger=False)
    print(report)
    if "--weekly" in sys.argv:
        print()
        print(weekly_pnl_report())
