---
id: double_top
name: Double Top
kind: pattern
category: Chart pattern
status: PENDING_REVIEW
direction: bearish
candles: null
code_name: Double Top
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

# Double Top

> **Origin: existing code.** No uploaded document covers this pattern yet, so this file describes exactly what `stockpatterns/patterns.py` detects today, for you to review. Approving it accepts this coded definition; a book-sourced version can replace it later.

## Summary
Two similar swing highs with a clear dip (neckline) between them.

## Source definition
Not specified in source: no uploaded document defines this pattern yet.

## Measurable conditions (as coded)
- Swing high at candle p: H[p] > the highs of the 3 candles before and >= the highs of the 3 candles after
- Two consecutive swing highs a and b, 5 to 60 candles apart
- |H[a] - H[b]| <= 0.6 x ATR14[b]
- neckline = lowest low between a and b; min(H[a], H[b]) - neckline >= 1.5 x ATR14[b]
- Reported at candle b; 'neckline broken' when a later close is below the neckline

## Notation used below
`O, H, L, C` = open, high, low, close of a candle; `[i]` = the pattern's last candle, `[i-1]` the one before.
`body = |C - O|`, `range = H - L`, `upper wick = H - max(O, C)`, `lower wick = min(O, C) - L`.
`avg_body` = mean body of the last 14 candles, `ATR14` = mean range of the last 14 candles.
**Prior trend** of candle `k` = `C[k-1] - C[k-6]`: DOWN if below `-ATR14[k-1]`, UP if above `+ATR14[k-1]`, else FLAT.
Only closed candles are evaluated (the live app drops the still-forming candle).

## Missing parameters and open questions
- Confirmation: Not specified in source (no document covers this pattern yet). The current code uses none.
- Invalidation: Not specified in source. The current code defines none; the trade stop-loss is set by the strategy (1.5 x ATR).
- Look-ahead: a swing high is only known 3 candles later, so the trade signal ignores this pattern (signal.py LAGGING). It is shown on the chart only.
