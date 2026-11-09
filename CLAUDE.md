# CLAUDE.md

Instructions for Claude Code working on this project: a trading knowledge and signal system for NIFTY 50,
BANK NIFTY, NSE/US stocks and crypto. Start the app with `python app.py` (http://127.0.0.1:5000).
The README covers how the app is used; this file covers how knowledge gets into the code.

## Architecture: knowledge first

Reading documents is the foundation of the system, not an optional step. Each layer maps to existing code:

| # | Layer | Where |
|---|---|---|
| 1 | Document reading (PDF books, notes, references) | `documents/uploaded_books/`, `document_reader/pdf_reader.py`, `text_extractor.py` -> `documents/extracted_text/` |
| 2 | Knowledge extraction (read, understand, extract, cite) | **Claude**, following this file; helpers in `document_reader/knowledge_extractor.py`, `source_reference.py` |
| 3 | Trading knowledge base (definitions, entry/exit, confirmation, invalidation, review) | `documents/extracted_knowledge/` (not approved), `knowledge/approved_*` (approved), `stockpatterns/knowledge.py`, `knowledge/knowledge_index.md` |
| 4 | Python strategy implementation (rules -> measurable conditions) | `stockpatterns/patterns.py` (pattern engine), `stockpatterns/signal.py` (trend + pattern rule), `stockpatterns/learner.py` (self-learning model) |
| 5 | Market data and pattern detection (NIFTY 50, BANK NIFTY, OHLCV) | `stockpatterns/feeds.py`, `markets.py`, `replay.py`, `patterns.detect()` |
| 6 | Signal generation (CALL / PUT / WAIT) | `stockpatterns/signal.recommend()`, `/api/signal` in `app.py` (applies the knowledge gate) |
| 7 | Observation and backtests (outcomes, pattern performance) | trade outcomes in `signal.run_trades()`, track record on the Live page, `/backtest`, Knowledge-page backtests (`backtest.pattern_performance`, `rule_performance`) |

Dashboard: **/knowledge** is for uploading documents, reading them, seeing extracted items, approving or rejecting
them, checking what is implemented, and viewing backtest results.

**The live signal must never depend on an LLM response for any candle.** It runs deterministic Python rules and
uses only knowledge that is IMPLEMENTED or BACKTESTED (the gate is `KnowledgeBase.gate()`, read from the files).

## Document reading and knowledge extraction

`documents/` is the primary source of trading knowledge. Before implementing any trading strategy:

1. Check every document in `documents/uploaded_books/`.
2. Read the relevant ones: `python -m document_reader read <file>` (or `--all`). This writes
   `documents/extracted_text/<file>.md` with the text page by page, and prints every section with the knowledge
   files that already cover it. Read the original PDF too (the Read tool shows pages), because tables and figures
   can be lost in plain text.
3. Extract concepts, patterns and strategies, one Markdown file each (format below).
4. Record the source document, section/chapter and page for every claim, with a short **verbatim quote** from
   that page. Quotes are checked automatically (`python -m document_reader check`): a quote that is not on its
   cited page is an error.
5. Create the files in `documents/extracted_knowledge/{patterns,strategies,concepts}/` with status
   `PENDING_REVIEW`.
6. Keep original source knowledge separate from suggestions: proposed parameters go in a section titled
   **"Experiment proposal (NOT from the source)"**.
7. Find incomplete or conflicting conditions. Write `Not specified in source` for every missing rule, and list
   each gap under "Missing parameters and ambiguities". When the source conflicts with the existing code, add an
   "Existing code vs source" table and a `decision_needed` field.
8. **Never invent information and attribute it to a book.** Never fill a gap silently.
9. Sections with no trading knowledge (forewords, instructions) go under `skipped_sections` in
   `documents/extracted_knowledge/document_notes.yaml`, with the reason, so the coverage report stays honest.
10. Finish with `python -m document_reader read <file>`: every section should show as covered or skipped. Then
    run `python -m document_reader check`, which must report no problems.

### Knowledge file format

```markdown
---
id: bullish_engulfing            # = file name, lowercase_with_underscores
name: Bullish Engulfing
kind: pattern                    # pattern | strategy | concept
category: 2-candle candlestick pattern
status: PENDING_REVIEW
direction: bullish               # patterns: bullish | bearish | neutral
candles: 2
code_name: Bullish Engulfing     # patterns: the name patterns.detect() returns (PATTERN_NAMES)
origin: book                     # book | existing-code
implemented_in: stockpatterns/patterns.py (detect)   # ONLY when the code follows THIS definition exactly
tests: tests/test_patterns.py
sources:
- document: dummy_trading_knowledge_book.pdf
  title: Trading Knowledge Starter Book (dummy sample)
  section: 2. Bullish Engulfing (illustrative concept)
  page: 2
  quote: Evaluate only after the current candle is closed.
decision_needed: optional question for the reviewer
history:
- {date: '2026-11-05', status: PENDING_REVIEW, by: claude, note: extracted from ...}
---
# Bullish Engulfing
## Category and interpretation        (interpretation is not a prediction guarantee)
## Plain-language definition
## Exact source-based conditions       (measurable OHLCV conditions, with page)
## Confirmation ideas                  (kept separate from the core definition)
## Invalidation
## Missing parameters and ambiguities  ("Not specified in source")
## Existing code vs source             (when code already exists)
## Python implementation requirements
## Suggested unit-test cases
## Experiment proposal (NOT from the source)
```

## Knowledge approval workflow

Every item has exactly one status, and its folder follows it automatically:

| Status | Meaning | Folder |
|---|---|---|
| EXTRACTED | raw extraction, not yet structured | `documents/extracted_knowledge/<kind>s/` |
| PENDING_REVIEW | structured, waiting for the user | same |
| REJECTED | the user rejected it (kept for the record) | same |
| APPROVED | the user accepted the definition | `knowledge/approved_<kind>s/` |
| IMPLEMENTED | approved, with Python code and tests that follow it (`implemented_in`) | same |
| BACKTESTED | implemented and measured on history (results stored in the file) | same |

- **Only the user approves or rejects.** They do it on the Knowledge page, or ask for it explicitly. Claude never
  sets APPROVED by itself.
- Change statuses through `KnowledgeBase.set_status()`, the page, or
  `python -m stockpatterns.knowledge status <kind> <id> <STATUS> --note "..."`, never by hand, so the folder,
  history and `knowledge/knowledge_index.md` stay consistent.
- Approving an item whose `implemented_in` code already follows the definition makes it IMPLEMENTED at once.
- Only APPROVED knowledge may be implemented. Only IMPLEMENTED and BACKTESTED knowledge is used by the live signal.
- If the user changes an approved definition, move it back to PENDING_REVIEW until they approve it again.

## Knowledge-to-code workflow

For every APPROVED pattern or strategy without code:

1. Read its knowledge file, including the user's review note (`review.note`): it records their decisions, for
   example "follow the book exactly".
2. Turn every condition into an objective, measurable rule on closed candles only (no look-ahead).
3. Implement it in Python (`patterns.py` for patterns: add the name to `PATTERN_NAMES`).
4. Write unit tests, including the "Suggested unit-test cases" from the file.
5. Validate it on historical candles (`pattern_performance` / the Backtest page).
6. Set `implemented_in` and `tests`, then set the status to IMPLEMENTED. The gate now lets the signal use it.
   The user can then run the backtest on the Knowledge page (BACKTESTED).

## Commands

```
python app.py                                    # dashboard: / live, /test replay, /backtest, /knowledge
python -m document_reader read --all             # extract text + coverage report of every uploaded book
python -m document_reader check                  # verify every source quote is on its cited page
python -m stockpatterns.knowledge gate           # what the live signal may use right now
python -m stockpatterns.knowledge index          # rewrite knowledge/knowledge_index.md
python -m unittest discover -s tests -t .        # Python tests (~1 min)
node --test tests/                               # JS tests (drawings, indicators, extension)
```

## Rules for code changes

- No look-ahead: a signal on a candle only uses that candle and older ones (tested in `test_signal.py`,
  `test_learner.py`).
- Backtests report development (first 70%) and out-of-sample (last 30%) results separately, and say that costs
  and slippage are not included.
- Tests never touch the real `knowledge/` or `documents/` folders: use `tests/kb_helpers.make_kb()`.
- The Chrome extension (`chrome-extension/`) only works locally; leave it alone unless asked.
- Nothing here is financial advice; say so wherever results are shown.
