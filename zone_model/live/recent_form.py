"""
Recent Form Module
==================
Fetches last 5 games for any team from ESPN and computes a form score
used as a momentum/trend layer across all models.

Returns:
  - Points/runs scored and allowed per game (last 5)
  - Win/loss streak
  - Offensive and defensive trend (improving vs declining)
  - Form score: -1.0 to +1.0 (positive = team is hot)
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from datetime import date
from dataclasses import dataclass, field
from typing import Optional

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

SPORT_PATHS = {
    "mlb":  ("baseball",    "mlb"),
    "nfl":  ("football",    "nfl"),
    "nba":  ("basketball",  "nba"),
    "nhl":  ("hockey",      "nhl"),
    "ncaaf":("football",    "college-football"),
}


@dataclass
class GameResult:
    date:        str
    opponent:    str
    team_score:  float
    opp_score:   float
    won:         bool
    home:        bool


@dataclass
class RecentForm:
    team:           str
    sport:          str
    games:          list[GameResult] = field(default_factory=list)
    avg_scored:     float = 0.0
    avg_allowed:    float = 0.0
    win_streak:     int   = 0      # positive = wins, negative = losses
    off_trend:      float = 0.0    # slope of scoring over last 5 games
    def_trend:      float = 0.0    # slope of points allowed (negative = improving)
    form_score:     float = 0.0    # composite -1 to +1
    available:      bool  = False


def _espn_get(sport: str, path: str) -> dict:
    s, l = SPORT_PATHS[sport]
    url = f"{ESPN_BASE}/{s}/{l}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "ZoneModel/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _find_team_id(sport: str, team_name: str) -> Optional[str]:
    """Fuzzy search ESPN teams endpoint for a team ID."""
    try:
        data = _espn_get(sport, "teams")
        for entry in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
            t = entry.get("team", {})
            name = t.get("displayName", "")
            if team_name.lower() in name.lower() or name.lower() in team_name.lower():
                return t.get("id")
    except Exception:
        pass
    return None


def _linear_slope(values: list[float]) -> float:
    """Simple linear regression slope over index."""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def get_recent_form(sport: str, team_name: str, n: int = 5) -> RecentForm:
    """
    Fetch the last `n` completed games for `team_name` in `sport`.
    Returns a RecentForm dataclass. Falls back gracefully on network failure.
    """
    form = RecentForm(team=team_name, sport=sport)

    try:
        team_id = _find_team_id(sport, team_name)
        if not team_id:
            return form

        data = _espn_get(sport, f"teams/{team_id}/schedule")
        events = data.get("events", [])

        results: list[GameResult] = []
        for ev in reversed(events):   # most recent first
            status = ev.get("competitions", [{}])[0].get("status", {}).get("type", {})
            if not status.get("completed", False):
                continue

            comps = ev.get("competitions", [{}])[0]
            competitors = comps.get("competitors", [])
            if len(competitors) < 2:
                continue

            team_comp = next(
                (c for c in competitors
                 if team_name.lower() in c.get("team", {}).get("displayName", "").lower()),
                None
            )
            if not team_comp:
                continue
            opp_comp = next((c for c in competitors if c is not team_comp), None)
            if not opp_comp:
                continue

            team_score = float(team_comp.get("score", 0) or 0)
            opp_score  = float(opp_comp.get("score",  0) or 0)
            won        = team_comp.get("winner", False)
            home       = team_comp.get("homeAway", "") == "home"
            game_date  = ev.get("date", "")[:10]
            opp_name   = opp_comp.get("team", {}).get("displayName", "?")

            results.append(GameResult(
                date       = game_date,
                opponent   = opp_name,
                team_score = team_score,
                opp_score  = opp_score,
                won        = won,
                home       = home,
            ))
            if len(results) >= n:
                break

        if not results:
            return form

        form.games     = results
        form.available = True

        scored  = [g.team_score for g in results]
        allowed = [g.opp_score  for g in results]
        form.avg_scored  = round(sum(scored)  / len(scored),  2)
        form.avg_allowed = round(sum(allowed) / len(allowed), 2)

        # Win streak (positive = win streak, negative = losing streak)
        streak = 0
        for g in results:
            if g.won:
                streak = streak + 1 if streak >= 0 else 1
            else:
                streak = streak - 1 if streak <= 0 else -1
        form.win_streak = streak

        # Trend slopes (reversed so index 0 = oldest)
        form.off_trend = round(_linear_slope(list(reversed(scored))),  3)
        form.def_trend = round(_linear_slope(list(reversed(allowed))), 3)

        # Form score: blend of win rate, scoring trend, defense trend
        win_rate   = sum(1 for g in results if g.won) / len(results)
        off_signal = max(-1.0, min(1.0, form.off_trend  / 2.0))
        def_signal = max(-1.0, min(1.0, -form.def_trend / 2.0))   # lower allowed = better
        form.form_score = round((win_rate - 0.5) * 2 * 0.5 + off_signal * 0.3 + def_signal * 0.2, 3)

    except Exception:
        pass

    return form


def form_run_adjustment(form: RecentForm, sport: str = "mlb") -> float:
    """
    Converts a team's form score into a run/point adjustment for the total model.
    Hot teams score more; cold teams score less. Returns delta to add to fair total.
    """
    if not form.available:
        return 0.0

    # Scale factors per sport (how much does recent form shift expected scoring)
    scales = {"mlb": 0.4, "nfl": 3.0, "nba": 4.0, "nhl": 0.3, "ncaaf": 3.5}
    scale  = scales.get(sport, 1.0)
    return round(form.form_score * scale, 3)


def format_form_summary(form: RecentForm) -> str:
    """One-line summary for display in pick reports."""
    if not form.available:
        return f"{form.team}: form data unavailable"
    streak_str = f"W{form.win_streak}" if form.win_streak > 0 else f"L{abs(form.win_streak)}"
    trend = "↑" if form.off_trend > 0.3 else ("↓" if form.off_trend < -0.3 else "→")
    return (f"{form.team}: last {len(form.games)}G avg {form.avg_scored:.1f} scored / "
            f"{form.avg_allowed:.1f} allowed  streak={streak_str}  scoring {trend}  "
            f"form={form.form_score:+.2f}")
