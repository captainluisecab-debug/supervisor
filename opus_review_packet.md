# Opus 12h Review Packet
Generated: 2026-06-04T11:55:01.712842+00:00

You are Opus, the strategic reviewer for an autonomous multi-bot trading system.
This is your scheduled 12-hour review. You receive this exactly twice daily at 9:00 AM and 9:00 PM.

UNIVERSAL GOAL: Increase positive PnL. Protect capital. Reduce stupid losses.
Every action must serve this goal or it is misaligned.

AUTHORITY MODEL (LOCKED):
- GOVERNOR = only live command writer. Drives posture. Protects capital.
- HERMES = context authority. Remembers, tracks, detects drift. No commands.
- OPUS (you) = strategic improvement. Fix minor issues in your lane. Recommend major improvements. Do NOT override Governor.
- SLEEVES = execute and obey. Do not invent policy.
- OPERATOR = approves major strategy/architecture/config/policy changes.
- No member drifts into another member's lane.
- Default on uncertainty: HOLD / no change.

YOUR ALLOWED FIX SCOPE:
[
  "code bug fixes in non-live paths",
  "log format improvements",
  "threshold adjustments within existing bounds",
  "dead code cleanup",
  "documentation updates"
]

YOUR FORBIDDEN SCOPE:
[
  "governor command file writes",
  "live .env changes",
  "policy.json changes",
  "strategy logic changes",
  "architecture changes",
  "position sizing changes",
  "entry/exit rule changes"
]

HERMES CONTEXT BRIEF (pre-computed from hermes_context.json — local-first optimization):
Universe: $7893.26 | PnL: $-2484.36 (-23.9%) | 1h delta: $-0.22 | 12h delta: $-1.76
Regime: NEUTRAL (conf=0.00)
Kraken: $3408.61 DD=-3.8% mode=DEFEND posture=SOFT_RETIRE open=0 ff=False
  Pair regime: {"BTC/USD": "DOWN", "ETH/USD": "DOWN", "XRP/USD": "DOWN", "POL/USD": "DOWN", "NEAR/USD": "DOWN"}
SFM: $4.92 DD=-23.2% trades=8 wins=2 position=False
Alpaca: $1071.73 trades=65 wins=36 open=2
Advisory: K=SCOUT/entry=True S=DEFENSE/entry=False A=SCOUT/entry=True
Execution truth: 50 total, 25 buys, 25 sells, 11 ff, 0 violations
  Last BUY: 2026-06-01T17:30:13 | Last SELL: 2026-06-01T19:51:03
Churn: 1h=0 loops 6h=0 24h=0 loops/$0.00
Exit quality: [{'reason': 'psar_trail', 'pnl': -0.2985, 'pair': 'POL/USD'}, {'reason': 'take_profit', 'pnl': 2.1177, 'pair': 'XRP/USD'}, {'reason': 'trail_hit', 'pnl': -4.1508, 'pair': 'XRP/USD'}, {'reason': 'psar_trail', 'pnl': -0.876, 'pair': 'XRP/USD'}, {'reason': 'trail_hit', 'pnl': -4.1147, 'pair': 'XRP/USD'}, {'reason': 'trail_hit', 'pnl': -3.3773, 'pair': 'XRP/USD'}, {'reason': 'trail_hit', 'pnl': -6.1456, 'pair': 'NEAR/USD'}, {'reason': 'cash_and_run_chop_w4_dN_$0.09_buf0.1x', 'pnl': -0.2927, 'pair': 'XRP/USD'}, {'reason': 'trail_hit', 'pnl': -3.493, 'pair': 'ETH/USD'}, {'reason': 'score_exit', 'pnl': -3.9145, 'pair': 'XRP/USD'}]
Entry blocks: [{'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}, {'pair': 'NEAR/USD', 'reason': 'blocked:score=65.3<88.0(regime=VOLATILE)', 'score': 65.32}]
Insights: ['CONCERN: last 10 exits have 9 losses vs 1 wins (avg $-2.45)', 'Top exit reason: trail_hit (5/10)', 'Kraken: 7/26 wins (27%)', 'Top entry blocker: blocked:score=65.3<88.0(regime=VOLATILE) (11/20)', 'SFM: 2/8 wins (25%)', 'Alpaca: 36/65 wins (55%)']

GOVERNOR UNIVERSE BRIEF:
{
  "ts": "2026-06-04T11:50:42.982712+00:00",
  "dominant_regime": "TRENDING_DOWN",
  "effective_posture": {
    "kraken": "SOFT_RETIRE",
    "sfm": "HERMES_DD_OVERRIDE",
    "alpaca": "TRADE_ACTIVE",
    "zerobot": "ZEROBOT_TRADE_ACTIVE"
  },
  "kraken": {
    "equity": 3408.611256512005,
    "dd_pct": -3.799172490901892,
    "mode": "DEFEND",
    "open_positions": 0,
    "cash": 3408.611256512005
  },
  "sfm": {
    "equity": 1990.35,
    "dd_pct": 0.0,
    "open_position": false
  },
  "alpaca": {
    "equity": 557.0617615567496,
    "realized_pnl": 57.06176155674964,
    "win_rate": 55.38461538461539,
    "open_positions": 2
  },
  "brain_advisory": "Hermes advisory: NEUTRAL, K=-3.8% S=-23.2% A=0.0% Z=-0.0%",
  "governor_decisions": [
    {
      "sleeve": "kraken",
      "action": "SOFT_RETIRE",
      "reason": "Operator soft-retire active (kraken_retire.flag present) \u2014 entries permanently blocked"
    },
    {
      "sleeve": "sfm",
      "action": "HERMES_DD_OVERRIDE",
      "reason": "Hermes advisory: entry_allowed=false (DD=0.0%) \u2014 tighten-only override"
    },
    {
      "sleeve": "alpaca",
      "action": "TRADE_ACTIVE",
      "reason": "Regime=TRENDING_UP -> TRADE."
    },
    {
      "sleeve": "zerobot",
      "action": "ZEROBOT_TRADE_ACTIVE",
      "reason": "Regime=TRENDING_DOWN -> NORMAL (strategy's own gates apply)."
    }
  ],
  "feedback": {
    "equity_1h_ago": 0,
    "equity_now": 5956.023018068755,
    "equity_direction": "unknown"
  }
}

PNL DELTA (vs 12 hours ago):
  Universe: $+0.00 (flat)
  Kraken:   $+0.00
  SFM:      $+0.00
  Alpaca:   $+0.00
  Previous snapshot: 2026-06-03T23:55:01.793173+00:00

CURRENT PNL:
  Universe equity: $5956.02
  Universe PnL vs baseline ($6,969.62): $-1013.60
  Kraken: $3408.61 (DD -3.8%)
  SFM: $1990.35
  Alpaca: $557.06

GOVERNOR DECISION SUMMARY (last 12h):
{
  "SOFT_RETIRE": 20,
  "HOLD": 20,
  "HERMES_DD_OVERRIDE": 20,
  "TRADE_ACTIVE": 20,
  "ZEROBOT_TRADE_ACTIVE": 20
}

RECENT BRAIN OUTCOMES:
[
  {
    "decision_ts": "2026-04-03T00:37:54.391346+00:00",
    "outcome_ts": "2026-04-03T00:47:59.931208+00:00",
    "total_chg_pct": 0.0,
    "overall_verdict": "NEUTRAL",
    "regime": {
      "label": "RISK_ON",
      "confidence": 0.33,
      "btc_7d_pct": -2.8,
      "spy_vol_10d": 1.47,
      "vix": 23.9
    },
    "sleeves": [
      {
        "sleeve": "kraken",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 3686.03,
        "eq_after": 3686.03,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "sfm",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 2436.14,
        "eq_after": 2436.14,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "alpaca",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 480.26,
        "eq_after": 480.26,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      }
    ]
  },
  {
    "decision_ts": "2026-04-03T00:48:04.731183+00:00",
    "outcome_ts": "2026-04-03T00:58:09.684351+00:00",
    "total_chg_pct": 0.0,
    "overall_verdict": "NEUTRAL",
    "regime": {
      "label": "RISK_ON",
      "confidence": 0.33,
      "btc_7d_pct": -2.9,
      "spy_vol_10d": 1.47,
      "vix": 23.9
    },
    "sleeves": [
      {
        "sleeve": "kraken",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 3686.03,
        "eq_after": 3686.03,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "sfm",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 2436.14,
        "eq_after": 2436.14,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "alpaca",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 480.26,
        "eq_after": 480.26,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      }
    ]
  },
  {
    "decision_ts": "2026-04-03T00:58:14.335280+00:00",
    "outcome_ts": "2026-04-03T01:08:19.056743+00:00",
    "total_chg_pct": 0.0,
    "overall_verdict": "NEUTRAL",
    "regime": {
      "label": "RISK_ON",
      "confidence": 0.33,
      "btc_7d_pct": -3.0,
      "spy_vol_10d": 1.47,
      "vix": 23.9
    },
    "sleeves": [
      {
        "sleeve": "kraken",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 3686.03,
        "eq_after": 3686.03,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "sfm",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 2436.14,
        "eq_after": 2436.14,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "alpaca",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 480.26,
        "eq_after": 480.26,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      }
    ]
  },
  {
    "decision_ts": "2026-04-03T01:08:23.847483+00:00",
    "outcome_ts": "2026-04-03T01:18:28.741279+00:00",
    "total_chg_pct": 0.0,
    "overall_verdict": "NEUTRAL",
    "regime": {
      "label": "RISK_ON",
      "confidence": 0.33,
      "btc_7d_pct": -2.8,
      "spy_vol_10d": 1.47,
      "vix": 23.9
    },
    "sleeves": [
      {
        "sleeve": "kraken",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 3686.03,
        "eq_after": 3686.03,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "sfm",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 2436.14,
        "eq_after": 2436.14,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "alpaca",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 480.26,
        "eq_after": 480.26,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      }
    ]
  },
  {
    "decision_ts": "2026-04-03T01:18:33.415981+00:00",
    "outcome_ts": "2026-04-03T01:28:38.074948+00:00",
    "total_chg_pct": 0.0,
    "overall_verdict": "NEUTRAL",
    "regime": {
      "label": "RISK_ON",
      "confidence": 0.33,
      "btc_7d_pct": -2.8,
      "spy_vol_10d": 1.47,
      "vix": 23.9
    },
    "sleeves": [
      {
        "sleeve": "kraken",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 3686.03,
        "eq_after": 3686.03,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "sfm",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 2436.14,
        "eq_after": 2436.14,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      },
      {
        "sleeve": "alpaca",
        "mode": "DEFENSE",
        "size_mult": 0.3,
        "eq_before": 480.26,
        "eq_after": 480.26,
        "chg_pct": 0.0,
        "verdict": "NEUTRAL",
        "reasoning": "no fills in decision window | equity delta +0.00% (fallback, not scored)"
      }
    ]
  }
]

BRAIN ADVISORY (last cycle):
Hermes advisory: NEUTRAL, K=-3.8% S=-23.2% A=0.0% Z=-0.0%

PERSISTENT REVIEW MEMORY (from your last 12h review — use this to avoid re-raising resolved issues):
  Review cycle: #134
  Issues previously identified: ["LESSON-007: duplicate exit logging", "LESSON-008: expectancy deadlock"]
  Issues previously fixed: ["LESSON-007: dedup in _read_recent_exits()", "LESSON-008: expectancy time-decay", "orphaned brain_pending.json removed"]
  Issues deferred: ["Paperclip unreachable (needs restart)", "Alpaca 25% win rate (needs strategy review)"]
  Issues still active: []
  Last regime: TRENDING_DOWN

HERMES ESCALATIONS (urgent findings since last review — consumed on read):
[
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-03T23:56:36.024340+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.0% \u2014 below -10% threshold",
    "ts": "2026-06-03T23:56:36.024340+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3409 in one cycle (7895 -> 4486)",
    "ts": "2026-06-04T00:01:39.624334+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -18.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:01:39.624334+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3406 in one cycle (7894 -> 4488)",
    "ts": "2026-06-04T00:07:34.219563+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:07:34.219563+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:12:37.779634+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:12:37.779634+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4487)",
    "ts": "2026-06-04T00:17:41.159490+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -18.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:17:41.159490+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T00:22:44.547875+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -18.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:22:44.547875+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4488)",
    "ts": "2026-06-04T00:27:48.062726+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:27:48.062726+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:32:53.900952+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:32:53.900952+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:37:59.742971+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:37:59.742971+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:43:03.392913+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:43:03.392913+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:48:06.810621+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:48:06.810621+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:53:10.385845+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:53:10.385845+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T00:58:13.777371+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T00:58:13.777371+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:03:17.355531+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:03:17.355531+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:08:21.099332+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:08:21.099332+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:13:24.727601+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:13:24.727601+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:18:28.467279+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:18:28.467279+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:23:31.988288+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:23:31.988288+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:28:35.623613+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:28:35.623613+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:33:39.201326+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:33:39.201326+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:38:42.824614+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:38:42.824614+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:43:46.278287+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:43:46.278287+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:48:49.797383+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:48:49.797383+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:53:53.321074+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:53:53.321074+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T01:58:56.865103+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T01:58:56.865103+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T02:04:00.335559+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:04:00.335559+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T02:09:03.941618+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:09:03.941618+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4487)",
    "ts": "2026-06-04T02:14:07.271230+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:14:07.271230+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T02:19:10.742035+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:19:10.742035+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T02:24:14.292673+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:24:14.292673+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4488)",
    "ts": "2026-06-04T02:29:17.860614+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:29:17.860614+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4487)",
    "ts": "2026-06-04T02:34:21.328659+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:34:21.328659+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T02:39:24.916343+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:39:24.916343+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T02:44:28.386154+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:44:28.386154+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T02:49:31.848845+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:49:31.848845+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4488)",
    "ts": "2026-06-04T02:54:35.337516+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:54:35.337516+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T02:59:38.907343+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T02:59:38.907343+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:04:42.462525+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:04:42.462525+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:09:45.959188+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:09:45.959188+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:14:49.439541+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:14:49.439541+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:19:53.020757+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:19:53.020757+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:24:56.714046+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:24:56.714046+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:30:00.274573+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:30:00.274573+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:35:03.885490+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:35:03.885490+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:40:07.394651+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:40:07.394651+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:45:13.136828+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:45:13.136828+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:50:16.750810+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:50:16.750810+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T03:55:20.133918+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T03:55:20.133918+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:00:23.371094+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:00:23.371094+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:05:27.069577+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:05:27.069577+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:10:30.545341+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:10:30.545341+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:15:34.048843+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:15:34.048843+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:20:37.416861+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:20:37.416861+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:25:40.962959+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:25:40.962959+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:30:44.416825+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:30:44.416825+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:35:47.793919+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:35:47.793919+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:40:51.207657+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:40:51.207657+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:45:54.634485+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:45:54.634485+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:50:58.007602+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:50:58.007602+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T04:56:01.513766+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T04:56:01.513766+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:01:04.700693+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:01:04.700693+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:06:08.234740+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:06:08.234740+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:11:11.535505+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:11:11.535505+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:16:14.905034+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:16:14.905034+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:21:18.332560+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:21:18.332560+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:26:21.703973+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:26:21.703973+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:31:25.186303+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:31:25.186303+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:36:28.596459+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:36:28.596459+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:41:32.094454+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:41:32.094454+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:46:35.465309+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:46:35.465309+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:51:39.052526+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:51:39.052526+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T05:56:42.472335+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T05:56:42.472335+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:01:45.858773+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:01:45.858773+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:06:49.188328+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:06:49.188328+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:11:52.553467+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:11:52.553467+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:16:56.065453+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:16:56.065453+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:21:59.413379+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -19.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:21:59.413379+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:27:02.904232+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:27:02.904232+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:32:06.433582+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:32:06.433582+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:37:09.781315+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:37:09.781315+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:42:13.179858+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:42:13.179858+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:47:16.639675+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:47:16.639675+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:52:20.011252+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:52:20.011252+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T06:57:23.380633+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T06:57:23.380633+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:02:26.772840+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:02:26.772840+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:07:30.070369+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:07:30.070369+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:12:33.442808+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:12:33.442808+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:17:36.736152+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -20.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:17:36.736152+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:22:40.076784+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:22:40.076784+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:27:43.401767+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:27:43.401767+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:32:46.700478+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:32:46.700478+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:37:50.124385+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:37:50.124385+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:42:53.587649+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:42:53.587649+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:47:56.984603+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:47:56.984603+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:53:00.409570+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:53:00.409570+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T07:58:03.869764+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T07:58:03.869764+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T08:03:07.198047+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:03:07.198047+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3409 in one cycle (7896 -> 4488)",
    "ts": "2026-06-04T08:08:10.822682+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:08:10.822682+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7896 -> 4487)",
    "ts": "2026-06-04T08:13:14.266133+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.3% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:13:14.266133+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:18:17.681585+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:18:17.681585+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:23:21.013927+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:23:21.013927+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:28:24.498554+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:28:24.498554+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:33:27.905573+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -21.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:33:27.905573+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:38:31.367667+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:38:31.367667+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4487)",
    "ts": "2026-06-04T08:43:34.803094+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:43:34.803094+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7895 -> 4486)",
    "ts": "2026-06-04T08:48:38.211941+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:48:38.211941+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T08:53:41.551166+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:53:41.551166+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T08:58:44.936124+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T08:58:44.936124+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:03:48.246156+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.0% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:03:48.246156+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:08:51.595995+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:08:51.595995+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3409 in one cycle (7894 -> 4485)",
    "ts": "2026-06-04T09:13:55.000042+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:13:55.000042+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7893 -> 4485)",
    "ts": "2026-06-04T09:18:58.489020+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:18:58.489020+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3407 in one cycle (7893 -> 4486)",
    "ts": "2026-06-04T09:24:02.026379+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:24:02.026379+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:29:05.406462+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:29:05.406462+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:34:08.280409+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:34:08.280409+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:39:11.683546+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:39:11.683546+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:44:15.039015+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:44:15.039015+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:49:18.405179+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:49:18.405179+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:54:21.847193+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:54:21.847193+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T09:59:25.291612+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T09:59:25.291612+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:04:28.801450+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:04:28.801450+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:09:32.440182+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:09:32.440182+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:14:35.930996+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:14:35.930996+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:19:39.306327+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:19:39.306327+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:24:42.679024+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:24:42.679024+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:29:46.277674+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.6% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:29:46.277674+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:34:49.754020+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:34:49.754020+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:39:53.103697+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.5% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:39:53.103697+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:44:56.659848+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:44:56.659848+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T10:50:00.153482+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.9% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:50:00.153482+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4485)",
    "ts": "2026-06-04T10:55:03.972867+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T10:55:03.972867+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7893 -> 4486)",
    "ts": "2026-06-04T11:00:07.533314+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:00:07.533314+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:05:11.031505+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.4% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:05:11.031505+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:10:14.447345+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:10:14.447345+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:15:17.914560+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:15:17.914560+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:20:21.393145+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.7% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:20:21.393145+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:25:25.158074+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:25:25.158074+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4486)",
    "ts": "2026-06-04T11:30:28.664248+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:30:28.664248+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7894 -> 4485)",
    "ts": "2026-06-04T11:35:32.171930+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:35:32.171930+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7893 -> 4485)",
    "ts": "2026-06-04T11:40:35.805947+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -22.8% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:40:35.805947+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7893 -> 4485)",
    "ts": "2026-06-04T11:45:39.254046+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.1% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:45:39.254046+00:00"
  },
  {
    "severity": "HIGH",
    "type": "equity_drop",
    "detail": "Universe equity dropped $3408 in one cycle (7893 -> 4485)",
    "ts": "2026-06-04T11:50:42.759524+00:00"
  },
  {
    "severity": "HIGH",
    "type": "sfm_dd_critical",
    "detail": "SFM DD at -23.2% \u2014 below -10% threshold",
    "ts": "2026-06-04T11:50:42.759524+00:00"
  }
]

PAPERCLIP ISSUE STATE (loop-closure tracking):
{
  "open": [
    {
      "id": "PC-205",
      "title": "Regime: TRENDING_DOWN (Hermes: NEUTRAL)",
      "status": "todo",
      "age_hours": 31.6
    },
    {
      "id": "PC-204",
      "title": "SFM DD critical: -15.6%",
      "status": "todo",
      "age_hours": 35.4
    },
    {
      "id": "PC-25",
      "title": "Hermes escalation: SFM DD at -44.9% \u2014 below -10% threshold",
      "status": "todo",
      "age_hours": 1160.4
    },
    {
      "id": "PC-12",
      "title": "Hermes escalation: Kraken DD at -11.3% \u2014 below -10% threshol",
      "status": "todo",
      "age_hours": 1279.2
    },
    {
      "id": "PC-11",
      "title": "Hermes escalation: Universe equity dropped $66 in one cycle ",
      "status": "todo",
      "age_hours": 1279.2
    }
  ],
  "stale": [
    "PC-25",
    "PC-12",
    "PC-11"
  ],
  "total": 207,
  "closed": 202
}

EXECUTION TRUTH (what actually executed vs what was commanded — per AUTHORITY_CONSTITUTION §4a):
{
  "total_executions": 50,
  "buys": 25,
  "sells": 25,
  "force_flattens": 11,
  "violations_count": 0,
  "last_execution_ts": "2026-06-01T19:51:03.113790+00:00",
  "last_buy_ts": "2026-06-01T17:30:13.584540+00:00",
  "last_sell_ts": "2026-06-01T19:51:03.113790+00:00",
  "churn_windows": {
    "1h": {
      "buys": 0,
      "force_flattens": 0,
      "unauthorized_entries": 0,
      "churn_pnl_drain": 0,
      "repeated_entry_loops": 0
    },
    "6h": {
      "buys": 0,
      "force_flattens": 0,
      "unauthorized_entries": 0,
      "churn_pnl_drain": 0,
      "repeated_entry_loops": 0
    },
    "24h": {
      "buys": 0,
      "force_flattens": 0,
      "unauthorized_entries": 0,
      "churn_pnl_drain": 0,
      "repeated_entry_loops": 0
    }
  }
}

AUTHORITY VIOLATIONS (BUY fills while entry_allowed=false — requires investigation):
[]

SYSTEM LESSONS (institutional memory — do NOT re-learn these):
[
  {
    "id": "LESSON-001",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "authority_violation",
    "lesson": "Command files are intent, execution_log.jsonl is truth. A BUY can execute while entry_allowed=false if the sleeve does not enforce the command file. Hermes must cross-reference execution_log against command state every cycle.",
    "evidence": "57 BUYs executed in 72h while Governor had entry_allowed=false. enzobot/engine.py did not read entry_allowed field. As of 2026-04-04T18:14Z, 24 additional violations detected in 24h \u2014 engine.py STILL does not enforce entry_allowed.",
    "remediation": "DETECTION ONLY: Added execution truth reading in Hermes. Added reconciliation in Paperclip bridge. ENFORCEMENT MISSING: engine.py entry_allowed gate was never verified as implemented \u2014 enzobot continues to ignore entry_allowed field in kraken_cmd.json.",
    "prevention_rule": "Every cycle must reconcile execution reality against command intent. Enforcement must exist at the sleeve level, not just detection at the supervisor level.",
    "status": "resolved",
    "updated_by": "opus_12h_review_cycle8",
    "updated_at": "2026-04-04T18:14:00Z"
  },
  {
    "id": "LESSON-002",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "memory_loss",
    "lesson": "Hermes working memory (pnl_history, regime_history, event_log) is stored in Python globals and lost on every supervisor restart. This erases 24h of context and breaks delta computation.",
    "evidence": "After supervisor restart for kernel deployment, Hermes had zero historical context. PnL deltas showed null.",
    "remediation": "Added disk-backed persistence via hermes_state_persist.json. Reload on startup.",
    "prevention_rule": "All working memory must be disk-backed with reload on startup.",
    "status": "resolved"
  },
  {
    "id": "LESSON-003",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "monitoring_gap",
    "lesson": "Paperclip bridge monitored kernel halts, DD thresholds, regime changes, and classifications \u2014 but not execution obedience. The most critical operational check (are bots obeying commands?) was missing.",
    "evidence": "57 unauthorized BUYs went undetected for 72h because no layer compared execution_log against command files.",
    "remediation": "Added authority violation check and churn detection to Paperclip bridge.",
    "prevention_rule": "Paperclip must verify execution obedience every cycle.",
    "status": "resolved"
  },
  {
    "id": "LESSON-004",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "reporting_failure",
    "lesson": "No trade-status claim is valid without checking execution_log.jsonl first. Inferring 'no trades' from command file state is unreliable.",
    "evidence": "Status reports said 'no BUY fills possible' while 57 BUYs were executing. Command files showed entry_allowed=false but engine ignored it.",
    "remediation": "Mandatory verification checklist: check execution_log before any trade-status claim.",
    "prevention_rule": "Before saying 'no trades' or 'waiting for BUY', verify execution_log.jsonl and state the last fill timestamp.",
    "status": "resolved"
  },
  {
    "id": "LESSON-005",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "churn_detection",
    "lesson": "Buy-then-force-flatten churn loops are a system-level control failure, not just PnL noise. Each round-trip costs $0.28-$4.93 and represents an authority violation.",
    "evidence": "31 force_flatten SELLs in 72h totaling $-21.32 in losses. Each was preceded by an unauthorized BUY. 2026-04-04: 18 additional force_flattens, 22 repeated entry loops, $-9.26 churn drain in 24h.",
    "remediation": "DETECTION: Added churn detection in Paperclip bridge. ENFORCEMENT: engine.py entry_allowed gate NOT confirmed as implemented \u2014 churn continues because unauthorized BUYs still occur.",
    "prevention_rule": "Churn pattern (BUY followed by force_flatten within 1h) must trigger critical issue.",
    "status": "resolved",
    "updated_by": "opus_12h_review_cycle8",
    "updated_at": "2026-04-04T18:14:00Z"
  },
  {
    "id": "LESSON-006",
    "ts": "2026-04-04T14:00:00Z",
    "source": "operator+opus",
    "category": "escalation_loss",
    "lesson": "Hermes escalations are consumed-and-destroyed by Opus 12h review. No historical record survives. Past escalations cannot be reviewed or audited.",
    "evidence": "hermes_escalations.jsonl is cleared to 0 bytes after Opus reads it. No archive exists.",
    "remediation": "Added escalation_archive.jsonl \u2014 permanent append-only archive. Active file remains consume-once.",
    "prevention_rule": "All escalations must be archived permanently before being cleared from the active file.",
    "status": "resolved"
  },
  {
    "id": "LESSON-007",
    "ts": "2026-04-10T00:30:00Z",
    "source": "opus_12h_review_cycle23",
    "category": "data_contamination",
    "lesson": "Engine logs each exit twice with slightly different timestamps and IDs (differs by 1-40 seconds). Rolling expectancy computed from raw exit records is contaminated \u2014 every loss and win is double-counted. This inflated negative expectancy from -1.87 to -3.57, causing a false FREEZE_ENTRIES that locked $3,652 (56% of universe) for 27+ hours during TRENDING_UP.",
    "evidence": "146 raw exits, 106 after dedup = 40 duplicates (27%). Expectancy shifted from -3.57 (frozen) to -1.87 (cleared) after dedup. Kraken had 0 positions with $3,652 cash idle.",
    "remediation": "Added dedup by (pair, entry_price, exit_reason) in _read_recent_exits() in supervisor_governor.py. Added time-decay on negative expectancy (20% per 12h) as deadlock prevention.",
    "prevention_rule": "Any metric computed from exit logs must deduplicate first. Any freeze-by-metric system must have a decay/reset mechanism to prevent permanent deadlock.",
    "status": "resolved",
    "updated_by": "opus_12h_review_cycle23",
    "updated_at": "2026-04-10T00:30:00Z"
  },
  {
    "id": "LESSON-008",
    "ts": "2026-04-10T00:30:00Z",
    "source": "opus_12h_review_cycle23",
    "category": "deadlock_prevention",
    "lesson": "A rolling expectancy that freezes entries creates a permanent deadlock when: expectancy < threshold -> no entries -> no exits -> expectancy never recovers. Capital sits idle indefinitely.",
    "evidence": "Kraken frozen for 27+ hours with expectancy=-3.57 (contaminated). Even with dedup fix, expectancy=-1.87 could re-freeze after a bad trade with no recovery path.",
    "remediation": "Added EXPECTANCY_DECAY_INTERVAL_SEC=43200 (12h) and EXPECTANCY_DECAY_RATE=0.20 in supervisor_governor.py. Negative expectancy decays 20% per 12h of inactivity toward zero.",
    "prevention_rule": "Every metric-based freeze must have a time-bounded decay mechanism. No metric should permanently block capital deployment.",
    "status": "resolved",
    "updated_by": "opus_12h_review_cycle23",
    "updated_at": "2026-04-10T00:30:00Z"
  }
]

MEMORY CONTINUITY:
  Authority violations seen (cumulative): 315
  Last reconciliation: {"total_executions": 50, "buys": 25, "sells": 25, "force_flattens": 11, "violations_count": 0, "last_execution_ts": "2026-06-01T19:51:03.113790+00:00", "last_buy_ts": "2026-06-01T17:30:13.584540+00:00", "last_sell_ts": "2026-06-01T19:51:03.113790+00:00", "churn_windows": {"1h": {"buys": 0, "force_flattens": 0, "unauthorized_entries": 0, "churn_pnl_drain": 0, "repeated_entry_loops": 0}, "6h": {"buys": 0, "force_flattens": 0, "unauthorized_entries": 0, "churn_pnl_drain": 0, "repeated_entry_loops": 0}, "24h": {"buys": 0, "force_flattens": 0, "unauthorized_entries": 0, "churn_pnl_drain": 0, "repeated_entry_loops": 0}}}
  Causal lessons carried forward: []

RECENT CODE CHANGES (last 3 commits per repo — do NOT re-raise issues already fixed):
  [enzobot] f0d76c4 feat(auto_tune): self-improving learning loop â€” closed-trade -> per-pair -> rule -> adjust
  [sfmbot] 1c3945c feat(logging): keyword-based color highlighting via shared log_colors
  [sfmbot] 4e44b4e feat(brain): route autonomous writes through autonomy_guard
  [sfmbot] 250cce1 fix(brain): import time to stop silent adaptive-review crash
  [alpacabot] 14bffe0 Path C-FULL: enable full deploy size on NORMAL/TRADE mode
  [alpacabot] 325d61b feat(logging): keyword-based color highlighting via shared log_colors
  [alpacabot] 9183b5d feat(brain): wire Alpaca path classifier + trader into engine BUY loop
  [supervisor] 0058297 Banner 3-sleeves->4-sleeves + opus_strategic_review LLM prompt 3-bot->4-bot
  [supervisor] de2bd4e Phase 3 prereq #2: hermes_context.compute_advisory() emits zerobot key
  [supervisor] 9c68a9a ZeroBot pre-Phase-2 wiring: register 4th sleeve zerobot_btc

IMPORTANT: Before flagging any issue, check whether a recent commit already addresses it.
If a fix was already deployed, report it as RESOLVED, not as a current issue.
Only flag issues that are STILL PRESENT in the current running code.

YOUR TASK:
1. Review the last 12 hours of governor and system behavior.
2. Identify any loopholes, bugs, communication issues, or missed opportunities blocking positive trend.
3. For each issue, classify as:
   - MINOR: FIX IT NOW using your file tools (Read/Edit/Write). You have execution authority on minor fixes. Then report what you fixed.
   - MAJOR: requires operator approval — describe the fix but do NOT execute it.
4. Focus on what would improve the system's ability to capture positive PnL trend.
5. After making any fixes, produce a clear operator status report.

You have tool access to read and edit Python files across all bot directories.
PERMISSIONS: The opus_review_window is OPEN right now. You HAVE write permission to edit Python files.
DO NOT assume permissions are denied. DO NOT skip fixes because of prior permission errors.
If a fix is in your lane, EXECUTE IT NOW using Edit or Write tools. Do not just report it.

You may NOT write to: command files (*_cmd.json), .env, policy.json, brain_state.json, or any runtime state file.
You may NOT restart services. Fixes take effect on next natural restart.

CLOSURE DISCIPLINE:
- Do NOT mark any fix as complete unless you have verified it end-to-end.
- For each fix you apply, verify: the file compiles, the logic is correct, the expected behavior would occur.
- If you cannot verify a fix, mark it as "applied but unverified" and explain what needs checking.
- Do NOT re-raise issues from "issues_fixed" in your persistent memory unless you have NEW evidence they are broken again.

If nothing materially changed: report "No material change."

RESPOND IN THIS EXACT MANDATORY FORMAT (all sections required, every 12 hours, 7 days/week):

## 1. PNL REPORT
| Metric | Value |
|--------|-------|
| Universe equity now | $X |
| Universe PnL (vs $6,969.62 baseline) | $X |
| Delta vs 12 hours ago | $X (better/flat/worse) |
| Kraken delta | $X |
| SFM delta | $X |
| Alpaca delta | $X |

## 2. UNIVERSE STATUS
(2-3 sentences: current state, direction, main risk)

## 3. ISSUES FOUND
For each issue, label its status:
- ACTIVE: still present and unresolved
- RESOLVED: fixed in this or a prior cycle
- BLOCKED: cannot fix without operator approval
- DEFERRED: known but not priority
(numbered list with status labels, or "None")

## 4. FIXES APPLIED (MINOR — in my lane)
For each fix:
- what was wrong
- exact file(s) changed
- what I fixed
- expected benefit
- rollback path
Or: "None"

## 5. FIXES RECOMMENDED (MAJOR — needs operator approval)
For each:
- what is wrong
- what should change
- expected benefit
- risk
Or: "None"

## 6. POSITIVE TREND BLOCKER
- What prevented sleeves from improving positive trend in the last 12h?
- Which sleeve was most blocked?
- Blocker type: market / strategy / governor / command / bug / capital-limit
- Single biggest blocker:
- Blocker status: already fixed / still active / needs approval

## 7. OPERATOR ACTION NEEDED
(yes/no + specific action items if yes)

## 8. OPERATOR BOTTOM LINE
One line: better / flat / worse vs last 12h, and why.

## 9. NEXT 12H OUTLOOK
(1-2 sentences: what to expect, what to watch)

## 10. EXECUTION TRUTH & LESSON CARRY-FORWARD
- Reconciliation summary: matched / mismatched / unresolved
- Authority violations detected (if any): root cause and recommended action
- New lessons learned this cycle (if any)
- Unresolved lessons from prior cycles
- Memory continuity: what persisted correctly, what was lost or stale
