# 📓 Awesome-Trader — Decision & Change Log

> **Purpose:** Persistent record of every major decision, bug finding, strategy change, and implementation session.
> Stored in the GitHub repo so it survives app deletions, machine changes, and long gaps between sessions.
> Future AI sessions or developers should read this file FIRST before touching anything.

---

## How to Use This Log

- Every entry is dated, titled, and tagged with `[BUG]`, `[STRATEGY]`, `[FIX]`, `[DISCUSSION]`, or `[DECISION]`
- The most recent entry is at the TOP
- Each entry links to relevant files so you can trace changes directly in the code

---

## Session: 2026-08-21 — Scalping Engine Overhaul

### Context
User goal: **Maximum trades and gains on 1m BTC candles.** Bot hosted on GCP (project: `trading-shishab`, VM: `awesome-trader`, zone: `us-central1-a`). Auto-deploys on push to `main` via GitHub Actions ([deploy.yml](../.github/workflows/deploy.yml)).

---

### [BUG] Historical Replay Corrupts Live State Machine

**Discovered:** Live GCP logs showed all state machine events (`SWEPT_HIGH`, `SHORT_SETUP_FORMED`, `REJECTED`) firing at the exact same timestamp `2026-08-20T19:40:06` — all in one second.

**Root cause:** On startup, all 1000 historical 1m candles are fed through `_evaluate_1m_logic()` with `is_historical=True`, but the full state machine (SWEPT/WAITING/SETUP_FORMED transitions) runs anyway. This causes ~50+ rapid state transitions that leave the live state in an unpredictable mid-sequence position.

**Location:** `backend/logic_engine.py` — `_evaluate_1m_logic()` function, candle processing loop.

**Fix decided:** Add early return at top of `_evaluate_1m_logic` when `is_historical=True`, after warming up HMM feature buffer only. Live state starts clean from `WAITING`.

---

### [BUG] Body Ratio 0.50 Filter Killing All Setups at Key Levels

**Discovered:** GCP logs showed:
```
SWEPT 4H HIGH (72800.0000) → Setup candle REJECTED: body ratio 0.02
SWEPT 4H HIGH (72800.0000) → Setup candle REJECTED: body ratio 0.09
SWEPT 4H HIGH (72800.0000) → Setup candle REJECTED: body ratio 0.18
SWEPT 4H HIGH (72800.0000) → Setup candle REJECTED: body ratio 0.20
```
5 out of 6+ approaches of 72800 had body ratio < 0.50 and were rejected.

**Root cause:** Code requires the confirmation candle (after a level sweep) to have body_ratio >= 0.50. At key resistance/support levels, price almost always creates small-bodied doji/indecision candles — that IS the rejection signal.

**Fix decided:** Replace static 0.50 threshold with HMM-regime-dynamic thresholds.

---

### [BUG] 15m SWEPT_HIGH Stuck in Reset Loop

**Discovered:** Fresh logs (last 30 min of live trading) showed:
```
20:11:00 SWEPT 15m HIGH (72748.1000) → SWEPT_HIGH
20:24:02 SWEPT 15m HIGH (72748.1000) → SWEPT_HIGH   ← 13 min later, same level
20:25:01 SWEPT 15m HIGH (72748.1000) → SWEPT_HIGH
20:26:02 SWEPT 15m HIGH (72748.1000) → SWEPT_HIGH
20:27:03 SWEPT 15m HIGH (72748.1000) → SWEPT_HIGH
```
5 detections, 0 trades. State resets to WAITING after TTL expires, then immediately re-detects the same sweep.

**Fix decided:**
1. Extend TTL (regime-dynamic: 6–15 candles)
2. After TTL expires on a level, add a `cooldown_level` that prevents re-detection of the same level for N candles

---

### [BUG] HMM Infinite Retraining Loop + Not Converging

**Discovered:**
```
Starting HMM async training on 1000 samples...
Saved HMM model. HMM training complete.
Starting HMM async training on 1000 samples...  ← immediately again
WARNING: Model is not converging. Delta = -56.9
WARNING: Model is not converging. Delta = -16.3
```
Retraining every 2–3 seconds, never converging. Regime labels are garbage.

**Root cause:** `len(state["hmm_features"]) >= 1000` is always true once buffer fills. Every candle tick triggers a retrain. The `is_training` flag clears too fast.

**Fix decided:** Add `last_hmm_train_time` timestamp, retrain max once per 15 minutes. Add `regime_reliable` boolean — only True if last training converged successfully.

---

### [BUG] Volume Surge Gate (1.3–1.5x) Silently Blocking All Triggers

**Discovered:** Intrabar trigger requires `vol_surge` (1.3–1.5x average) before firing. Institutional rejections at key levels are often quiet. Confirmed zero `TRIGGERED` messages in any log.

**Fix decided:** Replace static volume gate with HMM-regime-dynamic volume requirement.

---

### [BUG] EV Veto Bootstrapping Deadlock

**Discovered:** When no trade history, `EV=0` → trade blocked. The bot needs trades to build EV, but blocks trades until EV is positive.

**Fix decided:** Only apply EV veto when `n_trades >= 15`. Below 15, allow all signals through.

---

### [DECISION] HMM-Dynamic Quality Filters (Core Architecture Change)

**Philosophy:** Instead of static hard filters or no filters — use the HMM regime to dynamically set filter strictness.

| HMM Regime | regime_reliable | Body Ratio Min | Volume Required | TTL |
|---|---|---|---|---|
| Liquidation Cascade | True | 0.00 | No | 6 |
| Trend | True | 0.20 | No | 10 |
| Chop | True | 0.30 | Yes (1.2x) | 5 |
| Any | False (HMM broken) | 0.20 | No | 8 |

---

### [STRATEGY] New: EMA Cross 1m Momentum Scalp (S13)

**Rationale:** The sweep-based state machine only fires at extreme levels. BTC makes many 1m momentum moves inside the 4H range. This strategy captures those.

**Logic:** 1m EMA20 crosses above/below EMA50 + RSI not in opposing extreme + in any trading session → enter with fixed 0.15% TP.

**Expected frequency:** 5–10 signals/day, independent of sweep state machine.

**Added as:** `S13_EMA_Cross_Scalp`

---

### [DECISION] Key Parameter Changes

| Parameter | Old Value | New Value | Reason |
|---|---|---|---|
| Body ratio min | 0.50 (static) | HMM-dynamic (0.0–0.30) | Regime-aware quality |
| Volume surge gate | 1.3–1.5x (hard gate) | HMM-dynamic (optional) | Level rejections are often quiet |
| TTL | 4 candles (static) | HMM-dynamic (5–15 candles) | Market-condition-aware patience |
| HMM retrain interval | Every candle (bug) | Every 15 minutes | Stops infinite loop |
| EV veto min trades | 0 (always active) | 15 trades | Fix bootstrapping deadlock |
| Max concurrent positions | 2 | 5 | More scalp parallelism |
| S12 max_margin_adds | 3 | 1 (temporary) | Safety during first 24h rollout |

---

## Session: 2026-08-20 — Platform Investigation

### [DISCUSSION] Hosting Confirmed: Google Cloud Platform
- **Project:** `trading-shishab`
- **VM:** `awesome-trader`, zone `us-central1-a`
- **Auto-deploy:** push to main → GitHub Actions → SSH → git pull → npm build → pip install → systemctl restart
- **Billing:** No extra charges for pushes — existing VM just gets updated code

---

## Architecture Reference (as of 2026-08-21)

### Active Strategies
| Name | Leverage | SL | Notes |
|---|---|---|---|
| S11_Fixed_Pct_TP | 50x | Yes (structure-based) | Directional sweeps, safe |
| S12_NoSL_MarginBoost | 400x | No (liquidation-based) | High-risk, cap margin_adds=1 during rollout |
| S13_EMA_Cross_Scalp | TBD | Yes | NEW — 1m momentum scalp |

### File Map
```
backend/
  logic_engine.py   ← All trading logic, state machine, HMM integration
  hmm_engine.py     ← HMM model wrapper (GaussianHMM via hmmlearn)
  risk_engine.py    ← EV calculation, Kelly fraction, historical stats
  mexc_client.py    ← MEXC WebSocket, kline feed, funding rate
  main.py           ← FastAPI app, WebSocket broadcast

.github/workflows/
  deploy.yml        ← CI/CD: push to main → auto-deploy to GCP VM

docs/
  TRADING_DECISIONS_LOG.md  ← THIS FILE — read before touching anything
```

---

*Last updated: 2026-08-21 | Session ID: ed47c813 | AI: Antigravity*
