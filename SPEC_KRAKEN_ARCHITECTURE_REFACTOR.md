# SPEC: Kraken Architecture Refactor — MDP / Controllers / Executors

**Status:** DRAFT v1.0 — planning, NOT YET BUILT.
**Date:** 2026-04-28
**Author:** Opus
**Sensitivity:** 9/10 (touches every live trading path).
**Approval gate:** operator review → approve / revise / reject → only then build phased migration.

---

## Why

Operator directive 2026-04-28: "build a cleaner live trading chassis" with:
- Market Data Provider (single access point for candles, trades, order book)
- Controllers (modular long-running strategy logic)
- Executors (self-managed order placement, refresh, cancel, position lifecycle)
- Cleaner separation strategy/control vs execution

Current state: `engine.py` is a 1,300+-line monolith mixing data fetch, strategy decision, gate cascade, order placement, and position management. The path classifier and trader added on top are well-isolated (separate files) but the legacy hot path is intertwined.

The refactor is RIGHT — but it cannot be done in one session on a live system without significant risk. This doc lays out a phased migration. Each phase ships independently and is operator-approved. Discipline: spec → build → shadow → live or kill, applied at each phase.

---

## Target architecture

```
                    ┌────────────────────────────────────────┐
                    │   MarketDataProvider (singleton)        │
                    │   - REST: fetch_ohlcv(pair, tf, lookback) │
                    │   - REST: fetch_orderbook(pair, depth)   │
                    │   - REST: fetch_recent_trades(pair, since)│
                    │   - WebSocket: live ticker subscribe     │
                    │   - Archive: write-through to disk       │
                    │   - Cache: in-memory hot data            │
                    └────────────┬───────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                          │
            ┌───────▼──────────┐    ┌─────────▼─────────┐
            │ Controller       │    │ Controller        │
            │ ClassifierKraken │    │ TraderKraken      │
            │ (perception)     │    │ (decision logic)   │
            │ - run_once()     │    │ - run_once()      │
            │ - state cached   │    │ - reads classifier │
            │   to disk        │    │   output + price   │
            └──────────────────┘    │ - emits orders     │
                                     │   to ExecutorPool  │
                                     └────────┬───────────┘
                                              │
                                  ┌───────────▼────────────┐
                                  │   ExecutorPool          │
                                  │   - max_executors=N     │
                                  │   - lifecycle mgmt      │
                                  └───────────┬────────────┘
                                              │
                          ┌──────────────┐    │    ┌──────────────┐
                          │ PositionExec │◄───┴───►│ PositionExec │
                          │ BTC/USD      │         │ NEAR/USD     │
                          │ - entry      │         │ - entry      │
                          │ - manage     │         │ - manage     │
                          │ - scale_out  │         │ - scale_out  │
                          │ - exit       │         │ - exit       │
                          │ - stop trail │         │ - stop trail │
                          └──────────────┘         └──────────────┘

                    [ Safety stack runs alongside, same priority ]
                    Operator Pause | Sentinel | Governor | Kernel
```

## Component contracts

### MarketDataProvider (`enzobot/mdp.py`)
Single source of truth for all Kraken data.

```python
class MarketDataProvider:
    def fetch_ohlcv(self, pair: str, timeframe_min: int, lookback: int = 200) -> List[Candle]
    def fetch_orderbook(self, pair: str, depth: int = 10) -> OrderBookSnapshot
    def fetch_recent_trades(self, pair: str, since_ts: int = None) -> List[Trade]
    def get_live_price(self, pair: str) -> float           # WebSocket-fed
    def get_24h_volume(self, pair: str) -> float           # ticker
    def get_spread(self, pair: str) -> float               # ticker
    
    # Internal: every call write-throughs to data/market_archive/
    # Cache layer: 60s TTL on REST data
```

### Controller (`enzobot/controllers/{name}_controller.py`)
Long-running strategy module. One per role.

```python
class Controller(ABC):
    name: str
    pair: str  # or 'universe' for cross-pair logic
    
    @abstractmethod
    def run_once(self, mdp: MarketDataProvider, state: ControllerState) -> ControllerOutput
    
    @property
    def output_destination(self) -> str:  # e.g. 'classifier_log', 'trader_decisions'
```

Initial controllers:
- **`KrakenClassifierController`** — runs `kraken_path_classifier.classify_path` per pair per cycle. Output → archive.
- **`KrakenTraderController`** — reads classifier output + position state + capital. Emits `OrderIntent` objects to ExecutorPool.

### Executor (`enzobot/executors/{type}_executor.py`)
Self-managed order/position lifecycle.

```python
class PositionExecutor:
    pair: str
    intent: OrderIntent  # entry params (size, stop, take_profit, exit_logic)
    state: PositionState  # OPEN / MANAGING / SCALING_OUT / EXITING / CLOSED
    
    def step(self, mdp: MarketDataProvider, broker: Broker) -> StepResult:
        # Each cycle, executor decides: place order? refresh? cancel? scale? exit?
        # Owns its own stop trail, take-profit logic, regime-shift exit
```

Lifecycle states:
- `PENDING_ENTRY` → broker submits limit/market order, watches fill
- `OPEN` → manages stop, trail, take-profit, scale-out triggers
- `EXITING` → exit order placed, watches fill
- `CLOSED` → reports outcome to learner, removes self from pool

ExecutorPool:
```python
class ExecutorPool:
    max_executors: int  # = max_open_positions
    
    def add(self, executor: PositionExecutor) -> bool
    def step_all(self, mdp, broker) -> List[StepResult]
    def force_flatten(self, reason: str) -> None  # governor / operator hook
```

### Safety stack — preserved
- **OperatorPause** (sacrosanct, can override anything)
- **Sentinel** (universe restriction, MAX_POS, deploy_pct caps)
- **Governor** (regime FLAT → ExecutorPool.force_flatten + entry_allowed=False)
- **Kernel** (invariant validation each cycle)

These remain as a SEPARATE LAYER outside MDP/Controllers/Executors. They can pause/disable Controllers and force-close Executors but do not reach into their internal state.

---

## Migration phases

### Phase 1 (DONE 2026-04-28): Data archive foundation
- ✓ `market_data_archive.py` write-through on every fetch
- ✓ Documentation: `MARKET_DATA_ARCHIVE_LAYOUT.md`
- ✓ Wired into existing engine.py at all 4 OHLCV fetch sites
- ✓ Trader decision archive

This is necessary FIRST so that any future refactor doesn't lose data.

### Phase 2 (next): MarketDataProvider
- Build `enzobot/mdp.py` wrapping `data_kraken.py` + KrakenCcxtBroker for ticker + WebSocket
- Add `fetch_orderbook` and `fetch_recent_trades` (currently MISSING — Kraken Depth + Trades endpoints)
- Replace direct `from data_kraken import fetch_ohlc` calls in `engine.py` with `mdp.fetch_ohlcv()`
- Same archive write-through but centralized
- Estimated: 4-6 hours, ~200 lines of new code, ~20 lines edited in engine.py
- Risk: low (functional equivalent)
- Validation: 24h shakedown, no anomalies, archive growing

### Phase 3 (after Phase 2 stable): Controllers
- Refactor `kraken_path_classifier.py` invocation into `KrakenClassifierController.run_once()`
- Refactor `kraken_trader.py` invocation into `KrakenTraderController.run_once()`
- Engine.py shrinks: just orchestrates `mdp → controllers → pool`
- Estimated: 6-10 hours
- Risk: medium (touches hot path)
- Validation: 7-day shadow side-by-side with current path, then flip live

### Phase 4 (after Phase 3): Executors
- Extract position lifecycle (entry, manage, exit, stop trail) from `engine.py` into `PositionExecutor`
- ExecutorPool replaces buy_candidates list + sell_plan
- Each open position is an Executor instance
- Estimated: 12-20 hours (most invasive)
- Risk: high (touches order placement)
- Validation: 14-day shadow + paper-mode integration test before live

### Phase 5 (after Phase 4): Cross-sleeve standardization
- Apply same MDP/Controller/Executor pattern to Alpaca and Solana sleeves
- Shared abstractions extracted to `shared/` package

---

## Risk and rollback

Every phase ships independently. Each has its own kill switch:
- Phase 2: feature flag `USE_MDP=false` → reverts to direct fetch_ohlc
- Phase 3: feature flag `USE_CONTROLLERS=false` → reverts to inline classifier/trader blocks
- Phase 4: feature flag `USE_EXECUTORS=false` → reverts to buy_candidates/sell_plan path

If a phase causes problems, flip the flag, debug, ship again.

## Cross-agent teaching

When this is built:
- Update `CLAUDE.md` Section 1 (Role Assignment) with new file paths under MDP/Controllers/Executors
- Update agent docs: `claude-code-guide`, sleeve-specific agents
- Each sleeve's `<sleeve>_market_sense.py` becomes a Controller; each `<sleeve>_trader.py` becomes a Controller
- Old monolithic `engine.py` paths become legacy/safety-only

## What this refactor does NOT change

- Live trading edge: classifier + trader logic stays the same (just relocated)
- Safety stack: pause_writer, sentinel, governor, kernel — untouched
- Operator authority: pause sacrosanct, hard escalations preserved
- Storage layout: market_data_archive paths fixed (Phase 1 already established)

## Operator decision needed

**Approve Phase 2 (MDP build)?** Estimated 4-6 hours focused work, low risk.
- If yes: I draft the MDP class spec, you approve, I build, 24h shakedown, then proceed to Phase 3.
- If revise: tell me what to revise.
- If reject: keep current architecture; Phase 1 archive continues capturing data for future analysis.

**Note on Tonight's already-completed work:**
- Phase 1 (data archive) is BUILT and wired. The next bot restart activates it.
- Phase 2-5 stay at SPEC level until operator approves each in turn.
