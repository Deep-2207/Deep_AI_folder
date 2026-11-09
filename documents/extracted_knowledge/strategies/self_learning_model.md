---
id: self_learning_model
name: Self-learning model (gradient-boosted trees)
kind: strategy
category: Strategy
status: PENDING_REVIEW
origin: existing-code
implemented_in: stockpatterns/learner.py
tests: tests/test_learner.py
sources: []
history:
- date: '2026-11-05'
  status: PENDING_REVIEW
  by: claude
  note: written from the existing code
---

# Self-learning model (gradient-boosted trees)

> **Origin: existing code.** A statistical model trained on each chart's own candles; not taken from a book.
> Approving it allows it to take over the trade signal (in Auto, only after passing its own gate).

## What it does (as coded)
- About 20 numbers per candle (trend, pattern score, RSI, recent moves, body/wicks, range position, volatility,
  volume, time of day), using only that candle and older ones.
- Learns the expected R of a CALL and of a PUT with exactly the rule's stop, target and exits; trains after 800
  finished lessons, re-trains every 200 candles. Paper-trades each new candle with a model that never saw it.
- Enters when it expects more than +0.10R.

## Its own gate (as coded)
Takes over (Auto mode) only when: >= 100 paper trades on unseen candles, average R - 2 x standard error > 0, and its
average beats the rule's on the same candles.

## Note on the knowledge gate
Its pattern features use **all** coded patterns (not only approved ones), because changing its inputs would
invalidate its stored paper record. Reject this strategy if you want only approved patterns to influence signals.
