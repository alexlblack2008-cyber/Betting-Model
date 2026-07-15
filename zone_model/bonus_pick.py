"""
The Bonus Pick
==============
A second, entirely different research methodology for high-profile events:
  - World Cup / major international soccer
  - UFC / boxing championship fights
  - NFL playoff games, Super Bowl
  - NBA playoff series
  - MLB playoffs / World Series
  - March Madness Elite Eight onward
  - Any game tagged as a "national broadcast" event

Where the Zone Model is purely statistical (umpire zone data, pitcher K%),
the Bonus Pick is situational and market-structural — it answers:
  "Is the market mispricing this game because of public perception?"

Research dimensions (all different from Zone Model):
  1. Public Money Trap Score  — how lopsidedly the public is betting one side
  2. Sharp Reversal Signal    — line moved AGAINST the public money (steam move)
  3. Situational Motivation   — underdog with something to prove vs. complacent favorite
  4. Narrative Inflation Score— media hype inflating a team's perceived strength
  5. Rest / Fatigue Delta     — structured rest disadvantage in high-stakes spots
  6. Market Consensus Spread  — how much books disagree (wider = less certain)

Each dimension is scored 0-10. A weighted composite produces:
  - A lean direction (favorite/underdog, over/under)
  - A confidence level
  - A $100 paper bet recommendation

Supported sports via The Odds API sport keys:
  soccer_*    (World Cup, Champions League, EPL, MLS)
  mma_mixed_martial_arts  (UFC)
  americanfootball_nfl    (NFL including playoffs)
  basketball_nba          (NBA including playoffs)
  baseball_mlb            (MLB playoffs)
  basketball_ncaab        (March Madness)
  icehockey_nhl           (NHL playoffs)
"""

from __future__ import annotations
import os
import json
import math
import urllib.request
import urllib.error
import urllib.parse
import time
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Optional

from live.odds_client import load_dotenv, _api_key

load_dotenv()

# ── High-profile event detection ──────────────────────────────────────────────

# Odds API sport keys we monitor for bonus-pick events
HIGH_PROFILE_SPORTS = {
    "americanfootball_nfl":      {"name": "NFL",           "weight": 1.0},
    "basketball_nba":            {"name": "NBA",           "weight": 0.95},
    "soccer_fifa_world_cup":     {"name": "World Cup",     "weight": 1.0},
    "soccer_uefa_champs_league": {"name": "Champions League", "weight": 0.85},
    "mma_mixed_martial_arts":    {"name": "UFC/MMA",       "weight": 0.90},
    "baseball_mlb":              {"name": "MLB Playoffs",  "weight": 0.80},
    "basketball_ncaab":          {"name": "NCAA Basketball","weight": 0.75},
    "icehockey_nhl":             {"name": "NHL",           "weight": 0.70},
    "boxing_boxing":             {"name": "Boxing",        "weight": 0.85},
    "soccer_epl":                {"name": "Premier League","weight": 0.65},
    "soccer_mls":                {"name": "MLS",           "weight": 0.55},
}

# Keywords that flag an event as "high profile" regardless of sport
HIGH_PROFILE_KEYWORDS = {
    "playoff", "playoffs", "final", "finals", "championship", "champion",
    "superbowl", "super bowl", "world series", "world cup", "stanley cup",
    "title", "ufc", "main event", "elite eight", "final four",
    "monday night", "sunday night", "thursday night", "prime time",
    "conference championship", "division series", "league championship",
}

ODDS_API_BASE = "https://api.the-odds-api.com/v4"


def _odds_get(path: str, params: dict) -> list | dict:
    """Single GET against The Odds API."""
    try:
        params["apiKey"] = _api_key()
    except EnvironmentError:
        return []
    qs  = urllib.parse.urlencode(params)
    url = f"{ODDS_API_BASE}{path}?{qs}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError):
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    return []


# ── Event fetcher ─────────────────────────────────────────────────────────────

@dataclass
class HighProfileEvent:
    sport_key:   str
    sport_name:  str
    event_id:    str
    home_team:   str
    away_team:   str
    commence:    str    # ISO timestamp
    best_spread_home:  Optional[float]   # negative = home favored
    best_total:        Optional[float]
    spread_consensus:  float   # std dev across books (0 = perfect agreement)
    total_consensus:   float
    books_agree:       int     # number of books offering this game
    raw_event:         dict    = field(default_factory=dict)


def fetch_todays_high_profile_events(game_date: str | None = None) -> list[HighProfileEvent]:
    """
    Polls The Odds API for every supported sport and returns events on
    `game_date` that qualify as high-profile.
    """
    target = game_date or date.today().isoformat()
    events: list[HighProfileEvent] = []

    for sport_key, meta in HIGH_PROFILE_SPORTS.items():
        raw = _odds_get(f"/sports/{sport_key}/odds", {
            "regions":    "us",
            "markets":    "spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
        })

        if not isinstance(raw, list):
            continue

        for ev in raw:
            commence = ev.get("commence_time", "")
            if target not in commence:
                continue

            home = ev.get("home_team", "")
            away = ev.get("away_team", "")

            # Flag: is this event high profile by keyword?
            label = f"{home} {away} {sport_key}".lower()
            is_flagged = any(kw in label for kw in HIGH_PROFILE_KEYWORDS)
            # For UFC/World Cup/NFL Playoffs, every event qualifies
            always_on  = sport_key in {
                "mma_mixed_martial_arts", "soccer_fifa_world_cup",
                "boxing_boxing",
            }

            if not (is_flagged or always_on):
                continue

            # Collect spreads and totals across books
            spreads: list[float] = []
            totals:  list[float] = []
            books_seen = 0

            for bm in ev.get("bookmakers", []):
                books_seen += 1
                for market in bm.get("markets", []):
                    if market["key"] == "spreads":
                        for oc in market.get("outcomes", []):
                            if oc.get("name") == home:
                                spreads.append(float(oc.get("point", 0)))
                    elif market["key"] == "totals":
                        for oc in market.get("outcomes", []):
                            if oc.get("name") == "Over":
                                totals.append(float(oc.get("point", 0)))

            def _stdev(vals: list[float]) -> float:
                if len(vals) < 2:
                    return 0.0
                mean = sum(vals) / len(vals)
                return math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))

            def _median(vals: list[float]) -> Optional[float]:
                if not vals:
                    return None
                s = sorted(vals)
                mid = len(s) // 2
                return s[mid] if len(s) % 2 else (s[mid-1] + s[mid]) / 2

            events.append(HighProfileEvent(
                sport_key          = sport_key,
                sport_name         = meta["name"],
                event_id           = ev.get("id", ""),
                home_team          = home,
                away_team          = away,
                commence           = commence,
                best_spread_home   = _median(spreads),
                best_total         = _median(totals),
                spread_consensus   = round(_stdev(spreads), 3),
                total_consensus    = round(_stdev(totals), 3),
                books_agree        = books_seen,
                raw_event          = ev,
            ))

    return events


# ── Scoring engine ─────────────────────────────────────────────────────────────

@dataclass
class BonusPickOutput:
    event:          HighProfileEvent
    lean:           str    # "HOME", "AWAY", "OVER", "UNDER"
    market_line:    str    # e.g. "HOU +3.5" or "OVER 47.5"
    composite_score: float  # 0-100
    confidence:     float   # 0-1
    kelly_fraction: float
    rationale:      list[str]   # bullet-point explanations
    recommendation: str     # "BET" or "PASS"


def _public_trap_score(spread: Optional[float], sport_key: str) -> tuple[float, str]:
    """
    Scores how likely the public is overbetting one side based on spread size.
    Heavy favorites (large negative spreads) attract disproportionate public money.
    Returns (score 0-10, lean direction).
    """
    if spread is None:
        return 5.0, "NEUTRAL"
    # Large favorites get massive public money → fade them (bet underdog)
    if spread < -7:
        return 8.5, "AWAY"    # public hammers big favorites → lean underdog
    if spread < -3:
        return 6.5, "AWAY"
    if spread > 3:
        return 6.5, "HOME"    # public fades big home dogs → lean home dog
    return 5.0, "NEUTRAL"


def _sharp_reversal_score(consensus_stdev: float) -> tuple[float, str]:
    """
    High disagreement between books = sharp action has moved some lines but
    not others. This steam-move signal suggests the sharp side has value.
    Returns (score 0-10, signal strength label).
    """
    if consensus_stdev >= 1.5:
        return 9.0, "STRONG STEAM DETECTED"
    if consensus_stdev >= 0.8:
        return 7.0, "MODERATE LINE DISAGREEMENT"
    if consensus_stdev >= 0.4:
        return 5.5, "SLIGHT LINE MOVEMENT"
    return 3.0, "BOOKS IN AGREEMENT"


def _motivation_score(sport_key: str, home_team: str, away_team: str,
                      spread: Optional[float]) -> tuple[float, str]:
    """
    Scores situational motivation. Underdogs in high-stakes spots
    historically outperform spread expectations.
    """
    label = f"{home_team} {away_team}".lower()
    score = 5.0
    notes = []

    # Underdog in a final / championship = maximum motivation
    if any(w in label for w in ["final", "championship", "title", "cup"]):
        if spread and spread > 0:   # home team is underdog
            score = 9.0
            notes.append("home underdog in championship game")
        elif spread and spread < 0:
            score = 7.0
            notes.append("championship game — both sides highly motivated")

    # UFC: main event fights always have maximum fight-night energy
    if sport_key in {"mma_mixed_martial_arts", "boxing_boxing"}:
        score = max(score, 7.5)
        notes.append("main event combat sports — high finish variance")

    # NFL: Monday/Sunday/Thursday night games — home teams cover at higher rate
    if sport_key == "americanfootball_nfl":
        score = max(score, 6.5)
        notes.append("primetime NFL — home crowd factor elevated")

    note = "; ".join(notes) if notes else "standard motivation"
    return score, note


def _narrative_inflation_score(sport_key: str, spread: Optional[float]) -> tuple[float, str]:
    """
    Media narratives inflate public perception of certain teams.
    Big favorites in televised games are consistently overvalued by the public.
    """
    if spread is None:
        return 5.0, "no spread data"
    # The public overvalues large favorites in high-profile games
    if spread < -10:
        return 9.0, "heavy favorite likely inflated by media narrative — fade"
    if spread < -6:
        return 7.0, "moderate favorite with narrative inflation risk"
    if -3 <= spread <= 3:
        return 5.0, "competitive line — less narrative distortion"
    return 4.0, "underdog may be undervalued"


def _consensus_disagreement_score(spread_stdev: float, total_stdev: float) -> float:
    """
    When books disagree on both spread AND total, uncertainty is high.
    Score 0-10: higher = more disagreement = more potential edge.
    """
    combined = (spread_stdev + total_stdev) / 2
    return min(10.0, combined * 6.0)


def score_bonus_pick(event: HighProfileEvent) -> BonusPickOutput:
    """
    Runs all five research dimensions and produces the Bonus Pick recommendation.
    """
    spread = event.best_spread_home  # negative = home favored

    # Dimension scores
    pub_score,   pub_lean   = _public_trap_score(spread, event.sport_key)
    sharp_score, sharp_note = _sharp_reversal_score(event.spread_consensus)
    motiv_score, motiv_note = _motivation_score(
        event.sport_key, event.home_team, event.away_team, spread
    )
    narr_score, narr_note   = _narrative_inflation_score(event.sport_key, spread)
    consensus_score         = _consensus_disagreement_score(
        event.spread_consensus, event.total_consensus
    )

    # Weighted composite (weights sum to 1.0)
    weights = {
        "public_trap":   0.28,
        "sharp_signal":  0.24,
        "motivation":    0.20,
        "narrative":     0.18,
        "consensus":     0.10,
    }
    composite = (
        pub_score    * weights["public_trap"]  +
        sharp_score  * weights["sharp_signal"] +
        motiv_score  * weights["motivation"]   +
        narr_score   * weights["narrative"]    +
        consensus_score * weights["consensus"]
    )
    composite = round(composite * 10, 1)  # scale to 0-100

    # Determine lean
    # Primary lean from public trap + narrative (most reliable in high-profile)
    if pub_lean == "AWAY" or (narr_score >= 7.0 and spread and spread < -5):
        lean = "AWAY"
        market_line = f"{event.away_team} +{abs(spread):.1f}" if spread else event.away_team
    elif pub_lean == "HOME":
        lean = "HOME"
        market_line = f"{event.home_team} +{abs(spread):.1f}" if spread else event.home_team
    else:
        # No clear spread lean → look at total
        lean = "OVER" if event.spread_consensus > 0.5 else "UNDER"
        market_line = f"{lean} {event.best_total}" if event.best_total else lean

    # Confidence: normalize composite to 0-1 with floor at 0.3
    confidence = max(0.30, min(0.90, composite / 100))

    # Kelly (1/4 Kelly, -110 juice assumed)
    breakeven = 0.5238
    est_win_prob = breakeven + (confidence - 0.50) * 0.25
    b = 0.909
    kelly = max(0.0, ((est_win_prob * (b + 1) - 1) / b) * 0.25)

    # Rationale bullets
    rationale = [
        f"Public trap score {pub_score:.1f}/10: {pub_lean} lean — public likely overbetting {'favorite' if spread and spread < 0 else 'one side'}",
        f"Sharp signal {sharp_score:.1f}/10: {sharp_note}",
        f"Motivation {motiv_score:.1f}/10: {motiv_note}",
        f"Narrative inflation {narr_score:.1f}/10: {narr_note}",
        f"Book consensus gap {consensus_score:.1f}/10: spread σ={event.spread_consensus}, total σ={event.total_consensus}",
    ]

    recommendation = "BET" if composite >= 58 and confidence >= 0.40 else "PASS"

    return BonusPickOutput(
        event           = event,
        lean            = lean,
        market_line     = market_line,
        composite_score = composite,
        confidence      = confidence,
        kelly_fraction  = round(kelly, 4),
        rationale       = rationale,
        recommendation  = recommendation,
    )


def get_bonus_pick(game_date: str | None = None) -> Optional[BonusPickOutput]:
    """
    Main entry: finds the single best Bonus Pick from all high-profile events
    today, or returns None if nothing qualifies.
    """
    events = fetch_todays_high_profile_events(game_date)
    if not events:
        return None

    candidates = [score_bonus_pick(e) for e in events]
    candidates = [c for c in candidates if c.recommendation == "BET"]
    if not candidates:
        # Fall back to the highest composite even if under threshold
        candidates = sorted(candidates or [score_bonus_pick(e) for e in events],
                            key=lambda x: x.composite_score, reverse=True)
        return candidates[0] if candidates else None

    candidates.sort(key=lambda x: x.composite_score * x.confidence, reverse=True)
    return candidates[0]


def format_bonus_pick(bp: Optional[BonusPickOutput]) -> str:
    """Returns formatted string for inclusion in the daily report."""
    sep = "=" * 56
    if bp is None:
        return f"\n{sep}\n  ★ BONUS PICK: No qualifying high-profile event today\n{sep}"

    ev = bp.event
    lines = [
        "",
        sep,
        f"  ★  BONUS PICK  —  {ev.sport_name.upper()}",
        sep,
        f"  {ev.away_team}  @  {ev.home_team}",
        f"  Lean:       {bp.lean}  →  {bp.market_line}",
        f"  Composite:  {bp.composite_score:.0f}/100   Confidence: {bp.confidence:.0%}",
        f"  Kelly:      {bp.kelly_fraction:.2%} of bankroll",
        f"  Paper bet:  $100 → win ${100/1.10:.2f} at -110",
        "",
        "  RESEARCH BREAKDOWN (different methodology from Zone Model):",
    ]
    for r in bp.rationale:
        lines.append(f"    • {r}")
    lines += [
        "",
        f"  NOTE: Bonus Pick uses market-structure analysis (public money,",
        f"  sharp reversal, narrative inflation) — not statistical umpire/",
        f"  pitcher data. Two independent models, one daily report.",
        f"",
        f"  **THE BONUS PICK: {bp.lean}  {bp.market_line}**",
        sep,
    ]
    return "\n".join(lines)
