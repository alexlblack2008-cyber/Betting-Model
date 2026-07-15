"""
The Zone Model
==============
MLB Totals Betting via Umpire-Pitcher Context Analysis

Research basis:
  - MLB umpires produce the most measurable officiating impact in pro sports
  - Each ump's zone size shifts expected run totals by up to ±0.8 runs
  - Assignments are announced 1-2 days pre-game: a late-information edge
  - The K/BB interaction between umpire zone and pitcher style is non-linear
    and underweighted by market prices

Pipeline:
  1. Compute Umpire Run Adjustment (URA) from historical zone data
  2. Compute Pitcher-Umpire Compatibility Score (PUCS) for each starter
  3. Apply Bullpen Fatigue Adjustment (BFA)
  4. Apply Rest/Travel Context Adjustment (RCA)
  5. Produce a "fair total" and compare to market line
  6. Size the bet via fractional Kelly Criterion
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from umpire_data import UMPIRE_PROFILES, LEAGUE_AVG
from pitcher_data import PITCHER_PROFILES, default_bullpen
from abs_challenge import abs_adjusted_umpire_profile


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class BullpenState:
    avg_era_7d: float = 4.20
    ip_last_3d: float = 5.5
    high_lev_used_yesterday: bool = False


@dataclass
class TeamContext:
    """Everything about one side of the matchup beyond the pitcher."""
    team_name: str
    starter_name: str
    days_rest: int = 4           # days since starter's last outing
    bullpen: BullpenState = field(default_factory=BullpenState)
    home: bool = False
    off_rating: float = 100.0    # team offensive wRC+ (100 = league avg)
    time_zone_change: int = 0    # tz hours crossed since last game (negative = westward)


@dataclass
class GameInput:
    """Full input spec for one game."""
    umpire_name: str
    home_team: TeamContext
    away_team: TeamContext
    market_total: float          # posted over/under
    abs_challenge_active: bool = True  # True for 2026 MLB season


@dataclass
class ModelOutput:
    fair_total: float
    edge_runs: float             # fair_total - market_total (positive → lean OVER)
    edge_pct: float              # edge expressed as percentage of market total
    recommendation: str          # "OVER", "UNDER", or "NO BET"
    confidence: float            # 0-1 scale
    kelly_fraction: float        # suggested fraction of bankroll
    breakdown: dict              # diagnostic detail for each adjustment


# ---------------------------------------------------------------------------
# Step 1 – Umpire Run Adjustment (URA)
# ---------------------------------------------------------------------------

def umpire_run_adjustment(ump_name: str) -> tuple[float, float]:
    """
    Returns (run_adjustment, confidence_weight).

    run_adjustment: expected total runs change vs league average
                    (negative = fewer runs, lean UNDER)
    confidence_weight: shrinks toward 0 if sample is small
    """
    # NOTE: abs_active is passed via module-level flag set in compute_fair_total
    raw_profile = UMPIRE_PROFILES.get(ump_name, UMPIRE_PROFILES["__UNKNOWN__"])
    profile = abs_adjusted_umpire_profile(raw_profile, abs_active=_ABS_ACTIVE)

    run_adj = profile["run_impact"] * 2  # impact applies to both teams' pitchers

    # Confidence: logistic curve, full confidence above 300 games
    games = profile["games"]
    if games == 0:
        confidence = 0.0
    else:
        confidence = 1.0 / (1.0 + math.exp(-0.015 * (games - 200)))

    return run_adj, confidence


# ---------------------------------------------------------------------------
# Step 2 – Pitcher-Umpire Compatibility Score (PUCS)
# ---------------------------------------------------------------------------

def pitcher_umpire_score(pitcher_name: str, ump_name: str) -> float:
    """
    Returns a run adjustment from one pitcher's interaction with the umpire.

    Logic:
      - High-K pitchers benefit more from big zones (more called strikes, fewer walks)
      - Wild pitchers are most volatile: big zone helps them, tight zone kills them
      - Ground-ball specialists are less sensitive to zone size

    Returns signed run adjustment for THIS PITCHER'S HALF of the total.
    Positive = more runs allowed by this pitcher (trend OVER for this half).
    """
    pitcher = PITCHER_PROFILES.get(pitcher_name, PITCHER_PROFILES["__UNKNOWN__"])
    ump = UMPIRE_PROFILES.get(ump_name, UMPIRE_PROFILES["__UNKNOWN__"])

    csraa = ump["csraa"]        # positive = bigger zone
    k_pct = pitcher["k_pct"]
    bb_pct = pitcher["bb_pct"]
    gbpct = pitcher["gbpct"]

    # Sensitivity of a pitcher to zone size:
    # - High K% pitchers gain/lose more with zone changes (leverage ≈ k_pct * 8)
    # - High BB% pitchers are penalized more by a tight zone (leverage ≈ bb_pct * 12)
    # - High GB% pitchers are somewhat zone-insensitive
    k_sensitivity = k_pct * 8.0
    bb_sensitivity = bb_pct * 12.0
    gb_damper = 1.0 - (gbpct - 0.44) * 0.8   # shrink effect for extreme GBers

    # Net effect: big zone (positive csraa) → more Ks, fewer BBs → fewer runs
    # We express this as "runs allowed adjustment" (negative = pitcher allows fewer)
    k_component  = -csraa * k_sensitivity * 0.04   # zone → K rate → runs
    bb_component = +csraa * bb_sensitivity * 0.03  # zone → BB rate → runs (inverse)

    raw_adj = (k_component + bb_component) * gb_damper

    # Regress toward zero for extreme values (model humility)
    raw_adj = max(min(raw_adj, 0.8), -0.8)
    return raw_adj


# ---------------------------------------------------------------------------
# Step 3 – Bullpen Fatigue Adjustment (BFA)
# ---------------------------------------------------------------------------

def bullpen_fatigue_adjustment(bp: BullpenState) -> float:
    """
    Returns run adjustment (positive = more runs) based on bullpen wear.

    The starter usually only goes 5-6 innings; bullpen quality in the
    last 3-5 innings matters enormously for totals.
    """
    adj = 0.0

    # ERA drift: each 1.0 above league average (4.20) adds ~0.07 runs to expected total
    era_delta = bp.avg_era_7d - LEAGUE_AVG["runs_per_game_per_team"] * 0.95
    adj += era_delta * 0.07

    # Overuse: heavy innings in last 3 days degrades performance
    # League average is ~5.0 IP across the bullpen per 3 days
    ip_overuse = max(0, bp.ip_last_3d - 5.0)
    adj += ip_overuse * 0.06

    # If high-leverage arms were used yesterday: closer / setup likely unavailable
    if bp.high_lev_used_yesterday:
        adj += 0.18

    return adj


# ---------------------------------------------------------------------------
# Step 4 – Rest / Travel Context Adjustment (RCA)
# ---------------------------------------------------------------------------

def rest_travel_adjustment(ctx: TeamContext) -> float:
    """
    Returns a scoring rate adjustment for this team based on schedule context.
    Positive = team expected to score more (or allow more if pitcher is depleted).

    Key factors:
      - Extra rest boosts starter effectiveness (fewer runs allowed)
      - Eastward travel shifts are more fatiguing than westward
      - Short rest for the starter is a major risk factor
    """
    adj = 0.0

    # Starter rest
    rest = ctx.days_rest
    if rest <= 3:
        adj += 0.22    # short rest → worse performance → more runs
    elif rest == 4:
        adj += 0.0     # normal
    elif rest == 5:
        adj -= 0.05    # slight edge: extra prep
    elif rest >= 6:
        adj -= 0.09    # long rest can cut both ways; modest benefit

    # Time zone fatigue (eastward travel is harder: body clock runs late)
    tz = ctx.time_zone_change
    if tz > 0:         # traveled east
        adj += tz * 0.04
    elif tz < 0:       # traveled west (easier physiologically)
        adj += abs(tz) * 0.01

    # Offensive rating context
    # Teams with wRC+ above 110 or below 90 deviate meaningfully from average
    off_delta = (ctx.off_rating - 100) / 100
    adj -= off_delta * 0.12   # better offense = more runs scored (subtract = they score more)
                               # We invert: adj here models TOTAL runs, a better offense
                               # increases the total. We return team-scored runs contribution.
    return adj


# ---------------------------------------------------------------------------
# Step 5 – Fair Total Calculator
# ---------------------------------------------------------------------------

# Module-level flag so sub-functions (umpire_run_adjustment, pitcher_umpire_score)
# can read ABS state without needing it threaded through every signature.
_ABS_ACTIVE: bool = True


def compute_fair_total(game: GameInput) -> ModelOutput:
    """
    Combines all adjustments into a fair total and trading recommendation.
    """
    global _ABS_ACTIVE
    _ABS_ACTIVE = game.abs_challenge_active

    league_avg_total = LEAGUE_AVG["total_avg"]  # 9.1

    # --- Umpire layer ---
    ura, ump_confidence = umpire_run_adjustment(game.umpire_name)

    # --- Pitcher-umpire compatibility (both starters) ---
    home_pucs = pitcher_umpire_score(game.home_team.starter_name, game.umpire_name)
    away_pucs = pitcher_umpire_score(game.away_team.starter_name, game.umpire_name)
    total_pucs = home_pucs + away_pucs  # combined pitcher effect on total

    # --- Bullpen fatigue (both sides) ---
    home_bfa = bullpen_fatigue_adjustment(game.home_team.bullpen)
    away_bfa = bullpen_fatigue_adjustment(game.away_team.bullpen)
    total_bfa = home_bfa + away_bfa

    # --- Rest/travel context (scored as impact on total runs) ---
    # RCA from home team affects how many runs HOME allows (away scoring)
    # and vice versa; we sum contributions to total
    home_rca = rest_travel_adjustment(game.home_team)
    away_rca = rest_travel_adjustment(game.away_team)
    total_rca = home_rca + away_rca

    # --- Fair total assembly ---
    # Start from league average, apply each layer
    # URA scaled by umpire confidence (shrinks to 0 for unknown umps)
    adjusted_total = (
        league_avg_total
        + ura * ump_confidence
        + total_pucs * ump_confidence    # PUCS is only meaningful when ump is known
        + total_bfa
        + total_rca
    )

    edge_runs = adjusted_total - game.market_total
    edge_pct = edge_runs / game.market_total

    # --- Confidence composite ---
    # Weighted layers: ump + pitcher carry real signal even in static mode;
    # bullpen and rest/travel are bonuses when live data is available.
    # Each layer contributes a 0-1 score; weights sum to 1.0.
    ump_score   = min(1.0, abs(ura) / 0.30)          # weight 0.40 — primary edge
    pucs_score  = min(1.0, abs(total_pucs) / 0.20)   # weight 0.35 — pitcher fit
    bfa_score   = min(1.0, abs(total_bfa) / 0.30)    # weight 0.15 — fatigue
    rca_score   = min(1.0, abs(total_rca) / 0.20)    # weight 0.10 — rest/travel

    weighted_signal = (
        0.40 * ump_score +
        0.35 * pucs_score +
        0.15 * bfa_score +
        0.10 * rca_score
    )
    raw_confidence = weighted_signal * ump_confidence

    # --- Recommendation thresholds ---
    # We require at least 0.35 runs of edge and 0.35 confidence to bet
    MIN_EDGE_RUNS = 0.35
    MIN_CONFIDENCE = 0.35

    if abs(edge_runs) >= MIN_EDGE_RUNS and raw_confidence >= MIN_CONFIDENCE:
        recommendation = "OVER" if edge_runs > 0 else "UNDER"
    else:
        recommendation = "NO BET"

    # --- Kelly Criterion (fractional, 1/4 Kelly for safety) ---
    # Convert edge % to implied probability edge then Kelly
    # For a -110 line (most totals): breakeven win rate = 52.38%
    breakeven_rate = 0.5238
    juice = 0.0909  # implied vig on standard -110 line

    # Rough win probability from edge: each 0.5 runs of edge ≈ +3-4% win prob
    estimated_win_prob = breakeven_rate + (edge_runs / 0.5) * 0.035
    estimated_win_prob = max(0.0, min(1.0, estimated_win_prob))

    b = 1.0 / (1.0 + juice)  # net odds (win $1 / risk $1.10 → b ≈ 0.909)
    kelly_num = estimated_win_prob * (b + 1) - 1
    kelly_den = b
    full_kelly = kelly_num / kelly_den if kelly_den != 0 else 0.0
    fractional_kelly = max(0.0, full_kelly * 0.25)  # 1/4 Kelly

    return ModelOutput(
        fair_total=round(adjusted_total, 2),
        edge_runs=round(edge_runs, 2),
        edge_pct=round(edge_pct, 4),
        recommendation=recommendation,
        confidence=round(raw_confidence, 3),
        kelly_fraction=round(fractional_kelly, 4),
        breakdown={
            "league_avg_total": league_avg_total,
            "umpire_run_adj":   round(ura * ump_confidence, 3),
            "ump_confidence":   round(ump_confidence, 3),
            "home_pitcher_pucs": round(home_pucs, 3),
            "away_pitcher_pucs": round(away_pucs, 3),
            "home_bullpen_adj": round(home_bfa, 3),
            "away_bullpen_adj": round(away_bfa, 3),
            "home_rest_travel_adj": round(home_rca, 3),
            "away_rest_travel_adj": round(away_rca, 3),
        },
    )


# ---------------------------------------------------------------------------
# Step 6 – Pretty-print report
# ---------------------------------------------------------------------------

def print_report(game: GameInput, result: ModelOutput) -> None:
    width = 60
    sep = "─" * width

    print(f"\n{'THE ZONE MODEL':^{width}}")
    print(sep)
    print(f"  Home: {game.home_team.team_name:20s}  Starter: {game.home_team.starter_name}")
    print(f"  Away: {game.away_team.team_name:20s}  Starter: {game.away_team.starter_name}")
    print(f"  Umpire: {game.umpire_name}")
    print(f"  Market Total: {game.market_total}")
    print(sep)
    print(f"  {'ADJUSTMENT BREAKDOWN':}")
    for k, v in result.breakdown.items():
        print(f"    {k:<28s}: {v:+.3f}")
    print(sep)
    print(f"  Fair Total:       {result.fair_total:.2f}")
    print(f"  Edge (runs):      {result.edge_runs:+.2f}")
    print(f"  Edge (%):         {result.edge_pct*100:+.2f}%")
    print(f"  Confidence:       {result.confidence:.1%}")
    print(sep)
    if result.recommendation == "NO BET":
        print(f"  RECOMMENDATION:   ✗  NO BET  (edge or confidence too thin)")
    else:
        print(f"  RECOMMENDATION:   ➤  {result.recommendation}")
        print(f"  Kelly fraction:   {result.kelly_fraction:.2%} of bankroll")
    print(sep)
