"""
Pitcher profile schema and sample data.

In production: populated from Baseball Reference / FanGraphs / Statcast APIs.

Key metrics per pitcher:
  k_pct     - Strikeout percentage (K per plate appearance)
  bb_pct    - Walk percentage (BB per plate appearance)
  gbpct     - Ground ball percentage (low GB = more fly balls = more HRs with big zone)
  zone_pct  - % of pitches thrown in the strike zone
  era_adj   - ERA adjusted for park factor (ERA-)
  ip_per_start - average innings pitched per start (bullpen usage signal)
  days_rest - days since last start (set at game-time)
  hand      - pitching hand ('R' or 'L')
"""

PITCHER_PROFILES = {
    # Strikeout artists — benefit most from big zones
    "Gerrit Cole": {
        "k_pct": 0.298, "bb_pct": 0.062, "gbpct": 0.388,
        "zone_pct": 0.478, "era_adj": 78, "ip_per_start": 6.1,
        "hand": "R",
    },
    "Spencer Strider": {
        "k_pct": 0.355, "bb_pct": 0.071, "gbpct": 0.311,
        "zone_pct": 0.459, "era_adj": 65, "ip_per_start": 5.9,
        "hand": "R",
    },
    "Blake Snell": {
        "k_pct": 0.319, "bb_pct": 0.118, "gbpct": 0.362,
        "zone_pct": 0.411, "era_adj": 71, "ip_per_start": 5.4,
        "hand": "L",
    },
    # Control pitchers — benefit moderately, hurt more by tight zones
    "Zack Wheeler": {
        "k_pct": 0.268, "bb_pct": 0.054, "gbpct": 0.441,
        "zone_pct": 0.502, "era_adj": 82, "ip_per_start": 6.4,
        "hand": "R",
    },
    "Logan Webb": {
        "k_pct": 0.221, "bb_pct": 0.062, "gbpct": 0.571,
        "zone_pct": 0.521, "era_adj": 88, "ip_per_start": 6.2,
        "hand": "R",
    },
    # Wild/walk-prone — most sensitive to zone size
    "Dylan Cease": {
        "k_pct": 0.294, "bb_pct": 0.101, "gbpct": 0.339,
        "zone_pct": 0.426, "era_adj": 84, "ip_per_start": 5.7,
        "hand": "R",
    },
    "Max Scherzer": {
        "k_pct": 0.279, "bb_pct": 0.058, "gbpct": 0.389,
        "zone_pct": 0.498, "era_adj": 80, "ip_per_start": 5.8,
        "hand": "R",
    },
    "Sandy Alcantara": {
        "k_pct": 0.219, "bb_pct": 0.060, "gbpct": 0.582,
        "zone_pct": 0.509, "era_adj": 86, "ip_per_start": 6.6,
        "hand": "R",
    },
    # Placeholder for unknown pitcher
    "__UNKNOWN__": {
        "k_pct": 0.220, "bb_pct": 0.080, "gbpct": 0.440,
        "zone_pct": 0.470, "era_adj": 100, "ip_per_start": 5.5,
        "hand": "R",
    },
}

# Bullpen fatigue profile schema (per team)
# In production: computed from game log of previous 7 days
def default_bullpen():
    return {
        "avg_era_7d": 4.20,        # rolling ERA of bullpen in last 7 days
        "ip_last_3d": 5.5,         # total innings thrown by bullpen in last 3 days
        "high_lev_used_yesterday": False,  # was closer/setup used yesterday?
    }
