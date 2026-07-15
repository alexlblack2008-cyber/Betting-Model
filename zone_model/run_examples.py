"""
Example runs of The Zone Model.

Run with:  python run_examples.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from zone_model import (
    GameInput, TeamContext, BullpenState, compute_fair_total, print_report
)

# ---------------------------------------------------------------------------
# Example 1: Heavy hitter's ump vs. two strikeout pitchers
#   - CB Bucknor is one of the tightest zones in the league
#   - Both starters are swing-and-miss arms who suffer with tight zones
#   - Market has this at 8.5 — model will likely push toward OVER
# ---------------------------------------------------------------------------
game1 = GameInput(
    umpire_name="CB Bucknor",
    home_team=TeamContext(
        team_name="New York Yankees",
        starter_name="Gerrit Cole",
        days_rest=4,
        bullpen=BullpenState(avg_era_7d=3.80, ip_last_3d=4.5, high_lev_used_yesterday=False),
        home=True,
        off_rating=108,
        time_zone_change=0,
    ),
    away_team=TeamContext(
        team_name="Houston Astros",
        starter_name="Spencer Strider",
        days_rest=5,
        bullpen=BullpenState(avg_era_7d=4.50, ip_last_3d=6.2, high_lev_used_yesterday=True),
        home=False,
        off_rating=105,
        time_zone_change=1,   # traveled east one time zone
    ),
    market_total=8.5,
    abs_challenge_active=True,
)

result1 = compute_fair_total(game1)
print_report(game1, result1)


# ---------------------------------------------------------------------------
# Example 2: Large-zone ump vs. a ground-ball pitcher and a control artist
#   - Nic Lentz has one of the biggest zones in the league
#   - Logan Webb is an extreme GB pitcher (zone-insensitive)
#   - Zack Wheeler is a control pitcher who thrives in big zones
#   - Market at 9.0 — model will likely lean UNDER
# ---------------------------------------------------------------------------
game2 = GameInput(
    umpire_name="Nic Lentz",
    home_team=TeamContext(
        team_name="San Francisco Giants",
        starter_name="Logan Webb",
        days_rest=4,
        bullpen=BullpenState(avg_era_7d=4.10, ip_last_3d=5.0, high_lev_used_yesterday=False),
        home=True,
        off_rating=97,
        time_zone_change=0,
    ),
    away_team=TeamContext(
        team_name="Philadelphia Phillies",
        starter_name="Zack Wheeler",
        days_rest=4,
        bullpen=BullpenState(avg_era_7d=3.65, ip_last_3d=4.8, high_lev_used_yesterday=False),
        home=False,
        off_rating=112,
        time_zone_change=-3,  # traveled west three time zones
    ),
    market_total=9.0,
    abs_challenge_active=True,
)

result2 = compute_fair_total(game2)
print_report(game2, result2)


# ---------------------------------------------------------------------------
# Example 3: ABS OFF (historical comparison / pre-2025 season)
# ---------------------------------------------------------------------------
game3 = GameInput(
    umpire_name="Nic Lentz",
    home_team=TeamContext(
        team_name="San Francisco Giants",
        starter_name="Logan Webb",
        days_rest=4,
        bullpen=BullpenState(avg_era_7d=4.10, ip_last_3d=5.0, high_lev_used_yesterday=False),
        home=True,
        off_rating=97,
        time_zone_change=0,
    ),
    away_team=TeamContext(
        team_name="Philadelphia Phillies",
        starter_name="Zack Wheeler",
        days_rest=4,
        bullpen=BullpenState(avg_era_7d=3.65, ip_last_3d=4.8, high_lev_used_yesterday=False),
        home=False,
        off_rating=112,
        time_zone_change=-3,
    ),
    market_total=9.0,
    abs_challenge_active=False,   # ABS off — pre-challenge era
)

result3 = compute_fair_total(game3)
print("\n[COMPARISON: Same game WITHOUT ABS challenge system (pre-2025)]")
print_report(game3, result3)
print("\n[ABS effect on this game]")
print(f"  Fair total WITH ABS:    {result2.fair_total:.2f}")
print(f"  Fair total WITHOUT ABS: {result3.fair_total:.2f}")
print(f"  ABS compression:        {result3.fair_total - result2.fair_total:+.2f} runs")
