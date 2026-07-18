"""
Auto-settle pending picks by fetching final scores from ESPN.
Runs daily before the picks pipeline so yesterday's results are settled.
"""
import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "ledger.json"

ESPN_SOCCER = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={date}"
ESPN_MLB    = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={date}"

SOCCER_LEAGUES = [
    "fifa.world", "fifa.world_cup", "uefa.champions", "uefa.europa",
    "eng.1", "eng.fa", "eng.league_cup", "conmebol.libertadores",
    "conmebol.america", "uefa.euro",
]


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _load():
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return []


def _save(entries):
    LEDGER_PATH.write_text(json.dumps(entries, indent=2))


def _pnl(entry, outcome):
    staked = entry.get("actual_stake") or entry.get("stake") or 100
    to_win = entry.get("actual_to_win") or round(staked / 1.10, 2)
    if outcome == "won":  return round(to_win, 2)
    if outcome == "lost": return -staked
    return 0


def _settle_entry(entry, home_score, away_score):
    rec = entry["recommendation"]
    if rec in ("OVER", "UNDER"):
        total = home_score + away_score
        entry["actual_runs"] = total
        if rec == "OVER":
            outcome = "won" if total > entry["market_total"] else ("push" if total == entry["market_total"] else "lost")
        else:
            outcome = "won" if total < entry["market_total"] else ("push" if total == entry["market_total"] else "lost")
    elif rec == "HOME":
        entry["actual_home_score"] = home_score
        entry["actual_away_score"] = away_score
        entry["actual_runs"] = home_score + away_score
        outcome = "won" if home_score > away_score else ("push" if home_score == away_score else "lost")
    elif rec == "AWAY":
        entry["actual_home_score"] = home_score
        entry["actual_away_score"] = away_score
        entry["actual_runs"] = home_score + away_score
        outcome = "won" if away_score > home_score else ("push" if home_score == away_score else "lost")
    else:
        return False

    from datetime import datetime
    entry["outcome"]    = outcome
    entry["pnl"]        = _pnl(entry, outcome)
    entry["settled_at"] = datetime.utcnow().isoformat()
    print(f"  ✓ Settled {entry['away_team']} @ {entry['home_team']} "
          f"({rec} {entry['market_total']}) → {outcome.upper()} ${entry['pnl']:+.2f}")
    return True


def _name_match(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    return a in b or b in a or a.split()[-1] in b or b.split()[-1] in a


def settle_soccer(entries, check_date):
    date_str = check_date.strftime("%Y%m%d")
    pending = [e for e in entries if e["outcome"] == "pending"
               and e.get("sport") == "soccer" and e["bet_date"] == check_date.isoformat()]
    if not pending:
        return

    for league in SOCCER_LEAGUES:
        data = _get(ESPN_SOCCER.format(league=league, date=date_str))
        if not data:
            continue
        for event in data.get("events", []):
            comps = event.get("competitions", [{}])[0]
            competitors = comps.get("competitors", [])
            if len(competitors) < 2:
                continue
            status = comps.get("status", {}).get("type", {}).get("completed", False)
            if not status:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            home_name  = home.get("team", {}).get("displayName", "")
            away_name  = away.get("team", {}).get("displayName", "")
            home_score = int(home.get("score", 0))
            away_score = int(away.get("score", 0))

            for e in pending:
                if e["outcome"] != "pending":
                    continue
                if _name_match(e["home_team"], home_name) and _name_match(e["away_team"], away_name):
                    _settle_entry(e, home_score, away_score)


def settle_mlb(entries, check_date):
    date_str = check_date.strftime("%Y%m%d")
    pending = [e for e in entries if e["outcome"] == "pending"
               and e.get("sport", "mlb") == "mlb" and e["bet_date"] == check_date.isoformat()]
    if not pending:
        return

    data = _get(ESPN_MLB.format(date=date_str))
    if not data:
        return

    for event in data.get("events", []):
        comps = event.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        status = comps.get("status", {}).get("type", {}).get("completed", False)
        if not status or len(competitors) < 2:
            continue
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        home_name  = home.get("team", {}).get("displayName", "")
        away_name  = away.get("team", {}).get("displayName", "")
        home_score = int(home.get("score", 0))
        away_score = int(away.get("score", 0))

        for e in pending:
            if e["outcome"] != "pending":
                continue
            if _name_match(e["home_team"], home_name) and _name_match(e["away_team"], away_name):
                _settle_entry(e, home_score, away_score)


def run():
    entries = _load()
    today = date.today()
    changed = False

    for days_ago in range(1, 4):  # check last 3 days
        check_date = today - timedelta(days=days_ago)
        before = sum(1 for e in entries if e["outcome"] == "pending")
        settle_mlb(entries, check_date)
        settle_soccer(entries, check_date)
        after = sum(1 for e in entries if e["outcome"] == "pending")
        if after < before:
            changed = True

    if changed:
        _save(entries)
        print("  [Auto-settle] Ledger updated.")
    else:
        print("  [Auto-settle] No new results to settle.")


if __name__ == "__main__":
    run()
