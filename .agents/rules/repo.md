---
description: Repo map and working boundaries for StockMarketProject. Always apply.
alwaysApply: true
trigger: always_on
---

# Repo map

StockMarketProject: Live candlestick pattern scanner and trade signal system (NIFTY 50, BANK NIFTY, NSE/US stocks, crypto).

| Path | Contents |
|---|---|
| `app.py` | Flask web server and API endpoints (`/`, `/test`, `/backtest`, `/knowledge`) |
| `stockpatterns/` | Core engine: patterns (`patterns.py`), signals (`signal.py`), ML model (`learner.py`), feeds (`feeds.py`), replay (`replay.py`) |
| `document_reader/` | Document ingestion (`pdf_reader.py`) and quote citation verifier (`source_reference.py`) |
| `documents/` | Uploaded books, extracted text, unapproved knowledge (`PENDING_REVIEW`) |
| `knowledge/` | Approved, implemented, and backtested knowledge base (`knowledge_index.md`) |
| `static/` | Web frontend: charts, drawing tools, indicators, NIFTY 500 autocomplete |
| `tests/` | Python test suite (`python -m unittest discover -s tests -t .`) and JS tests (`node --test tests/*.test.js`) |
| `chrome-extension/` | Manifest V3 companion extension for browser alerts and live signals |

# Working rules

- Knowledge First: Never use an unapproved pattern or strategy in live signals. Knowledge gate is strictly enforced.
- No look-ahead: Candles used for patterns and signals must be closed candles only.
- Test integrity: Always verify Python tests and JS tests before concluding work.
- English in repo: All code, docstrings, commits, and comments stay in English.
