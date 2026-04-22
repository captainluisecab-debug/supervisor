# SESSION HANDOFF — 2026-04-19

**Last updated by:** Opus 4.6 (session 2026-04-15 through 2026-04-19)
**Handoff status:** COMPLETE — ready for Opus 4.7 or any new session
**Policy:** Runtime is local-only. No external API calls from any service. Operator review layer is human-in-the-loop, outside the runtime.

---

## 1. SYSTEM IDENTITY

**Who is Opus:** Chief architect, strategic reviewer, and code authority for a 3-bot live trading system managing ~$3,450 of REAL MONEY. Reports to the operator (Luis). All other components report to Opus or operate within Opus-defined rules.

**Responsible for:** Strategic 12h reviews (8AM/8PM), architecture decisions, code fixes, system integrity audits, live trading oversight.

**NOT allowed to:**
- Edit live bot files without maintenance window open
- Push to GitHub during active maintenance window
- Restart bots without operator elevated PowerShell
- Override Governor's live command authority
- Make ANY Anthropic API call without operator consent (standing rule)

---

## 2. CURRENT LIVE STATUS — ALL REAL MONEY

| Sleeve | Equity | PnL | Positions | Mode |
|---|---|---|---|---|
| Kraken | ~$3,546 | on new baseline | varies | CAUTIOUS early-phase (post recapitalization) |
| SFM/Solana | ~$1,831 | rpnl +$143.05 | 0 flat | LIVE |
| Alpaca | $535 | +$35.00 | 1 (QQQ or SPY) | LIVE (sleeping — weekend) |
| **TOTAL** | **~$6,012** | | | |

**Regime:** RISK_ON (100% conf) but TRENDING_DOWN on crypto — Kraken FORCE_FLAT active.
**Kill switch:** OFF. **Kernel:** PASS. **DD:** ~-6%.
**Alpaca:** Sleeping until Monday 09:30 ET (no weekend trading).
**Kraken + SFM:** Running 24/7 (crypto).

---

## 3. SESSION CHANGES (2026-04-15 through 2026-04-19)

### Major (2026-04-15/16)
- **Paper-to-live cutover ALL 3 bots** — system was 100% paper since inception
- **Phase A-F upgrades:** pair-scout closure, outcome analyzers, adaptive brains, selfheal Phase 2, capital hardening, Opus strategic layer
- **Alpaca first live trades:** NVDA +$5.40, TSLA +$10.81, MSFT +$10.30 (100% WR)
- **SFM first live trade:** +$105.20 take-profit on 900M SFM tokens

### Refinements (2026-04-16/17)
- **Small Capital Compounder config:** stop ATR 2.2->0.7, trail 2.0->1.5, RSI_MIN_SELL 42->35, TIME_STOP 12h->18h, quick_profit 1%->0.7%/15min
- **Dynamic EXIT_FLOOR:** DOWN=55, RANGING=50, UP=48 (regime-adaptive, proven from 231-exit history)
- **MIN_SCORE locked at 80** in .env defaults (brain cannot wipe on mode transition)
- **Kraken dust cleanup** — converted on exchange, cleaned from state
- **Morning brief fires 8:02 AM + 8:02 PM ET** (was 9AM weekday only)
- **Tactical brain layer:** light local model (Sonnet-class analog) for adaptive brain, selfheal, and strategic review

### Solana multi-pair (2026-04-17/18)
- **New multi-pair engine** (solana_multi_engine.py) replaces old single-token sfm_engine
- **6 pairs configured:** SOL/USDC, JUP/USDC, PYTH/USDC, BONK/USDC, SFM/USDC (active) + JITOSOL/USDC (disabled — routing issues)
- **JitoSOL accounting fixed:** was showing -$248 fake loss, corrected to +$45.52 real profit
- **3-second delay between pair fetches** to avoid GeckoTerminal 429 rate limiting
- **Supervisor fully synced** to solana_state.json (was reading old sfm_state.json)

### Baselines (current)
- Kraken: $3,545.78 (was $1,689.00; operator recapitalization 2026-04-21 to professional-grade working capital)
- SFM/Solana: $1,846.70
- Alpaca: $500.00

### Deploy config
- Kraken `TARGET_DEPLOY_PCT`: 0.37 (held constant from $600-deposit era; at $3,545.78 capital this targets $1,312 deployed / 5 positions = ~$262 per position — professional-but-disciplined sizing; preserves all Compounder, S1, K1, K2, K3, DUST-FILTER, ENTRY-CONFIRM, RECONCILE protections)

---

## 4. KEY ARCHITECTURE

```
Governor (sole command writer) -> kraken_cmd / sfm_cmd / alpaca_cmd
Kernel (invariant gate) -> PASS/HALT before every Governor cycle
Hermes (observer + advisory) -> aggregates universe, detects violations
Adaptive Brain (conditional Opus calls) -> refines params when performance dips
Selfheal (Phase 2) -> Opus diagnosis + rate-limited actions (3 restart/day, 2 cmd/day, 6 total/day)
Strategic Review (12h) -> writes opus_strategic_directive.json -> Governor reads
Outcome Analyzers (3 bots) -> closed feedback loops -> gate entry decisions
```

**Dynamic EXIT_FLOOR:** DOWN=55, RANGING=50, UP=48 — Governor writes dominant_regime to command file, engine reads it.

**Small Capital Compounder:** STOP_ATR=0.7, TRAIL=1.5, QUICK_PROFIT=0.7%/15min, RSI_MIN_SELL=35, TIME_STOP=18h, MAX_OPEN=5, MIN_SCORE=80.

---

## 5. TRUTH SOURCES

| What | Authoritative |
|---|---|
| Kraken positions | Kraken exchange via ccxt |
| Solana positions | On-chain wallet EN6eSG...T4p via RPC |
| Alpaca positions | Alpaca API account 100057000 |
| Commands | commands/{kraken,sfm,alpaca}_cmd.json |
| Fills | execution_log.jsonl |
| Outcome learning | score_adjustments.json (K), sfm_score_adjustments.json (S), alpaca_score_adjustments.json (A) |
| Strategic directive | opus_strategic_directive.json (expires 14h) |
| Stale/ignore | brain_outcomes.jsonl, system_lessons.jsonl, morning_briefs.jsonl |

---

## 6. STANDING RULES

- **Session-end:** push all 5 repos to GitHub + refresh this handoff file
- **External API calls:** prohibited. Runtime is local-only across all services and layers
- **Maintenance window:** required for any live bot file edit
- **No manual wallet actions** without telling Opus first (causes state/wallet splits)
- **No manual trades** on any exchange — system handles entries/exits
- **Baselines must be updated** when capital is deposited or withdrawn

---

## 7. NEXT-SESSION LAUNCH PATH

1. Read CLAUDE.md (operator law)
2. Read this file (SESSION_HANDOFF.md)
3. Read supervisor_report.json (live state)
4. Read opus_strategic_directive.json (current directives)
5. Check kernel_audit.jsonl last line (PASS?)
6. Check all 4 services running
7. Check: is crypto regime still TRENDING_DOWN or has it flipped?
8. Check: did Solana multi-pair engine enter any positions over the weekend?
9. Monday: Alpaca wakes at 09:30 ET — watch for new entries with $50 sizing

---

## 8. TOP PRIORITIES

1. **WATCH: Crypto regime flip** — Kraken + SFM waiting for TRENDING_UP to deploy capital
2. **WATCH: Solana entries** — 5 pairs scanning, $1,509 USDC ready, RSIs deeply oversold
3. **MONDAY: Alpaca market open** — brain sized up to $50/trade, seek MSFT/TSLA/NVDA entries
4. **VALIDATE: Small Capital Compounder** — only 5 trades since config change, need 20+ to prove expectancy
5. **DEFERRED: SFM peak_equity persistence** — DD calc resets on restart
6. **DEFERRED: Orphan folders** C:\alpacabot, C:\sfmbot, C:\enzobot (code only, .env deleted)
7. **DEFERRED: strip ANTHROPIC_API_KEY + remote SDK imports** from enzobot/.env, supervisor/.env, and any remaining source refs — enforce local-only by absence (keys should also be rotated regardless, since they were visible in session output)

---

## 9. KNOWN ISSUES

- **Kraken BTC dust** (0.00004 BTC ~$3) — below Kraken minimum, can't sell, harmless
- **SFM rpnl** in state file may drift from wallet truth — engine tracks trades but SOL price changes are not reflected in rpnl
- **Override file missing safety params** when brain is in OBSERVE mode — .env defaults (80/48) cover this, but brain should ideally always write them
- **Solana wallet has ~$471 SOL** that the bot tracks in equity but can't deploy directly (needs USDC for entries)
- **BTC $6.15 on Bitcoin chain** in Phantom — separate from bot, not tradeable on Solana

---

## 10. REPOS

| Repo | Branch | Latest Commit | Pushed |
|---|---|---|---|
| supervisor | master | d0ccace + several | YES |
| enzobot | main | a27a552 + several | YES |
| sfmbot | master | 0363f16 + several | YES |
| alpacabot | master | ae3eeb5 | YES |
| memory/openclaw | main | 69e7fa9 | YES |

All repos synced with GitHub as of session end.

---

## 11. MODEL ARCHITECTURE (LOCAL-ONLY)

| Layer | Cadence | Engine class | Role |
|---|---|---|---|
| Operator review layer | On-demand | Operator-gated human-in-the-loop session | Architecture, audits, strategic approvals. Outside the runtime loop; not a runtime dependency. |
| 12h strategic review | Every 12h | Light-to-medium local model | Directive generation |
| Adaptive brain (3 bots) | Per-cycle, conditional | Light local model | Tactical param nudges |
| Selfheal | Event-driven | Light local model | Anomaly diagnosis |
| Governor / Kernel / Engines | Every cycle | Deterministic (no model) | Rules + invariants |

Rule: reasoning depth at the edge (operator layer), reasoning speed in the loop (light local). No runtime component depends on any external or remote service.
