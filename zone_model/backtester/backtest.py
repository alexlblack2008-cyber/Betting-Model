"""
Historical backtester for The Zone Model.

For each historical game:
  1. Run the full Zone Model pipeline using closing line as market_total
  2. Record: fair_total, edge_runs, recommendation, actual_runs, result
  3. Simulate a $100 paper bet on all recommended games
  4. Compute: win rate, ROI, CLV vs. open line, CLV vs. close line

CLV (Closing Line Value): if the model recommended OVER at open total of 8.5
and the game closed at 9.0, the model "beat the close" by +0.5 — this is
a strong signal of long-run edge even independent of outcome.

Run with:  python backtest.py
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from zone_model import (
    GameInput, TeamContext, BullpenState, compute_fair_total,
)
from backtester.historical_data import load_games

import statistics
from dataclasses import dataclass, field
from typing import List


STAKE = 100.0       # paper-bet stake per pick
JUICE = -110        # standard over/under juice
PAYOUT = STAKE / 1.10  # net profit on a winning -110 bet


@dataclass
class BetResult:
    game_id:        int
    date:           str
    home_team:      str
    away_team:      str
    umpire:         str
    recommendation: str     # OVER / UNDER / NO BET
    fair_total:     float
    open_total:     float
    close_total:    float
    actual_runs:    int
    edge_runs:      float
    confidence:     float
    kelly_fraction: float
    # Outcome (None if NO BET)
    bet_placed:     bool = False
    won:            bool | None = None
    pnl:            float = 0.0
    # CLV
    clv_vs_open:    float = 0.0   # positive = we beat the opening line
    clv_vs_close:   float = 0.0   # positive = we beat the closing line


def _determine_outcome(rec: str, actual_runs: int, market_total: float) -> bool | None:
    """Returns True (win), False (loss), or None (push)."""
    if rec == "OVER":
        if actual_runs > market_total:  return True
        if actual_runs < market_total:  return False
        return None  # push
    elif rec == "UNDER":
        if actual_runs < market_total:  return True
        if actual_runs > market_total:  return False
        return None
    return None


def run_backtest(abs_active: bool = True) -> List[BetResult]:
    games = load_games()
    results: List[BetResult] = []

    for g in games:
        home_ctx = TeamContext(
            team_name    = g["home_team"],
            starter_name = g["home_starter"],
            days_rest    = g["home_days_rest"],
            bullpen      = BullpenState(
                avg_era_7d              = g["home_bp_era_7d"],
                ip_last_3d              = g["home_bp_ip_3d"],
                high_lev_used_yesterday = g["home_bp_highlev_yest"],
            ),
            home             = True,
            off_rating       = g["home_off_rating"],
            time_zone_change = g["home_tz_change"],
        )
        away_ctx = TeamContext(
            team_name    = g["away_team"],
            starter_name = g["away_starter"],
            days_rest    = g["away_days_rest"],
            bullpen      = BullpenState(
                avg_era_7d              = g["away_bp_era_7d"],
                ip_last_3d              = g["away_bp_ip_3d"],
                high_lev_used_yesterday = g["away_bp_highlev_yest"],
            ),
            home             = False,
            off_rating       = g["away_off_rating"],
            time_zone_change = g["away_tz_change"],
        )
        game_input = GameInput(
            umpire_name          = g["umpire"],
            home_team            = home_ctx,
            away_team            = away_ctx,
            market_total         = g["close_total"],
            abs_challenge_active = abs_active,
        )

        output = compute_fair_total(game_input)
        rec    = output.recommendation
        actual = g["actual_runs"]
        close  = g["close_total"]
        open_t = g["open_total"]

        # CLV: how much did we beat the opening / closing line?
        # For OVER: beating means close > open (line moved our way)
        # For UNDER: beating means close < open
        if rec == "OVER":
            clv_vs_open  = close - open_t
            clv_vs_close = 0.0   # by definition 0 when using close as market
        elif rec == "UNDER":
            clv_vs_open  = open_t - close
            clv_vs_close = 0.0
        else:
            clv_vs_open = clv_vs_close = 0.0

        bet_placed = rec != "NO BET"
        won: bool | None = None
        pnl = 0.0
        if bet_placed:
            won = _determine_outcome(rec, actual, close)
            if won is True:
                pnl = PAYOUT
            elif won is False:
                pnl = -STAKE
            # push: pnl = 0

        results.append(BetResult(
            game_id        = g.get("game_id", 0),
            date           = g["date"],
            home_team      = g["home_team"],
            away_team      = g["away_team"],
            umpire         = g["umpire"],
            recommendation = rec,
            fair_total     = output.fair_total,
            open_total     = open_t,
            close_total    = close,
            actual_runs    = actual,
            edge_runs      = output.edge_runs,
            confidence     = output.confidence,
            kelly_fraction = output.kelly_fraction,
            bet_placed     = bet_placed,
            won            = won,
            pnl            = pnl,
            clv_vs_open    = clv_vs_open,
            clv_vs_close   = clv_vs_close,
        ))

    return results


def print_backtest_report(results: List[BetResult]) -> None:
    bets = [r for r in results if r.bet_placed and r.won is not None]
    wins = [r for r in bets if r.won]
    no_bets = [r for r in results if not r.bet_placed]
    overs = [r for r in bets if r.recommendation == "OVER"]
    unders = [r for r in bets if r.recommendation == "UNDER"]

    total_pnl       = sum(r.pnl for r in bets)
    total_staked    = len(bets) * STAKE
    roi             = (total_pnl / total_staked * 100) if total_staked else 0
    win_rate        = (len(wins) / len(bets) * 100) if bets else 0
    avg_edge        = statistics.mean(abs(r.edge_runs) for r in bets) if bets else 0
    avg_confidence  = statistics.mean(r.confidence for r in bets) if bets else 0
    avg_clv_open    = statistics.mean(r.clv_vs_open for r in bets) if bets else 0

    width = 60
    sep = "─" * width
    print(f"\n{'ZONE MODEL BACKTEST REPORT':^{width}}")
    print(sep)
    print(f"  Total games analyzed:   {len(results)}")
    print(f"  Bets placed:            {len(bets)}  ({len(bets)/len(results)*100:.1f}% of games)")
    print(f"  No-bet filter removed:  {len(no_bets)} games")
    print(sep)
    print(f"  Win rate:               {win_rate:.1f}%  (breakeven = 52.4%)")
    print(f"  Net P&L (paper $100):  ${total_pnl:+.2f}")
    print(f"  Total staked:          ${total_staked:.2f}")
    print(f"  ROI:                   {roi:+.2f}%")
    print(sep)
    print(f"  OVER bets:  {len(overs):3d}  |  wins: {sum(1 for r in overs if r.won):3d}")
    print(f"  UNDER bets: {len(unders):3d}  |  wins: {sum(1 for r in unders if r.won):3d}")
    print(sep)
    print(f"  Avg model edge (|runs|): {avg_edge:.3f}")
    print(f"  Avg confidence:          {avg_confidence:.1%}")
    print(f"  Avg CLV vs open line:   {avg_clv_open:+.3f} runs")
    print(sep)

    # Breakdown by umpire bucket
    high_edge = [r for r in bets if abs(r.edge_runs) >= 0.60]
    if high_edge:
        he_wins = sum(1 for r in high_edge if r.won)
        he_pnl  = sum(r.pnl for r in high_edge)
        print(f"  HIGH EDGE (≥0.60 runs): {len(high_edge)} bets, "
              f"{he_wins/len(high_edge)*100:.1f}% win, "
              f"${he_pnl:+.2f} P&L")

    # 5 biggest wins and worst losses
    sorted_bets = sorted(bets, key=lambda r: r.pnl, reverse=True)
    print(f"\n  Top 3 wins:")
    for r in sorted_bets[:3]:
        print(f"    {r.date} {r.away_team} @ {r.home_team} "
              f"({r.umpire}) | {r.recommendation} {r.close_total} "
              f"| actual {r.actual_runs} | ${r.pnl:+.2f}")
    print(f"  Top 3 losses:")
    for r in sorted_bets[-3:]:
        print(f"    {r.date} {r.away_team} @ {r.home_team} "
              f"({r.umpire}) | {r.recommendation} {r.close_total} "
              f"| actual {r.actual_runs} | ${r.pnl:+.2f}")
    print(sep)


if __name__ == "__main__":
    print("Running backtest (ABS challenge system ON) …")
    results = run_backtest(abs_active=True)
    print_backtest_report(results)

    print("\nRunning backtest (ABS challenge system OFF — pre-2025) …")
    results_no_abs = run_backtest(abs_active=False)
    print_backtest_report(results_no_abs)
