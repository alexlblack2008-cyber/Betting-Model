"""
Paper-trading ledger.

Tracks every pick at a $100 stake. Persists to ledger.json in the zone_model
directory. Supports:
  - Recording a pick at bet time (outcome=pending)
  - Settling a pick once the game finishes
  - Weekly P&L report
"""

from __future__ import annotations
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

LEDGER_PATH = Path(__file__).parent / "ledger.json"
STAKE = 100.0
WIN_PAYOUT = STAKE / 1.10   # -110 juice → win $90.91 on $100 risk


def _load() -> list[dict]:
    if LEDGER_PATH.exists():
        with open(LEDGER_PATH) as f:
            return json.load(f)
    return []


def _save(entries: list[dict]) -> None:
    with open(LEDGER_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def record_pick(
    bet_date: str,
    home_team: str,
    away_team: str,
    umpire: str,
    recommendation: str,    # "OVER" or "UNDER"
    market_total: float,
    fair_total: float,
    edge_runs: float,
    confidence: float,
    kelly_fraction: float,
    game_pk: Optional[int] = None,
) -> None:
    """Log a new pick. Outcome starts as 'pending'."""
    entries = _load()
    entries.append({
        "bet_date":       bet_date,
        "game_pk":        game_pk,
        "home_team":      home_team,
        "away_team":      away_team,
        "umpire":         umpire,
        "recommendation": recommendation,
        "market_total":   market_total,
        "fair_total":     fair_total,
        "edge_runs":      edge_runs,
        "confidence":     round(confidence, 3),
        "kelly_fraction": round(kelly_fraction, 4),
        "stake":          STAKE,
        "outcome":        "pending",
        "actual_runs":    None,
        "pnl":            None,
        "settled_at":     None,
    })
    _save(entries)


def settle_pick(
    home_team: str,
    away_team: str,
    bet_date: str,
    actual_runs: int,
) -> str:
    """
    Settle a pending pick given the final score.
    Returns: "won", "lost", "push", or "not_found"
    """
    entries = _load()
    for e in entries:
        if (e["home_team"] == home_team
                and e["away_team"] == away_team
                and e["bet_date"] == bet_date
                and e["outcome"] == "pending"):
            total = e["market_total"]
            rec   = e["recommendation"]
            if rec == "OVER":
                result = "won" if actual_runs > total else ("push" if actual_runs == total else "lost")
            else:
                result = "won" if actual_runs < total else ("push" if actual_runs == total else "lost")

            e["actual_runs"] = actual_runs
            e["outcome"]     = result
            e["pnl"]         = WIN_PAYOUT if result == "won" else (-STAKE if result == "lost" else 0.0)
            e["settled_at"]  = datetime.utcnow().isoformat()
            _save(entries)
            return result
    return "not_found"


def record_prop_pick(
    bet_date: str,
    sport: str,
    home_team: str,
    away_team: str,
    recommendation: str,   # e.g. "OVER", "UNDER", "HOME", "AWAY"
    market_total: float,   # line or spread value
    confidence: float,
    description: str = "",  # e.g. "RJ Harris +4.5", "England/France BTTS"
) -> None:
    """Log a props/soccer/MMA/golf pick. Outcome starts as 'pending'."""
    entries = _load()
    # Avoid duplicate entries for same pick on same day
    for e in entries:
        if (e.get("home_team") == home_team and e.get("away_team") == away_team
                and e.get("bet_date") == bet_date
                and e.get("recommendation") == recommendation
                and e.get("outcome") == "pending"):
            return
    entries.append({
        "bet_date":       bet_date,
        "sport":          sport,
        "home_team":      home_team,
        "away_team":      away_team,
        "umpire":         description,
        "recommendation": recommendation,
        "market_total":   market_total,
        "confidence":     round(confidence, 3),
        "stake":          STAKE,
        "outcome":        "pending",
        "actual_runs":    None,
        "pnl":            None,
        "settled_at":     None,
    })
    _save(entries)


def weekly_pnl_report() -> str:
    """
    Returns a formatted weekly P&L summary string.
    Covers the current calendar week (Mon–Sun).
    """
    from datetime import timedelta
    entries = _load()
    today   = date.today()
    monday  = today - timedelta(days=today.weekday())
    sunday  = monday + timedelta(days=6)
    week_str = f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"

    week_entries = [
        e for e in entries
        if monday.isoformat() <= e["bet_date"] <= sunday.isoformat()
    ]
    settled   = [e for e in week_entries if e["outcome"] != "pending"]
    pending   = [e for e in week_entries if e["outcome"] == "pending"]
    wins      = [e for e in settled if e["outcome"] == "won"]
    losses    = [e for e in settled if e["outcome"] == "lost"]
    pushes    = [e for e in settled if e["outcome"] == "push"]
    total_pnl = sum(e["pnl"] for e in settled if e["pnl"] is not None)
    staked    = len(settled) * STAKE
    roi       = (total_pnl / staked * 100) if staked else 0.0

    lines = [
        "=" * 56,
        f"  ZONE MODEL  |  Weekly P&L  |  {week_str}",
        "=" * 56,
        f"  Picks this week:  {len(week_entries)}",
        f"  Settled:          {len(settled)}  "
        f"(W {len(wins)} / L {len(losses)} / P {len(pushes)})",
        f"  Pending:          {len(pending)}",
        f"  Total staked:    ${staked:.2f}",
        f"  Net P&L:         ${total_pnl:+.2f}",
        f"  ROI:             {roi:+.2f}%",
        "-" * 56,
    ]
    for e in week_entries:
        status = e["outcome"].upper()
        pnl_str = f"${e['pnl']:+.2f}" if e["pnl"] is not None else "pending"
        runs_str = str(e["actual_runs"]) if e["actual_runs"] is not None else "?"
        lines.append(
            f"  {e['bet_date']}  {e['away_team'][:15]:15s} @ "
            f"{e['home_team'][:15]:15s}  "
            f"{e['recommendation']} {e['market_total']}  "
            f"actual={runs_str:>3s}  {status:7s}  {pnl_str}"
        )
    lines.append("=" * 56)
    return "\n".join(lines)


def all_time_summary() -> str:
    """One-line all-time stats for inclusion in daily notification."""
    entries = _load()
    settled = [e for e in entries if e["outcome"] != "pending"]
    wins    = sum(1 for e in settled if e["outcome"] == "won")
    total_pnl = sum(e["pnl"] for e in settled if e["pnl"] is not None)
    staked  = len(settled) * STAKE
    roi     = (total_pnl / staked * 100) if staked else 0.0
    return (
        f"All-time: {wins}/{len(settled)} ({wins/len(settled)*100:.1f}% win) "
        f"${total_pnl:+.2f} ROI {roi:+.2f}%"
    ) if settled else "All-time: no settled bets yet"
