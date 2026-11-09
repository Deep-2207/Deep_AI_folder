---
id: trend_pattern_rule
name: Trend + pattern agreement rule (CALL / PUT / WAIT)
kind: strategy
category: Strategy
status: PENDING_REVIEW
origin: existing-code
implemented_in: stockpatterns/signal.py
tests: tests/test_signal.py
sources: []
history:
- date: '2026-11-05'
  status: PENDING_REVIEW
  by: claude
  note: written from the existing code
---

# Trend + pattern agreement rule (CALL / PUT / WAIT)

> **Origin: existing code.** Not taken from a book. Approving it lets the live signal use this rule, with
> **only the patterns you approved** feeding its pattern vote.

## Entry rules (as coded)
Two votes on each closed candle, both must agree:
- **Trend vote**: `tanh((EMA20 - EMA50) / ATR14)`: UP if >= +0.2, DOWN if <= -0.2, else FLAT.
- **Pattern vote**: approved patterns that completed in the last `look-ahead` candles, each scored by how much more
  (or less) often price rose `look-ahead` candles after that pattern *earlier on the same chart* than after any
  candle (z-score, needs >= 8 earlier cases and 50 baseline candles; fresher patterns weigh more):
  BULLISH if >= +0.15, BEARISH if <= -0.15, else NONE. Double Top/Bottom are excluded (look-ahead).
- **CALL** = trend UP + patterns BULLISH. **PUT** = trend DOWN + patterns BEARISH. Otherwise **WAIT**.

## Exit rules (as coded)
- Entry at the signal candle's close. Stop = 1.5 x ATR14 away. Target = 2 x the stop distance (R:R 2).
- Exit at the stop (checked first when both are inside one candle), the target, after 4 x look-ahead candles, or
  at the last candle before the market closes (intraday). One trade at a time, one-candle cool-down.
- No signals during the first 100 candles (warm-up).

## Confirmation / invalidation
- Confirmation = the trend vote. Invalidation = the stop-loss. No other confirmation or invalidation rule.

## Differences from the book's concepts (see concepts/)
- Stop-first assumption vs the book's AMBIGUOUS outcome (Signal outcome tracking, p. 4).
- No costs or slippage (Risk and testing rules, p. 4).

## Parameters
`TREND_MIN 0.2, PATTERN_MIN 0.15, SL_ATR 1.5, RR 2.0, MIN_CASES 8, WARMUP 100` (top of `signal.py`).
