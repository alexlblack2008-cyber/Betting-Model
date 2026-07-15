"""
Cron entry point — called once daily by the CCR Routine trigger.

Runs the full Zone Model daily pipeline and prints the report.
The CCR trigger captures stdout and sends it as a push notification + email.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from daily_picks import run_daily
from ledger import weekly_pnl_report
from datetime import date

def main():
    today = date.today().isoformat()
    print(f"[Zone Model] Running daily picks for {today} …\n")

    report = run_daily(today, log_to_ledger=True)
    print(report)

    # On Mondays, also print last week's full P&L
    if date.today().weekday() == 0:
        print("\n" + "=" * 56)
        print("  MONDAY WEEKLY RECAP")
        print("=" * 56)
        print(weekly_pnl_report())

if __name__ == "__main__":
    main()
