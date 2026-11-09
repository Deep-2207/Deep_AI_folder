---
id: signal_outcome_tracking
name: Signal outcome tracking
kind: concept
category: Risk management / observation
status: PENDING_REVIEW
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 6. Signal outcome tracking
  page: 4
  quote: For an observation-only system, each generated signal should be stored with its timestamp, instrument,
    timeframe, pattern, direction, reference entry, target, stop-loss and expiry rule.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 6. Signal outcome tracking
  page: 4
  quote: 'ACTIVE: neither target nor stop-loss has been reached and the signal has not expired.'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 6. Signal outcome tracking
  page: 4
  quote: 'AMBIGUOUS: available candle data cannot establish which level was reached first.'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 6. Signal outcome tracking
  page: 4
  quote: If one candle's high and low cross both target and stop-loss, OHLC data alone does not reveal the order.
decision_needed: Adopt the AMBIGUOUS outcome (code change), or keep 'stop first' as a documented deviation?
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

# Signal outcome tracking

> **Origin: book**, section 6, page 4. **Partly implemented, with one conflict** (see below).

## Plain-language definition (source)
Every generated signal is stored with: timestamp, instrument, timeframe, pattern, direction, reference entry,
target, stop-loss and expiry rule; and gets one outcome:

| Outcome (source) | Meaning (source) | Current software |
|---|---|---|
| ACTIVE | neither target nor stop reached, not expired | "IN CALL/PUT: HOLD" (open trade) |
| TARGET_HIT | target reached first | exit `target` |
| STOPLOSS_HIT | stop-loss reached first | exit `stop` |
| EXPIRED | observation period ended, neither level reached | exit `timeout` (4 x look-ahead) or `close` (market close) |
| AMBIGUOUS | candle data cannot tell which level came first | **not used**: the code assumes the stop came first |

## Conflict with the current code
The source says: if one candle's high and low cross both target and stop-loss, mark the result AMBIGUOUS unless
finer data resolves it. `stockpatterns/signal.py` (`run_trades`) and the drawing tools instead **assume the stop was
hit first** (a pessimistic choice). Decision needed when approving: adopt AMBIGUOUS (and decide how it counts in the
track record), or keep "stop first" as a documented deviation.

## Missing parameters and ambiguities
- "Chosen price-evaluation rule" (touch vs close): Not specified in source. Current code: intrabar touch.
- Expiry period: Not specified in source. Current code: 4 x look-ahead candles, plus intraday square-off.
- Storage: the signal's pattern is not stored per trade today; the track record is recomputed, not saved.

## Python implementation requirements
- A stored, append-only signal log (one row per signal with the fields above) and an outcome updater that only uses
  candles after the signal candle.
- AMBIGUOUS when both levels are inside one candle (unless 1-minute data resolves it).
