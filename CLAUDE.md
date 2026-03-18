# CLAUDE.md — AI Assistant Guide for the Supervisor Codebase

## Overview

This is a **multi-agent trading supervisor** that orchestrates 3 specialized trading bots (crypto, meme tokens, US stocks) using Claude AI as the "brain." The supervisor runs as a 5-minute event loop, gathering market intelligence, calling Claude Sonnet for portfolio decisions, and writing command files that each bot reads and executes.

The system is **production-only** — no test suite, no CI/CD. Runtime safety is enforced through anomaly detection, bounded self-healing, escalation arbitration, and immutable audit logs.

---

## Repository Structure

```
supervisor/
├── supervisor.py                 # Main entry point — 5-min orchestrator loop
├── supervisor_brain.py           # Claude Sonnet unified brain (portfolio decisions)
├── supervisor_escalation.py      # Opus escalation bus (bot-supervisor negotiation)
├── supervisor_selfheal.py        # Opus-powered auto-remediation of anomalies
├── supervisor_anomaly.py         # Real-time anomaly detection engine
├── supervisor_portfolio.py       # Portfolio aggregator (reads all 3 bot state files)
├── supervisor_regime.py          # Global market regime classification (RISK_ON/NEUTRAL/RISK_OFF)
├── supervisor_memory.py          # Brain outcome memory + decision quality scoring
├── supervisor_morning_brief.py   # Pre-market intelligence brief (9 AM ET weekdays)
├── supervisor_allocation.py      # Sharpe + Kelly allocation recommendations
├── supervisor_correlation.py     # BTC/SPY correlation collapse detection
├── supervisor_signals.py         # Fear/Greed + on-chain signals
├── supervisor_news.py            # Financial news headline fetcher
├── supervisor_calendar.py        # Economic calendar (high-impact events)
├── supervisor_social.py          # Stocktwits crowd sentiment
├── supervisor_execution.py       # Execution log reader (recent trades)
├── supervisor_unified.py         # Cross-bot portfolio view builder
├── supervisor_report.py          # Generates supervisor_report.json
├── supervisor_settings.py        # Centralized .env config loader (import first)
├── supervisor_telegram.py        # Telegram bot — push alerts + remote commands
├── supervisor_web.py             # Web dashboard + REST API (Flask, port 8080)
├── golive_tracker.py             # Go-live readiness scorecard (5 criteria, 0-100)
├── status.py                     # Human-readable CLI dashboard
├── watchdog.py                   # Process supervisor (restarts supervisor.py on crash)
├── global_markets.py             # Global market data aggregator
└── requirements.txt              # anthropic, requests, alpaca-py, flask
```

---

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env   # (no .env.example exists yet — see below)

# Run the main supervisor (loops every 5 min)
python supervisor.py

# Keep it alive with watchdog (restarts on crash)
python watchdog.py

# View live dashboard
python status.py

# Check go-live readiness score
python golive_tracker.py
```

---

## Environment Configuration

All settings are loaded by `supervisor_settings.py` on import via `_load(".env")`. Every module that needs config should `import supervisor_settings as S` and use `S.CONSTANT`.

### Required `.env` variables:

```bash
# Claude API (required)
ANTHROPIC_API_KEY=sk-ant-...

# Alpaca live account (required for regime data + stock bot state)
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...

# Bot state file paths (Windows paths in production)
ENZOBOT_STATE=C:\Projects\enzobot\state.json
ENZOBOT_BRAIN=C:\Projects\enzobot\brain_state.json
SFMBOT_STATE=C:\Projects\sfmbot\sfm_state.json
ALPACA_STATE=C:\Projects\alpacabot\alpaca_state.json
```

### Optional `.env` variables (defaults shown):

```bash
# Capital baselines (USD)
ENZOBOT_BASELINE=4000.00       # Crypto core growth engine
SFMBOT_BASELINE=2350.87        # Solana meme token booster
ALPACA_BASELINE=500.00         # Stock compounder

# Risk thresholds
KILL_SWITCH_DD_PCT=10.0        # Hard stop — all bots DEFENSE
BTC_TREND_RISK_OFF_PCT=-5.0    # BTC 7d return below this → RISK_OFF
BTC_TREND_RISK_ON_PCT=3.0      # BTC 7d return above this → RISK_ON
SPY_VOL_RISK_OFF_PCT=2.5       # SPY 10d vol above this → RISK_OFF flag

# Timing
CYCLE_SEC=300                  # Supervisor loop interval (5 min)
BRAIN_INTERVAL_CYCLES=6        # Call Claude every N cycles (dynamic in stress)

# Claude model
CLAUDE_MODEL=claude-sonnet-4-6 # Sonnet for brain; escalations/selfheal always use Opus

# Telegram remote access (optional — leave blank to disable)
TELEGRAM_BOT_TOKEN=            # From BotFather (@BotFather on Telegram)
TELEGRAM_CHAT_ID=              # Your personal chat ID (send /start to your bot, then check)

# Web dashboard (optional)
WEB_ENABLED=true               # Set false to disable
WEB_HOST=0.0.0.0               # Bind address (0.0.0.0 = all interfaces)
WEB_PORT=8080                  # Dashboard port
WEB_SECRET=                    # Optional auth token (passed as X-Secret header or ?secret=)
```

---

## Architecture & Data Flow

```
watchdog.py
    └─> supervisor.py (every 5 min)
            ├── build_portfolio()          # Read 3 bot state JSON files
            ├── classify_regime()          # CoinGecko BTC + Alpaca SPY + Yahoo indices
            ├── run_brain() [every N cycles]
            │       ├── collect: news, calendar, social, signals, correlations, executions
            │       ├── call Claude Sonnet (supervisor_brain.py)
            │       └── write: kraken_cmd.json, sfm_cmd.json, alpaca_cmd.json
            ├── check_escalations()        # Read bot escalation requests → Opus → responses
            ├── run_selfheal() [if anomalies]  # Opus diagnoses + fixes parameters
            └── build_report()             # Write supervisor_report.json
```

### Claude Decision Format

The brain calls Claude Sonnet and expects this JSON response:

```json
{
  "kraken":  {"mode": "NORMAL|SCOUT|DEFENSE", "size_mult": 0.3-1.3, "entry_allowed": true, "reasoning": "..."},
  "sfm":     {"mode": "NORMAL|SCOUT|DEFENSE", "size_mult": 0.3-1.3, "entry_allowed": true, "reasoning": "..."},
  "alpaca":  {"mode": "NORMAL|SCOUT|DEFENSE", "size_mult": 0.3-1.3, "entry_allowed": true, "reasoning": "..."},
  "portfolio_note": "..."
}
```

### Bot Roles (Sleeves)

| Bot | Market | Role | Default Mode |
|-----|--------|------|-------------|
| **kraken** (EnzoBot) | Crypto (Kraken) | Core growth engine | NORMAL |
| **sfm** (SFMBot) | Solana meme tokens | Tactical booster | SCOUT |
| **alpaca** (AlpacaBot) | US stocks | Stability sleeve | NORMAL |

### Escalation Bus Flow

1. Bot Sonnet detects problem → writes `escalations/{bot}_request.json`
2. Supervisor reads request next cycle → calls Opus with full portfolio context
3. Opus prescribes action: `override_mode`, `adjust_param`, `confirm_supervisor`, `strategic_directive`, `opportunity_alert`, `capital_reallocation`, or `escalate_to_human`
4. Supervisor writes `escalations/{bot}_response.json`
5. Bot reads response on next cycle

---

## Key Conventions

### Naming

- **Module names**: `supervisor_<domain>.py` (e.g., `supervisor_brain.py`)
- **Functions**: `snake_case`
- **Private functions**: `_leading_underscore()` (not part of module's public API)
- **Constants**: `UPPER_CASE` (defined in `supervisor_settings.py`)
- **Data classes**: `PascalCase` (e.g., `PortfolioState`, `RegimeSnapshot`, `BrainDecision`)

### Code Patterns

**Dataclass-first**: All cross-module data uses frozen/unfrozen dataclasses, not dicts:

```python
@dataclass
class RegimeSnapshot:
    regime: str          # RISK_ON | NEUTRAL | RISK_OFF
    confidence: float    # 0.0-1.0
    btc_7d_pct: float
    spy_vol_10d: float
    vix: float
    global_sentiment: str   # BULLISH | BEARISH | MIXED
    notes: list[str]
```

**Functional pipeline**: No OOP classes (except dataclasses). Each module exposes a single public function:

```python
# supervisor_portfolio.py
def build_portfolio() -> PortfolioState: ...

# supervisor_regime.py
def classify_regime() -> RegimeSnapshot: ...

# supervisor_brain.py
def run_brain(portfolio, regime, ...) -> BrainDecision: ...
```

**Defensive fail-open**: Every external call (Claude API, file I/O, HTTP) is wrapped with try/except that returns safe defaults — **never propagate exceptions upward**:

```python
try:
    raw = _call_claude(prompt)
    return _parse_response(raw)
except Exception as e:
    log.error(f"Claude call failed: {e} — using safe defaults")
    return BrainDecision(SAFE_DEFAULTS)
```

**Bounded remediation**: Self-healing never makes unbounded parameter changes. All adjustments are constrained by `SAFE_BOUNDS` in `supervisor_selfheal.py`.

**UTF-8 everywhere**: All file I/O uses explicit `encoding="utf-8"` (Windows compatibility — system may be cp1252):

```python
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
```

### Logging

Every module uses the standard pattern:

```python
import logging
log = logging.getLogger(__name__)
```

Format (set in `supervisor.py`): `[HH:MM:SS][module_name] message`

### JSON File I/O Conventions

| File | Purpose | Format |
|------|---------|--------|
| `supervisor_report.json` | Latest portfolio snapshot | JSON object |
| `supervisor_history.jsonl` | Cycle-by-cycle history | JSONL (append-only) |
| `brain_outcomes.jsonl` | Decision quality scores | JSONL (append-only) |
| `escalation_log.jsonl` | Opus escalation audit | JSONL (append-only) |
| `selfheal_log.jsonl` | Self-healing actions | JSONL (append-only) |
| `commands/kraken_cmd.json` | Brain → EnzoBot | JSON object |
| `commands/sfm_cmd.json` | Brain → SFMBot | JSON object |
| `commands/alpaca_cmd.json` | Brain → AlpacaBot | JSON object |
| `escalations/{bot}_request.json` | Bot → Supervisor | JSON object |
| `escalations/{bot}_response.json` | Supervisor → Bot | JSON object |

---

## Remote Access

### Telegram Bot (`supervisor_telegram.py`)

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env` to enable.

**Commands** (send in your Telegram chat with the bot):

| Command | Description |
|---------|-------------|
| `/status` | Portfolio equity, PnL, DD, sleeve breakdown |
| `/regime` | Current market regime + BTC/SPY data |
| `/brief` | Latest morning brief (truncated to 3800 chars) |
| `/mode <bot> <MODE>` | Override bot mode (e.g. `/mode kraken DEFENSE`) |
| `/selfheal` | Request self-heal scan on next cycle |
| `/stop` | Activate emergency stop (writes `EMERGENCY_STOP.txt`) |
| `/help` | List all commands |

**Push alerts** (sent automatically by `supervisor.py`):
- Regime change (e.g. NEUTRAL → RISK_OFF)
- Kill switch activated
- Brain puts any bot into DEFENSE mode
- HIGH severity anomaly detected
- Self-heal actions applied
- Morning brief ready

**Setup**:
1. Message @BotFather on Telegram → `/newbot` → copy token to `TELEGRAM_BOT_TOKEN`
2. Start a chat with your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`
3. Set `TELEGRAM_CHAT_ID` in `.env`

### Web Dashboard (`supervisor_web.py`)

Starts automatically on `http://0.0.0.0:8080` (configurable via `WEB_PORT`).

**Endpoints**:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | HTML dashboard (auto-refreshes every 30s) |
| `/api/status` | GET | JSON: portfolio, regime, sleeves, alerts |
| `/api/report` | GET | Full `supervisor_report.json` |
| `/api/brief` | GET | Morning brief as plain text |
| `/api/command` | POST | Override bot mode: `{"bot": "kraken", "mode": "DEFENSE"}` |
| `/api/stop` | POST | Activate emergency stop |

**Auth**: If `WEB_SECRET` is set, pass it as `X-Secret` header or `?secret=` query param.

**Remote access options**:
- LAN only: access via `http://<machine-ip>:8080`
- Remote: port-forward 8080 on your router, or use a VPN / ngrok / Cloudflare Tunnel

---

## Brain Decision Rules (Important for Claude)

When modifying `supervisor_brain.py` or the brain prompt, these rules are enforced:

1. **Portfolio DD > 8%** → all bots DEFENSE, entry_allowed=false
2. **Portfolio DD > 5%** → no NORMAL mode allowed, max SCOUT
3. **RISK_OFF regime** → max SCOUT for crypto/meme, NORMAL still ok for stocks
4. **RISK_ON regime** → NORMAL allowed if sleeve health is GOOD
5. **SFM is tactical only** → max SCOUT unless strong RISK_ON + good health
6. **Alpaca (stocks) = stability sleeve** → defaults NORMAL unless portfolio crisis
7. **size_mult must stay within ±0.2** of allocation engine suggestions per decision
8. **Correlation collapse active** → `apply_correlation_cap()` hard-overrides Claude's size_mult

---

## Anomaly Detection

`supervisor_anomaly.py` runs every cycle and detects:

| Anomaly | Description | Severity |
|---------|-------------|----------|
| `entry_drought` | No new positions for 5+ hours | HIGH |
| `adx_blocking` | ADX threshold rejecting all entries | HIGH |
| `attack_max_dd_tight` | Bot frozen despite gains (DD limit too tight) | MEDIUM |
| `stale_lock_file` | Bot process dead but lock file remains | HIGH |
| `parameter_churn` | Brain changing settings too rapidly | MEDIUM |
| `score_saturation` | Score calibration issue | MEDIUM |
| `frozen_cycle_counter` | Bot not advancing its cycle counter | HIGH |

Self-heal cooldown: 30 minutes per anomaly type (prevents thrashing).

---

## Go-Live Readiness Criteria

`golive_tracker.py` gates bot deployment. A bot is **go-live ready** when all criteria are met AND score ≥ 80:

| Criterion | Threshold | Weight |
|-----------|-----------|--------|
| Completed trades | ≥ 30 | 25% |
| Win rate | ≥ 52% | 20% |
| Avg win / avg loss ratio | ≥ 1.5 | 20% |
| Max drawdown | < 10% | 20% |
| Profitable days | ≥ 75% | 15% |

---

## Runtime Files (Gitignored)

These files exist at runtime but are NOT tracked in git:

```
.env                          # Credentials
supervisor_report.json        # Latest state
supervisor_history.jsonl      # Cycle history
brain_outcomes.jsonl          # Decision memory
brain_pending.json            # Pending evaluations
morning_brief*.txt            # Morning briefs
morning_briefs.jsonl          # Brief history
execution_log.jsonl           # Trade execution log
*_cache.json                  # API response caches
*_overrides.json              # Manual parameter overrides
commands/                     # Bot command files
escalations/                  # Escalation request/response files
*.log, logs/                  # Runtime logs
EMERGENCY_STOP.txt            # Kill switch trigger file
GOLIVE_READY.txt              # Go-live flag file
```

---

## Adding a New Module

1. Create `supervisor_<domain>.py`
2. Add `import logging; log = logging.getLogger(__name__)` at top
3. Import settings: `import supervisor_settings as S`
4. Define a primary public function returning a dataclass or dict
5. Wrap all external calls in try/except with safe fallback
6. Use `encoding="utf-8"` on all file I/O
7. Import and call it in `supervisor.py`

---

## Claude API Usage in This Codebase

```python
import anthropic
client = anthropic.Anthropic(api_key=S.ANTHROPIC_API_KEY)

# Normal brain decisions — Sonnet
response = client.messages.create(
    model=S.CLAUDE_MODEL,           # "claude-sonnet-4-6"
    max_tokens=1500,
    messages=[{"role": "user", "content": prompt}]
)

# Escalations and self-healing — always Opus
response = client.messages.create(
    model="claude-opus-4-6",        # Hard-coded, not configurable
    max_tokens=2000,
    messages=[{"role": "user", "content": prompt}]
)
```

**Do not change Opus escalation/selfheal calls to Sonnet.** Opus is intentionally used for high-stakes arbitration and anomaly remediation.

---

## Common Tasks

### Read the current portfolio state

```python
from supervisor_portfolio import build_portfolio
portfolio = build_portfolio()
print(portfolio.total_equity, portfolio.drawdown_pct)
```

### Check current market regime

```python
from supervisor_regime import classify_regime
regime = classify_regime()
print(regime.regime, regime.confidence, regime.btc_7d_pct)
```

### Manually trigger the brain

```python
from supervisor_brain import run_brain
from supervisor_portfolio import build_portfolio
from supervisor_regime import classify_regime
portfolio = build_portfolio()
regime = classify_regime()
decision = run_brain(portfolio, regime)
```

### Check anomalies

```python
from supervisor_anomaly import AnomalyDetector
detector = AnomalyDetector()
report = detector.detect(portfolio)
for anomaly in report.anomalies:
    print(anomaly.type, anomaly.severity)
```

---

## Known Constraints

- **Windows path defaults**: Default bot state paths are Windows-style (`C:\Projects\...`). On Linux, set `.env` paths accordingly.
- **No test suite**: There are no unit or integration tests. Validate changes by running `python status.py` and checking `supervisor_report.json`.
- **Concurrent file access**: Multiple bots may write `execution_log.jsonl` simultaneously. Retry logic exists in `supervisor_execution.py`.
- **State file age**: If a bot state file is stale (> 10 minutes), brain prompt will flag it. Check `state_age_sec` in `supervisor_unified.py`.
- **Brain interval is dynamic**: In crisis/stress regimes, the brain is called every cycle (5 min). In calm markets, every 6 cycles (30 min). Do not assume a fixed call rate.
