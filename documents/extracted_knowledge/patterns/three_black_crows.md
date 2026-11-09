---
id: three_black_crows
name: Three Black Crows
kind: pattern
category: 3-candle candlestick pattern
status: PENDING_REVIEW
direction: bearish
candles: 3
code_name: Three Black Crows
origin: existing-code
implemented_in: stockpatterns/patterns.py (detect)
tests: tests/test_patterns.py
sources: []
history:
- date: '2026-11-05'
  status: PENDING_REVIEW
  by: claude
  note: written from the existing code
---

# Three Black Crows

> **Origin: existing code.** No uploaded document covers this pattern yet, so this file describes exactly what `stockpatterns/patterns.py` detects today, for you to review. Approving it accepts this coded definition; a book-sourced version can replace it later.

## Summary
Three falling red candles, each opening inside the previous body.

## Source definition
Not specified in source: no uploaded document defines this pattern yet.

## Measurable conditions (as coded)
- Prior trend of candle [i-2] is UP or FLAT
- Candles [i-2], [i-1], [i] are all red
- Each body >= 60% of avg_body
- C[i-2] <= O[i-1] <= O[i-2] and C[i-1] <= O[i] <= O[i-1]
- C[i-2] > C[i-1] > C[i]
- Each lower wick <= 30% of its body

## Notation used below
`O, H, L, C` = open, high, low, close of a candle; `[i]` = the pattern's last candle, `[i-1]` the one before.
`body = |C - O|`, `range = H - L`, `upper wick = H - max(O, C)`, `lower wick = min(O, C) - L`.
`avg_body` = mean body of the last 14 candles, `ATR14` = mean range of the last 14 candles.
**Prior trend** of candle `k` = `C[k-1] - C[k-6]`: DOWN if below `-ATR14[k-1]`, UP if above `+ATR14[k-1]`, else FLAT.
Only closed candles are evaluated (the live app drops the still-forming candle).

## Missing parameters and open questions
- Confirmation: Not specified in source (no document covers this pattern yet). The current code uses none.
- Invalidation: Not specified in source. The current code defines none; the trade stop-loss is set by the strategy (1.5 x ATR).
