---
id: candle_basics
name: Candle (OHLCV) basics and candle completeness
kind: concept
category: Market data
status: PENDING_REVIEW
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 1. Basic market data concepts
  page: 2
  quote: A price candle summarises trading activity over a selected time interval.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 1. Basic market data concepts
  page: 2
  quote: A candle should normally be treated as complete only after its interval has ended and the data provider
    has confirmed the final values.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 1. Basic market data concepts
  page: 2
  quote: A candle pattern is not a guarantee of future price direction. Its usefulness must be tested on historical
    data and then monitored out of sample.
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

# Candle (OHLCV) basics and candle completeness

> **Origin: book**, section 1, page 2.

## Plain-language definition (source)
A candle summarises trading over one interval: Open (first price), High (highest), Low (lowest), Close (last) and
Volume (quantity traded, "where reliable volume data is available").

## Exact source-based conditions
- A candle is complete only after its interval has ended **and** the data provider has confirmed the final values.
- A candle pattern is not a guarantee of future direction; it must be tested on historical data and then monitored
  out of sample.

## How the current software follows it
- Patterns and signals use **closed candles only**: `app.py` drops the last candle while its interval is still
  running (`closed = df.iloc[:-1] if forming`). Tested in `tests/test_signal.py` (no look-ahead).
- "Provider has confirmed the final values": not checked. The app treats a candle as final once its interval has
  passed; Yahoo can still revise the last minute slightly.
- Out-of-sample monitoring: the self-learning model is judged only on candles it has never seen; the rule's track
  record is replayed candle by candle.

## Missing parameters and ambiguities
- How to detect "provider has confirmed": Not specified in source.
- Volume reliability: Not specified in source (index tickers such as ^NSEI report no volume on Yahoo).
