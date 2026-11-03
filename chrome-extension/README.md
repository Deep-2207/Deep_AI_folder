# Pattern Scanner - Chrome extension

A toolbar companion for the local scanner at http://127.0.0.1:5000. It only talks to that address.

## Install (developer mode, no Chrome Web Store needed)

1. Start the server: `cd D:\Deep_AI\StockMarketProject` then `python app.py`
2. Open `chrome://extensions` in Chrome
3. Turn on **Developer mode** (top right)
4. Click **Load unpacked** and choose this folder: `D:\Deep_AI\StockMarketProject\chrome-extension`
5. Pin it: puzzle-piece icon in the toolbar, then the pin next to "Pattern Scanner (local)"

After editing any file here, press the reload icon on the extension's card in `chrome://extensions`.

## What it does

- **Popup**: the same trade signal as the Live page: **BUY CALL NOW / BUY PUT NOW**, **IN CALL / IN PUT: HOLD**,
  **EXIT: TARGET HIT / STOP HIT**, **WAIT** (with the reason) or **MARKET CLOSED**, plus entry, stop-loss, target,
  the Trend and Patterns votes, the last trade and the track record, plus which logic gave the signal (the fixed
  rule, or the self-learning model once it has proven itself) and the model's state. Refreshes every 15 s.
  Markets: US stocks, NSE stocks, crypto, NSE replay, seeder.
- **Badge** on the toolbar icon: `CALL` (green) / `PUT` (red) while a trade is on, `WAIT`, `OFF` when the market is
  closed, ✓ / ✗ when the live candle hits the target / stop, `!` when the server is not running. Checked every minute.
- **Desktop alerts** (tick the box in the popup): when a new CALL/PUT trade starts (with entry, stop and target; if it
  was found a candle late, it says so) and when a trade ends (target, stop, time limit or market close).
  Clicking an alert opens the Live page (or the Test Lab for NSE replay / Seeder).
- Buttons to open the Live, Test Lab and Backtest pages.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | Manifest V3; permissions: storage, alarms, notifications; host access only to `http://127.0.0.1:5000/*` |
| `popup.html`, `popup.js` | The popup |
| `background.js` | Service worker: badge + alerts every minute |
| `common.js` | Settings and API helpers shared by both |
| `icons/` | Toolbar icons |

For learning and testing only. Not financial advice.
