"""
Cron entry point — called once daily by the CCR Routine trigger.

Runs the full Zone Model daily pipeline, prints the report, and emails
it directly to alex.l.black.2008@gmail.com via Gmail SMTP.

Required env vars (set on Render):
  ODDS_API_KEY        — The Odds API key
  GMAIL_APP_PASSWORD  — 16-char Gmail App Password (myaccount.google.com/apppasswords)
  GMAIL_FROM          — sending address (defaults to alex.l.black.2008@gmail.com)
  GMAIL_TO            — recipient address (defaults to alex.l.black.2008@gmail.com)
  BANKROLL            — paper bankroll in dollars (default 1000)
"""

import sys
import os
import smtplib
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from daily_picks import run_daily
from ledger import weekly_pnl_report
from datetime import date

GMAIL_FROM = os.environ.get("GMAIL_FROM", "alex.l.black.2008@gmail.com")
GMAIL_TO   = os.environ.get("GMAIL_TO",   "alex.l.black.2008@gmail.com")


def _build_html(body: str, today: str) -> str:
    """Convert plain-text report into a clean styled HTML email."""
    html_lines = []
    for line in body.splitlines():
        stripped = line.strip()

        # Section headers
        if stripped.startswith("THE ZONE MODEL") or stripped.startswith("PICK #") \
                or stripped.startswith("PROP EDGES") or stripped.startswith("GOLF VALUE") \
                or stripped.startswith("MONDAY WEEKLY"):
            html_lines.append(f'<div class="section-header">{stripped}</div>')

        # The actual pick line
        elif stripped.startswith("**THE PICK:") or stripped.startswith("THE PICK:"):
            pick_text = stripped.replace("**", "")
            html_lines.append(f'<div class="pick-line">{pick_text}</div>')

        # OVER / UNDER / BET SLIP header lines
        elif stripped.startswith("▲") or stripped.startswith("▼"):
            html_lines.append(f'<div class="direction">{stripped}</div>')

        # WHY THIS BET / NUMBERS / STAKE headers
        elif "WHY THIS BET" in stripped or "NUMBERS" in stripped \
                or "STAKE" in stripped or "ODDS & EDGE" in stripped \
                or "PREP / NEWS" in stripped:
            html_lines.append(f'<div class="sub-header">{stripped}</div>')

        # Bullet points
        elif stripped.startswith("•") or stripped.startswith("★"):
            html_lines.append(f'<div class="bullet">{stripped}</div>')

        # Divider lines
        elif set(stripped) <= set("=─·-│┌┐└┘├┤") and len(stripped) > 4:
            html_lines.append('<hr>')

        # Empty line
        elif stripped == "":
            html_lines.append('<div class="spacer"></div>')

        # Everything else
        else:
            html_lines.append(f'<div class="row">{stripped}</div>')

    content = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    margin: 0; padding: 0;
    background: #0f0f0f;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    color: #e8e8e8;
  }}
  .wrapper {{
    max-width: 600px;
    margin: 0 auto;
    padding: 24px 16px;
  }}
  .logo {{
    text-align: center;
    padding: 28px 0 8px;
  }}
  .logo-title {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 3px;
    color: #ffffff;
    text-transform: uppercase;
  }}
  .logo-sub {{
    font-size: 12px;
    color: #666;
    letter-spacing: 2px;
    margin-top: 4px;
    text-transform: uppercase;
  }}
  .date-bar {{
    text-align: center;
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 10px;
    margin: 16px 0 24px;
    font-size: 13px;
    color: #888;
    letter-spacing: 1px;
    text-transform: uppercase;
  }}
  .card {{
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 10px;
    padding: 20px 22px;
    margin-bottom: 16px;
  }}
  .section-header {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #888;
    text-transform: uppercase;
    padding: 18px 0 6px;
  }}
  .pick-line {{
    background: #00c853;
    color: #000;
    font-weight: 700;
    font-size: 15px;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 10px 0;
    letter-spacing: 0.5px;
  }}
  .direction {{
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    padding: 6px 0 2px;
  }}
  .sub-header {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    color: #555;
    text-transform: uppercase;
    padding: 14px 0 4px;
    border-top: 1px solid #252525;
    margin-top: 10px;
  }}
  .bullet {{
    font-size: 14px;
    color: #ccc;
    padding: 3px 0 3px 8px;
    line-height: 1.5;
  }}
  .row {{
    font-size: 13px;
    color: #aaa;
    padding: 2px 0;
    line-height: 1.6;
  }}
  .spacer {{ height: 6px; }}
  hr {{
    border: none;
    border-top: 1px solid #252525;
    margin: 10px 0;
  }}
  .footer {{
    text-align: center;
    font-size: 11px;
    color: #444;
    padding: 20px 0;
    letter-spacing: 1px;
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="logo">
    <div class="logo-title">⚡ The Zone Model</div>
    <div class="logo-sub">Daily Picks Report</div>
  </div>
  <div class="date-bar">{today}</div>
  <div class="card">
    {content}
  </div>
  <div class="footer">Zone Model · Automated Daily Report · Do not reply</div>
</div>
</body>
</html>"""


def _send_email(subject: str, body: str, today: str = "") -> bool:
    """Send picks report via Gmail SMTP. Returns True on success."""
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_password:
        print("  [Email] GMAIL_APP_PASSWORD not set — skipping email.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Zone Model <{GMAIL_FROM}>"
        msg["To"]      = GMAIL_TO

        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(_build_html(body, today), "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_FROM, app_password)
            server.sendmail(GMAIL_FROM, GMAIL_TO, msg.as_string())

        print(f"  [Email] Sent to {GMAIL_TO} ✓")
        return True
    except Exception as e:
        print(f"  [Email] Failed: {e}")
        return False


def _props_section(today: str) -> str:
    """Season-aware props scan across all sports."""
    try:
        api_key = os.environ.get("ODDS_API_KEY", "")
        if not api_key:
            return ""
        from props_model import scan_all_props, format_prop_pick
        from ledger import record_prop_pick
        picks = scan_all_props(api_key, today, max_picks=8)
        if not picks:
            return ""
        lines = [
            "",
            "=" * 56,
            "  PROP EDGES — ANY SPORT, ANY MARKET",
            "=" * 56,
        ]
        for p in picks:
            lines.append(format_prop_pick(p))
            lines.append("")
            # Log to ledger so it shows on the website
            try:
                home = getattr(p, "team", p.player)
                away = getattr(p, "opponent", p.sport)
                desc = f"{p.player} {p.prop_type} {p.line}"
                record_prop_pick(
                    bet_date       = today,
                    sport          = p.sport,
                    home_team      = home,
                    away_team      = away,
                    recommendation = p.recommendation,
                    market_total   = p.line,
                    confidence     = p.confidence,
                    description    = desc,
                )
            except Exception:
                pass
        return "\n".join(lines)
    except Exception:
        return ""


def _golf_section() -> str:
    """Fetch live golf odds and scan for value picks."""
    try:
        from golf_model import ACTIVE_TOURNAMENTS, scan_tournament, format_golf_pick
        bankroll = float(os.environ.get("BANKROLL", "1000"))

        live_events = []
        api_key = os.environ.get("ODDS_API_KEY", "")
        if api_key:
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "live"))
                from odds_client import fetch_golf_odds
                live_events = fetch_golf_odds()
            except Exception:
                pass

        events = live_events if live_events else ACTIVE_TOURNAMENTS
        if not events:
            return ""

        lines = [
            "",
            "=" * 56,
            "  GOLF VALUE PICKS" + (" [LIVE ODDS: DK/FD]" if live_events else ""),
            "=" * 56,
        ]
        for event in events:
            course_name = event.get("course")
            player_odds = event.get("player_odds", {})
            if not course_name or not player_odds:
                continue
            picks = scan_tournament(
                course_name,
                player_odds,
                top5_odds  = event.get("top5_odds"),
                top10_odds = event.get("top10_odds"),
                top20_odds = event.get("top20_odds"),
                bankroll   = bankroll,
            )
            if picks:
                lines.append(f"\n  {event.get('tournament', event.get('name', course_name)).upper()}")
                for p in picks:
                    lines.append(format_golf_pick(p, bankroll=bankroll))
                    lines.append("")
        return "\n".join(lines) if len(lines) > 4 else ""
    except Exception:
        return ""


def main():
    today = date.today().isoformat()
    print(f"[Zone Model] Running daily picks for {today} …\n")

    report = run_daily(today, log_to_ledger=True)
    props  = _props_section(today)
    golf   = _golf_section()

    full_report = report + props + golf

    # Monday P&L recap
    if date.today().weekday() == 0:
        recap = (
            "\n" + "=" * 56 + "\n"
            "  MONDAY WEEKLY RECAP\n"
            + "=" * 56 + "\n"
            + weekly_pnl_report()
        )
        full_report += recap

    print(full_report)

    # Email the report directly
    subject = f"⚡ Zone Model Picks — {today}"
    _send_email(subject, full_report, today=today)


if __name__ == "__main__":
    main()
