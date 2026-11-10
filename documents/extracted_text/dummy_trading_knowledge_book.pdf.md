# Trading Knowledge Starter Book
Extracted text of `dummy_trading_knowledge_book.pdf` (5 pages, 2026-11-09). Page numbers are the file's pages. Quote from here when citing.

---
## Page 1

TRADING KNOWLEDGE
STARTER BOOK
Dummy sample PDF for testing a Claude-assisted
trading knowledge extraction workflow
Target market
NIFTY 50 and BANK NIFTY (examples only)
Intended use
Document reading, concept extraction and rule structuring
Document type
Synthetic educational sample — not a published trading book
Version
1.0
IMPORTANT: This sample contains simplified, illustrative trading concepts and deliberately incomplete rules. It is
designed to test document ingestion and knowledge extraction—not to provide trading advice or ready-to-use profitable
strategies.

---
## Page 2

How to use this sample
Give this PDF to Claude Code and ask it to extract the concepts into structured Markdown files. The expected
output is a knowledge document that preserves definitions, conditions, ambiguities, source references and review
status.
Suggested extraction fields
 Concept name: the pattern or trading idea.
 Category: candlestick, chart pattern, support/resistance, volume or risk management.
 Market interpretation: what the concept may indicate.
 Identification conditions: observable rules based on OHLCV data.
 Confirmation: what additional evidence may strengthen the setup.
 Invalidation: what would make the setup no longer valid.
 Unknowns: any rule the source does not specify.
 Source reference: document title, chapter and page.
 Status: EXTRACTED or PENDING_REVIEW until a human approves it.
1. Basic market data concepts
A price candle summarises trading activity over a selected time interval. For a standard OHLC candle:
 Open: first traded price in the interval.
 High: highest traded price in the interval.
 Low: lowest traded price in the interval.
 Close: last traded price in the interval.
 Volume: quantity traded during the interval, where reliable volume data is available.
A 5-minute candle represents one five-minute interval. A candle should normally be treated as complete only after
its interval has ended and the data provider has confirmed the final values.
A candle pattern is not a guarantee of future price direction. Its usefulness must be tested on historical data and then
monitored out of sample.
2. Bullish Engulfing (illustrative concept)
Category: Two-candle candlestick pattern
Potential interpretation: possible bullish reversal, particularly after a decline.
Simplified description
The first candle has a bearish real body. The following candle has a bullish real body that fully covers the first
candle's real body. This description compares candle bodies, not necessarily the full high-low ranges.
Possible measurable conditions
 Previous candle: Close[1] < Open[1].
 Current candle: Close[0] > Open[0].
 Current real body covers the previous real body: Open[0] <= Close[1] and Close[0] >= Open[1].
 Evaluate only after the current candle is closed.

---
## Page 3

Context and possible confirmation
The pattern may be more meaningful after a decline or near a previously identified support area. A volume
increase or a later candle closing above the pattern high may be studied as additional confirmation. These are
hypotheses to test, not mandatory rules established by this sample.
Invalidation and unresolved choices
A close or trade below the pattern low may be used as an invalidation rule, but the exact rule (intrabar touch versus
candle close) must be chosen and documented. This sample does not prescribe an entry price, stop-loss buffer,
target, or expiry period.
Extraction note: Claude should preserve the distinction between the basic pattern definition and optional
confirmation ideas.
3. Bearish Engulfing (illustrative concept)
Category: Two-candle candlestick pattern
Potential interpretation: possible bearish reversal, particularly after an advance.
Simplified description
The first candle has a bullish real body. The next candle has a bearish real body that fully covers the first candle's
real body.
Possible measurable conditions
 Previous candle: Close[1] > Open[1].
 Current candle: Close[0] < Open[0].
 Current real body covers previous real body: Open[0] >= Close[1] and Close[0] <= Open[1].
 Evaluate only after the current candle is closed.
Context and possible confirmation
An advance before the pattern, a nearby resistance area, or increased volume may be studied as context. A later
candle closing below the pattern low may be evaluated as confirmation.
Unresolved choices
The sample does not define how large the bodies must be, how to measure the preceding trend, or how to set
entry, stop-loss and target. Those decisions require explicit review and testing.
4. Support and resistance (introductory concept)
Support: a price area where declines have previously paused or where buying interest may emerge.
Resistance: a price area where advances have previously paused or where selling interest may emerge.
These are better treated as zones than perfectly precise prices. A program needs a documented method to identify
them—for example, swing highs/lows within a specified lookback window, a tolerance around prices, and a rule for
merging nearby levels.
This sample does not define the lookback period, tolerance, minimum number of touches or breakout confirmation.
Claude must flag these as missing parameters rather than inventing values.
5. Volume confirmation (introductory concept)
Volume can provide context about participation during a price move. A simple research feature is the ratio of the
current completed candle's volume to the average volume of a defined number of prior completed candles.

---
## Page 4

Example formula: volume_ratio = current_volume / average(previous_N_volumes)
The value of N and any threshold are not specified here. The strategy developer must choose them for an
experiment, record the choice, and test whether the filter improves results without overfitting.
6. Signal outcome tracking
For an observation-only system, each generated signal should be stored with its timestamp, instrument, timeframe,
pattern, direction, reference entry, target, stop-loss and expiry rule.
Suggested outcomes
 ACTIVE: neither target nor stop-loss has been reached and the signal has not expired.
 TARGET_HIT: target was reached first under the chosen price-evaluation rule.
 STOPLOSS_HIT: stop-loss was reached first under the chosen price-evaluation rule.
 EXPIRED: the configured observation period ended without either level being reached.
 AMBIGUOUS: available candle data cannot establish which level was reached first.
If one candle's high and low cross both target and stop-loss, OHLC data alone does not reveal the order. Mark the result
AMBIGUOUS unless finer-grained data resolves it.
7. Risk and testing notes
A pattern's historical win rate alone is not enough to establish usefulness. A backtest should account for
transaction costs, slippage, realistic signal timing, data quality and the possibility of repeated or overlapping
signals.
Avoid look-ahead bias: a signal based on a candle must not be generated before that candle is complete. Keep
development data separate from out-of-sample evaluation data. Record all parameter choices.
No example in this sample is a recommendation to trade. NIFTY 50 and BANK NIFTY are indices; a later
instrument mapping step is needed if observing a tradable futures or options contract.
8. Instructions for Claude's extraction report
For every concept found in this PDF, produce a structured record with:
 Concept name and category.
 Plain-language definition.
 Exact source-based conditions.
 Potential interpretation (not a prediction guarantee).
 Confirmation ideas, clearly separated from core definition.
 Invalidation conditions.
 Missing parameters and ambiguities.
 Python implementation requirements.
 Suggested unit-test cases.
 Source document, chapter and page number.
 Knowledge status: PENDING_REVIEW.

---
## Page 5

Claude must not silently fill gaps. If a rule is absent, write 'Not specified in source'. Keep proposed research
parameters in a separate section labelled 'Experiment proposal'.
End of sample
