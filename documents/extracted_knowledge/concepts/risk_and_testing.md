---
id: risk_and_testing
name: Risk and testing rules
kind: concept
category: Risk management / testing
status: PENDING_REVIEW
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 7. Risk and testing notes
  page: 4
  quote: A pattern's historical win rate alone is not enough to establish usefulness.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 7. Risk and testing notes
  page: 4
  quote: A backtest should account for transaction costs, slippage, realistic signal timing, data quality and the
    possibility of repeated or overlapping signals.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 7. Risk and testing notes
  page: 4
  quote: 'Avoid look-ahead bias: a signal based on a candle must not be generated before that candle is complete.'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 7. Risk and testing notes
  page: 4
  quote: Keep development data separate from out-of-sample evaluation data. Record all parameter choices.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 7. Risk and testing notes
  page: 4
  quote: NIFTY 50 and BANK NIFTY are indices; a later instrument mapping step is needed if observing a tradable
    futures or options contract.
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

# Risk and testing rules

> **Origin: book**, section 7, page 4.

## Rules (source)
1. A historical win rate alone does not prove usefulness.
2. Backtests should account for transaction costs, slippage, realistic signal timing, data quality and repeated or
   overlapping signals.
3. No look-ahead: no signal before its candle is complete.
4. Keep development data separate from out-of-sample data; record all parameter choices.
5. NIFTY 50 and BANK NIFTY are indices: trading a future or option needs a separate instrument-mapping step.

## How the current software compares
| Rule | Current software |
|---|---|
| Win rate not enough | Pattern study compares each pattern with the up-rate of *any* candle; the rule reports average R |
| Costs and slippage | **Not included** anywhere (README says so) |
| Realistic timing | Entry at the signal candle's close; no look-ahead (tested) |
| Overlapping signals | One trade at a time + one-candle cool-down |
| Out-of-sample | Model: walk-forward. Knowledge-page backtests: first 70% vs last 30% reported separately |
| Parameter record | Constants at the top of `signal.py` / `patterns.py`; not yet written into strategy files per run |
| Instrument mapping | Not done: signals are on the index / stock price, not on an option premium |

## Missing parameters and ambiguities
- Cost and slippage values: Not specified in source.
- Development / out-of-sample split: Not specified in source.
