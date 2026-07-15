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
