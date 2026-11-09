---
id: bearish_engulfing
name: Bearish Engulfing
kind: pattern
category: 2-candle candlestick pattern
status: PENDING_REVIEW
direction: bearish
candles: 2
code_name: Bearish Engulfing
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 3. Bearish Engulfing (illustrative concept)
  page: 3
  quote: 'Category: Two-candle candlestick pattern'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 3. Bearish Engulfing (illustrative concept)
  page: 3
  quote: The first candle has a bullish real body. The next candle has a bearish real body that fully covers the
    first candle's real body.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 3. Bearish Engulfing (illustrative concept)
  page: 3
  quote: 'Current real body covers previous real body: Open[0] >= Close[1] and Close[0] <= Open[1].'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 3. Bearish Engulfing (illustrative concept)
  page: 3
  quote: Evaluate only after the current candle is closed.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 3. Bearish Engulfing (illustrative concept)
  page: 3
  quote: The sample does not define how large the bodies must be, how to measure the preceding trend, or how to
    set entry, stop-loss and target.
decision_needed: 'The current code is stricter than the book (it also requires a prior trend and a strictly larger
  body). Choose: A) follow the book exactly (code will be changed), or B) keep the code''s extra conditions as a
  documented deviation.'
history:
- date: '2026-11-05'
  status: EXTRACTED
  by: claude
  note: read dummy_trading_knowledge_book.pdf p. 3
- date: '2026-11-05'
  status: PENDING_REVIEW
  by: claude
  note: extracted from dummy_trading_knowledge_book.pdf
---

# Bearish Engulfing

> **Origin: book.** Extracted from *Trading Knowledge Starter Book (dummy sample)*, section 3. Bearish Engulfing (illustrative concept), page 3.
> Status PENDING_REVIEW: **a decision is needed before approval** (see "Existing code vs source").

## Category and interpretation
- Category (source, p. 3): two-candle candlestick pattern.
- Potential interpretation (source, p. 3): possible bearish reversal, particularly after an advance.
  This is an interpretation, not a prediction guarantee.

## Plain-language definition
The first candle has a bullish real body; the next candle has a bearish real body that
fully covers the first candle's real body. Only the bodies are compared, not the full high-low ranges.

## Exact source-based conditions (p. 3)
`[1]` = previous candle, `[0]` = current (pattern) candle.
1. Previous candle: `Close[1] > Open[1]`
2. Current candle: `Close[0] < Open[0]`
3. Current real body covers the previous real body: `Open[0] >= Close[1] and Close[0] <= Open[1]`
4. Evaluate only after the current candle is closed.

## Confirmation ideas (separate from the definition, source p. 3)
An advance before the pattern, a nearby resistance area, or increased volume may be studied as context. A later candle closing below the pattern low may be evaluated as confirmation.
The book calls these "hypotheses to test, not mandatory rules" (same section style). They are **not** part of the definition.

## Invalidation
Not specified in source (section 3 gives no invalidation rule).

## Missing parameters and ambiguities
- Minimum body size of either candle: Not specified in source.
- How to measure the preceding advance (if required at all): Not specified in source.
- Entry price, stop-loss buffer, target, expiry period: Not specified in source.
- Equality at the edges (`<=` / `>=`): the source uses inclusive comparisons, so equal open/close counts as covering.
- Invalidation: Not specified in source.

## Existing code vs source
The scanner already detects a "Bearish Engulfing" (`stockpatterns/patterns.py`), but **not with exactly the book's rule**:

| Condition | Book (p. 3) | Current code |
|---|---|---|
| Previous candle colour | green (`Close[1] > Open[1]`) | same |
| Current candle colour | red (`Close[0] < Open[0]`) | same |
| Body covers body | `Open[0] >= Close[1] and Close[0] <= Open[1]` | same |
| Body size | not required | body[0] must be **strictly larger** than body[1] |
| Prior trend | context only ("particularly after an advance") | **required**: prior trend of [1] is UP (5-candle close change above 1 x ATR14) |
| Evaluated on closed candles only | yes | yes |

Because the code differs, this file has no `implemented_in` yet: approving it will NOT switch it on in the live
signal until the code follows the approved definition (status IMPLEMENTED).

## Python implementation requirements
- A function on closed candles that returns the candle index where all source conditions hold.
- Use only candles `[1]` and `[0]` (no future candles).
- Keep the optional confirmations as separate, switchable filters so they can be tested on their own.

## Suggested unit-test cases
- Textbook case: `[1]` O=105 C=100, `[0]` O=99 C=106 -> detected.
- Edge equality: `Open[0] == Close[1]` and `Close[0] == Open[1]` -> detected (inclusive).
- Body not covered: `[0]` C=104 (< Open[1]=105) -> not detected.
- Wrong colours (both green) -> not detected.
- Forming (unclosed) last candle -> not evaluated.

## Experiment proposal (NOT from the source)
- Test the book's definition alone vs. with the code's extra conditions (prior trend, larger body) on NIFTY 50 and
  BANK NIFTY, on development data, then check the winner on later, separate (out-of-sample) data.
- Test the confirmations from p. 3 one at a time: volume ratio (see the Volume confirmation concept) and a later
  close below the pattern low.
