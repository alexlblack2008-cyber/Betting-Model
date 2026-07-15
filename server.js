const express = require("express");
const path    = require("path");
const fs      = require("fs");
const dotenv  = require("dotenv");
dotenv.config();

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const BASE_URL   = process.env.BASE_URL || "http://localhost:4242";
const LEDGER_PATH = path.join(__dirname, "zone_model", "ledger.json");

// ── Ledger helpers ───────────────────────────────────────────────────────────

function loadLedger() {
  try {
    if (fs.existsSync(LEDGER_PATH)) {
      return JSON.parse(fs.readFileSync(LEDGER_PATH, "utf8"));
    }
  } catch {}
  return [];
}

function weekBounds() {
  const today  = new Date();
  const day    = today.getDay();                 // 0=Sun,1=Mon,...
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((day + 6) % 7));
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const fmt = d => d.toISOString().slice(0, 10);
  return { start: fmt(monday), end: fmt(sunday) };
}

// ── API routes ───────────────────────────────────────────────────────────────

// All bets (full ledger)
app.get("/api/picks", (req, res) => {
  const entries = loadLedger();
  res.json(entries.slice().reverse());   // newest first
});

// This week only
app.get("/api/picks/week", (req, res) => {
  const { start, end } = weekBounds();
  const entries = loadLedger().filter(e => e.bet_date >= start && e.bet_date <= end);
  res.json(entries.slice().reverse());
});

// Summary stats
app.get("/api/summary", (req, res) => {
  const all      = loadLedger();
  const { start, end } = weekBounds();
  const week     = all.filter(e => e.bet_date >= start && e.bet_date <= end);
  const settled  = (entries) => entries.filter(e => e.outcome !== "pending");
  const wins     = (entries) => entries.filter(e => e.outcome === "won");
  const pnl      = (entries) => entries.reduce((s, e) => s + (e.pnl || 0), 0);
  const roi      = (entries) => {
    const s = settled(entries);
    return s.length ? pnl(s) / (s.length * 100) * 100 : 0;
  };

  res.json({
    allTime: {
      total:   all.length,
      settled: settled(all).length,
      wins:    wins(settled(all)).length,
      losses:  settled(all).filter(e => e.outcome === "lost").length,
      pushes:  settled(all).filter(e => e.outcome === "push").length,
      pnl:     +pnl(settled(all)).toFixed(2),
      roi:     +roi(all).toFixed(2),
    },
    thisWeek: {
      total:   week.length,
      settled: settled(week).length,
      wins:    wins(settled(week)).length,
      losses:  settled(week).filter(e => e.outcome === "lost").length,
      pushes:  settled(week).filter(e => e.outcome === "push").length,
      pnl:     +pnl(settled(week)).toFixed(2),
      roi:     +roi(week).toFixed(2),
      pending: week.filter(e => e.outcome === "pending").length,
    },
    weekRange: { start, end },
  });
});

// Settle a pick: POST /api/settle { home_team, away_team, bet_date, actual_runs }
app.post("/api/settle", (req, res) => {
  const { home_team, away_team, bet_date, actual_runs } = req.body;
  if (!home_team || !away_team || !bet_date || actual_runs == null) {
    return res.status(400).json({ error: "home_team, away_team, bet_date, actual_runs required" });
  }
  const runs = Number(actual_runs);
  if (isNaN(runs) || runs < 0) {
    return res.status(400).json({ error: "actual_runs must be a non-negative number" });
  }

  const entries = loadLedger();
  const entry = entries.find(e =>
    e.home_team === home_team &&
    e.away_team === away_team &&
    e.bet_date  === bet_date  &&
    e.outcome   === "pending"
  );

  if (!entry) return res.status(404).json({ error: "Pending pick not found" });

  const STAKE = 100, WIN_PAYOUT = STAKE / 1.10;
  const rec = entry.recommendation;
  const total = entry.market_total;
  let outcome;
  if (rec === "OVER")  outcome = runs > total ? "won" : runs === total ? "push" : "lost";
  else                 outcome = runs < total ? "won" : runs === total ? "push" : "lost";

  entry.actual_runs = runs;
  entry.outcome     = outcome;
  entry.pnl         = outcome === "won" ? +WIN_PAYOUT.toFixed(2) : outcome === "lost" ? -STAKE : 0;
  entry.settled_at  = new Date().toISOString();

  try {
    fs.writeFileSync(LEDGER_PATH, JSON.stringify(entries, null, 2));
    res.json({ outcome, pnl: entry.pnl, entry });
  } catch(e) {
    res.status(500).json({ error: "Failed to save ledger" });
  }
});

// ── Dashboard (single-page) ──────────────────────────────────────────────────

app.get("/picks", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "picks.html"));
});

// ── Root ─────────────────────────────────────────────────────────────────────

app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

const PORT = process.env.PORT || 4242;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
