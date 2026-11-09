---
id: support_resistance
name: Support and resistance
kind: concept
category: Support/resistance
status: PENDING_REVIEW
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 4. Support and resistance (introductory concept)
  page: 3
  quote: 'Support: a price area where declines have previously paused or where buying interest may emerge.'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 4. Support and resistance (introductory concept)
  page: 3
  quote: 'Resistance: a price area where advances have previously paused or where selling interest may emerge.'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 4. Support and resistance (introductory concept)
  page: 3
  quote: These are better treated as zones than perfectly precise prices.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 4. Support and resistance (introductory concept)
  page: 3
  quote: This sample does not define the lookback period, tolerance, minimum number of touches or breakout confirmation.
history:
- date: '2026-11-05'
  status: EXTRACTED
  by: claude
  note: read dummy_trading_knowledge_book.pdf
- date: '2026-11-05'
  status: PENDING_REVIEW
  by: claude
  note: structured for review
---

# Support and resistance

> **Origin: book**, section 4, page 3. **Not implemented** in the software.

## Plain-language definition (source)
- **Support**: a price area where declines have previously paused or buying interest may emerge.
- **Resistance**: a price area where advances have previously paused or selling interest may emerge.
- Treat them as **zones**, not exact prices.

## Method the source asks for (p. 3)
A documented method to identify them, "for example, swing highs/lows within a specified lookback window, a
tolerance around prices, and a rule for merging nearby levels".

## Missing parameters and ambiguities
- Lookback period: Not specified in source.
- Price tolerance (zone width): Not specified in source.
- Minimum number of touches: Not specified in source.
- Rule for merging nearby levels: Not specified in source.
- Breakout confirmation: Not specified in source.

## Python implementation requirements
- Swing highs/lows that only use candles up to the current one (a swing is confirmed k candles later: record that
  delay, as `Double Top` does).
- Every parameter above must be chosen, written into this file and tested before implementation.

## Experiment proposal (NOT from the source)
- Swing pivots with k = 3 (same as the existing Double Top/Bottom code), zone = pivot price +/- 0.5 x ATR14,
  merge zones that overlap, minimum 2 touches, lookback 200 candles. To be tested, not assumed.
