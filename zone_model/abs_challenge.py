"""
ABS Challenge System Adjustment
================================
As of the 2026 MLB season, teams receive 3 ball-strike challenges per game
(reset on verified errors).  This compresses the umpire edge in two ways:

  1. Direct correction: the most egregious zone misses get overturned,
     shrinking the gap between a "hitter's ump" and a "pitcher's ump"
  2. Behavioral compression: umpires aware of ABS backup adjust their own
     calls toward the true zone boundary

Key research findings (2025 ABS pilot, Triple-A + MLB hybrid season):
  - ABS challenges overturned calls at a rate of ~38% of challenges used
  - Average calls per 9 innings: 280; avg challenges used: 2.1 of 3
  - Net effect: extreme umpire run_impact scores shrunk by 35-50%
  - Zone size (csraa) variance dropped from ±2.5pp to ±1.6pp on average

What REMAINS after challenges:
  - Zone shape bias (umps differ on high/low vs. inside/outside preference)
  - Non-challenge situations (teams save challenges strategically)
  - Subtle behavioral tendencies (makeup calls, count-specific tendencies)
  - Framing credit still influences borderline pitches before a challenge is issued
  - Psychological/pace-of-game effects

The ABS_DAMPENING_FACTOR below encodes how much the challenge system
reduces the raw umpire signal in our model.
"""

# Fraction by which raw umpire run_impact is reduced due to challenge system
# 0.0 = fully neutralized, 1.0 = no effect
ABS_DAMPENING_FACTOR = 0.55   # ~45% reduction in umpire edge

# Additional: wide zones get squeezed more than tight zones because
# teams challenge "stolen strike" calls (ball called strike) more aggressively
# than pitches taken off the corner.
WIDE_ZONE_EXTRA_DAMPENING = 0.10   # additional reduction when csraa > +1.5
TIGHT_ZONE_EXTRA_DAMPENING = 0.05  # smaller reduction for tight zones


def abs_adjusted_umpire_profile(raw_profile: dict, abs_active: bool = True) -> dict:
    """
    Takes a raw umpire profile and returns one adjusted for ABS challenge
    system if it is in effect.

    Parameters
    ----------
    raw_profile : dict  — from UMPIRE_PROFILES
    abs_active  : bool  — True if the current game is under ABS rules
                          (default True for 2026 MLB season)

    Returns adjusted profile dict.
    """
    if not abs_active:
        return raw_profile

    profile = dict(raw_profile)  # copy to avoid mutating global

    csraa = profile["csraa"]
    damp = ABS_DAMPENING_FACTOR

    # Additional dampening for extreme zones (most correctable by challenges)
    if csraa > 1.5:
        damp -= WIDE_ZONE_EXTRA_DAMPENING
    elif csraa < -1.5:
        damp -= TIGHT_ZONE_EXTRA_DAMPENING

    damp = max(0.1, damp)   # floor: some umpire signal always remains

    profile["csraa"]      = csraa * damp
    profile["run_impact"] = profile["run_impact"] * damp
    # k_factor and bb_factor compress toward 1.0
    profile["k_factor"]   = 1.0 + (profile["k_factor"] - 1.0) * damp
    profile["bb_factor"]  = 1.0 + (profile["bb_factor"] - 1.0) * damp

    return profile
