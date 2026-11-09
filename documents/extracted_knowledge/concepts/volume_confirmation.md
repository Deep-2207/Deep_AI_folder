---
id: volume_confirmation
name: Volume confirmation (volume ratio)
kind: concept
category: Volume
status: PENDING_REVIEW
origin: book
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 5. Volume confirmation (introductory concept)
  page: 3
  quote: Volume can provide context about participation during a price move.
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 5. Volume confirmation (introductory concept)
  page: 4
  quote: 'Example formula: volume_ratio = current_volume / average(previous_N_volumes)'
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 5. Volume confirmation (introductory concept)
  page: 4
  quote: The value of N and any threshold are not specified here.
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

# Volume confirmation (volume ratio)

> **Origin: book**, section 5, pages 3-4. **Not implemented** as a filter (the self-learning model already
> uses a similar number as one of its inputs).

## Plain-language definition (source)
Volume gives context about participation in a move. Research feature: the current **completed** candle's volume
divided by the average volume of a defined number of prior completed candles.

## Exact source-based formula (p. 4)
`volume_ratio = current_volume / average(previous_N_volumes)`

## Missing parameters and ambiguities
- N (number of prior candles): Not specified in source.
- Threshold for "increased volume": Not specified in source.
- What to do when volume is missing (indices like ^NSEI / ^NSEBANK have no volume on Yahoo): Not specified in source.

## Python implementation requirements
- Use completed candles only; the previous N candles exclude the current one.
- Return "not available" (not 0 or 1) when volume data is missing, so the filter cannot silently pass or fail.

## Experiment proposal (NOT from the source)
- N = 20, threshold 1.5; compare Engulfing results with and without the filter on stocks that report volume
  (index volume is missing). Record the choice and check it out of sample, as p. 4 asks.
