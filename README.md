# Live Candlestick Pattern Scanner

Pulls live candles from free, keyless APIs and detects candlestick / chart patterns on them.

## Run

```
pip install -r requirements.txt
python app.py            # dashboard at http://127.0.0.1:5000
python -u live_cli.py    # or terminal scanner (BTCUSDT 1m)
python -m unittest discover -s tests -t .
```

CLI examples:
```
python -u live_cli.py --provider yahoo --symbol AAPL
python -u live_cli.py --provider yahoo --symbol RELIANCE.NS --poll 15
python -u live_cli.py --symbol ETHUSDT --interval 5m
```

## Data feeds (no API key)

| Provider | Covers | Notes |
|---|---|---|
| `binance` | crypto (`BTCUSDT`, `ETHUSDT`...) | Truly live and 24/7, best for testing any time of day |
| `yahoo` | stocks (`AAPL`, `TSLA`, `RELIANCE.NS`, `TCS.NS`) | Only moves during market hours; the UI flags a stale feed. Poll >= 10s to avoid rate limits |

Both are polled (REST), not websockets. Add a provider by writing a function that returns the candle DataFrame in `stockpatterns/feeds.py`.

## Patterns detected (`stockpatterns/patterns.py`)

- 1 candle: Doji, Dragonfly/Gravestone Doji, Hammer, Hanging Man, Inverted Hammer, Shooting Star, Marubozu
- 2 candles: Bullish/Bearish Engulfing, Harami, Piercing Line, Dark Cloud Cover, Tweezer Top/Bottom
- 3 candles: Morning/Evening Star, Three White Soldiers, Three Black Crows
- Chart: Double Top / Double Bottom (swing pivots, flags whether the neckline broke)

Reversal patterns only fire when the preceding 5 candles trended the right way. `confidence` is a heuristic
score (trend context + candle size), not a probability of profit. The newest candle is marked **forming**
until it closes, and patterns on it can still disappear.

## Prediction in points (latest pattern only)

The dashboard and CLI show only the most recent pattern and answer: *"last time this pattern appeared, how many
points did price move afterwards?"*

1. Loads up to 5,000 candles of history (Binance 1m is about 3.5 days; Yahoo returns what it has).
2. Finds every earlier occurrence of the same pattern and measures `close[after N candles] - close[at pattern]`
   (N = the "look ahead" selector; cases that span an overnight gap are skipped).
3. Prediction = **median** of those moves, in points and %; dotted lines = 25th to 75th percentile range.
   Needs >= 8 past cases, otherwise it falls back to the textbook direction and 2x ATR.
4. **Edge** compares the pattern's up-rate with the up-rate of *all* candles in the same window, so a falling
   market isn't mistaken for a bearish pattern. "No clear edge" means no better than a coin-flip.

On the chart: dashed line = predicted move from the pattern candle, grey dots = earlier cases of the same pattern.
Only closed candles count as evidence, so a pattern appears once its candle closes.

## Backtest Lab (http://127.0.0.1:5000/backtest)

Study old data 20 candles at a time (`stockpatterns/backtest.py`, `static/backtest.html`).

- Sources: NSE stocks/indices (Yahoo, daily goes back ~10 years), crypto (Binance), global (Yahoo). Timeframes 1d to 1m.
- Patterns: Hammer and Inverted Hammer (textbook UP), optionally Hanging Man and Shooting Star (same shapes after a rise, textbook DOWN).
- Navigation: Prev/Next 20 (or arrow keys), first/last, a slider, and Prev/Next pattern to jump between occurrences.
- Each pattern is explained rule by rule with its measured values (body %, wick vs body, the fall before it in ATR),
  then what happened after N candles (move, best rise and worst drop on the way, WORKED or FAILED).
- Results over the whole history per pattern: how often it worked, compared with how often ANY candle was followed by a rise.
- **Quiz mode** hides the candles after the pattern so you guess Higher or Lower first; your score is kept in the browser.

## NSE Test Lab (http://127.0.0.1:5000/test)

A separate page for practising when the market is closed. The live page at `/` is unchanged. Candles are
replayed as if live (`stockpatterns/replay.py`), with Play/Pause, Next candle, speed, a time slider and New data.

| Source | What it plays |
|---|---|
| **NSE replay** | Real past NSE candles from Yahoo: `RELIANCE`, `TCS`, `HDFCBANK`, `INFY`, `SBIN`... (`.NS` is added for you), `^NSEI` = NIFTY 50, `^NSEBANK` = Bank Nifty. About 7 days of 1m, a month of 5m/15m |
| **Pattern seeder** | Synthetic NSE-like data (09:15-15:30 IST sessions, Rs 0.05 ticks) full of textbook patterns. The closing price is a pure random walk; each candle's shape (wicks, small gaps) is drawn from the candles before it and its own close only, never from the future. **Follow-through** sets how often price ends up moving the textbook way after a pattern: at 50% patterns carry no information and there is nothing at all to predict, at 85-95% patterns really work |

Use the seeder to check the software itself (6 random markets each, only candles after the first 1,000):

| Follow-through | Trade rule | Self-learning model |
|---|---|---|
| 50% (nothing to learn) | +0.02R per trade (+/-0.06, i.e. zero) | -0.00R per trade (+/-0.04) |
| 85% (patterns work) | +0.33R per trade | +0.41R per trade |

Every planted pattern is detected and the follow-through rate matches the setting (tested). An earlier version
planted ready-made multi-candle shapes: their later candles could be predicted from the first one, and a learning
model made +0.18R per trade from that even at 50%. That is fixed, and tested with the model itself.

## Trade signal: when to take a CALL or a PUT

The right-hand panel of the live page always shows ONE instruction (`stockpatterns/signal.py`), made by the fixed rule
below, or by the self-learning model once it has proven itself (next section). It updates by itself whenever a candle
closes; the browser tab title shows it too, so you see it from other tabs.

| Banner | Meaning |
|---|---|
| **▲ BUY CALL NOW** / **▼ BUY PUT NOW** | A new signal on the candle that just closed. Enter now; once the next candle closes it is too late (don't chase). |
| **IN CALL / IN PUT: HOLD** | A trade is running: entry, stop-loss, target, live P/L and a stop-to-target progress bar. |
| **✓ EXIT: TARGET HIT** / **✗ EXIT: STOP HIT** | The live candle reached the target or the stop-loss: close the trade. |
| **WAIT: NO TRADE** | No signal, with the exact reason (e.g. "Trend is UP. Waiting for a bullish pattern"). |
| **MARKET CLOSED** | The data is not live: don't act on it. |

**CALL** = you profit if price goes UP. **PUT** = you profit if price goes DOWN.

The rule has two votes and both must agree:

- **Trend**: EMA20 vs EMA50 (in ATRs). UP, DOWN or FLAT.
- **Patterns**: candlestick patterns of the last few candles, judged by how price behaved after them *earlier on
  this chart* compared with any candle. BULLISH, BEARISH or NONE. (A textbook-bearish pattern that keeps being
  followed by rises counts as bullish here; the Pattern study card says so in plain words.)
- **CALL** = Trend UP + Patterns BULLISH. **PUT** = Trend DOWN + Patterns BEARISH. Anything else = WAIT.

Requiring agreement gave fewer but better trades than the earlier blended score on live US/NSE stocks, and it never
shows a CALL while the patterns point down. Trades: one at a time, enter at the signal candle's close, stop = 1.5 x ATR,
target = 2 x the stop distance, exit at stop / target / 4 x look-ahead candles, intraday trades squared off at the
market close, one-candle cool-down after each exit.

On the chart, ▲ CALL / ▼ PUT arrows mark where the rule entered and ✓ / ✗ / ⏱ how each trade ended; the current
(or last) trade is drawn as a CALL/PUT box. The **track record** box backtests the same rule on the loaded history
(no look-ahead, tested) and says plainly when it lost money. No fees or slippage are included.

## Self-learning model (auto-train, auto-upgrade)

The "Self-learning model" card on the live page (and the Test Lab) is a small machine-learning model per chart
(`stockpatterns/learner.py`, scikit-learn gradient-boosted trees) that keeps training itself and paper-trades next to
the rule. It is not an AI chat model: it learns only from this chart's candles, in about a second, on the CPU.

1. **Lessons**: every candle becomes a lesson once its trade is over: "a CALL bought at this close made +2R" (or -1R,
   or a time-limit / market-close result), with exactly the rule's stop-loss, target and exits; a PUT likewise.
2. **What it looks at**: about 20 numbers per candle: trend, pattern score, RSI, the last 1/3/5/10/20-candle moves,
   candle body and wicks, place in the 20-candle range, volatility, volume, time of day. All use only that candle and
   older ones. The card shows which of them its opinion depends on most (that is not proof that it works).
3. **Auto-train**: once 800 lessons have finished it trains two models (expected R of a CALL and of a PUT), then it
   re-trains by itself every 200 new candles on every lesson finished so far. **Retrain now** forces a new version.
4. **Paper trading**: each new candle is judged by the newest model, which has never seen it: CALL or PUT when it
   expects more than +0.10R, otherwise WAIT. These decisions are stored and never changed: they are its track record,
   shown next to the rule's on the same candles.
5. **Auto-upgrade (the gate)**: in **Auto** mode it takes over the trade signal only when all three are true:
   at least 100 paper trades on unseen candles; its average R minus 2 x its luck margin (standard error) is above 0;
   and its average beats the rule's on the same candles. If its record later drops below that, the rule takes over
   again by itself. **Rule only** never uses it; **Model only** uses it even unproven (practice only, shown in red).

While the rule is in charge, the model's opinion is shown in grey as "paper only, not a signal", so the banner stays
the one thing to follow. The Chrome extension follows the same logic (Auto) and shows the model's state.

**Saved and growing**: live charts are saved in `models/<chart>/` (`candles.csv`, `paper_decisions.csv`,
`model.joblib`, `meta.json`), so its history (up to 20,000 candles) and lessons keep growing every day the app runs,
beyond Yahoo's 7 days of 1-minute data. **Reset** deletes that folder. Test Lab charts are kept in memory and start
over when the replay data changes.

**Honest results so far** (walk-forward, only candles the model had never seen): on 10 real charts (US, NSE, crypto,
NIFTY daily) it made about +0.01R per trade over 1,500 trades, against +0.10R for the rule; one model trained on six
stocks together did worse (-0.06R). Tested on the candles it had learned from, the same model looked like +0.82R per
trade: that illusion is exactly what the gate protects you from. On the seeder it finds the edge where there is one
(85%) and nothing where there is none (50%). So expect "Not passed yet" on most real charts for now; more saved
history is what could change that.

Tested (`tests/test_learner.py`): no look-ahead (changing every candle after a point never changes an earlier
decision), lessons equal the trade engine's results, feeding candles batch by batch gives the same decisions as all
at once, re-training every 200 candles, the gate, saving and loading, Test Lab resets, and the API.

## Live stocks instead of crypto

- **US stocks (live)**: Yahoo's 1-minute data is live during US hours (20:00-02:30 IST in winter, 19:00-01:30 in summer).
- **NSE India stocks**: type `SBIN`, `MCX`, `RELIANCE`... (`.NS` is added). Live during 09:15-15:30 IST.
- The market lights in the header show which exchange is open (holidays are not included).
- **🔥 Movers** ranks liquid, usually-volatile stocks by their average 1-minute candle in the last hour, so you can pick
  one that is really moving (US: SOXL, RIOT, MARA, PLTR, COIN, AMD...; NSE: MCX, ANGELONE, SBIN, DIXON, BSE...).
- On page load the app starts on a market that is open (NSE in the Indian daytime, US in the evening).

## Drawing tools (left toolbar, like TradingView)

| Tool | How |
|---|---|
| Select | default; click a drawing to select it, drag to move, `Delete` removes it, `Esc` deselects |
| **CALL** / **PUT** box | click once on the chart, then drag the handles: top = target, bottom = stop-loss, right = width. Drag the body to move the whole box |
| Trend line | click, move, click again (or press-drag-release) |
| Horizontal line | one click |
| Ruler | two clicks: shows points, % and candles between them |
| Magnet / Lock / Hide / Trash | snap to OHLC, block accidental edits, hide all drawings, delete selected (or all) |

A CALL/PUT box shows entry, target and stop in points and %, the R:R ratio, and whether price has since hit the
target or the stop (stop is assumed first if both fall inside one candle). The "Your trade boxes" panel lists them
with live P/L. The prediction card has a **Draw box from this prediction** button. Drawings are saved in the browser
per symbol and are anchored on time and price, so they stay put across zoom, refresh and timeframe changes.
Candles older than the 300 shown are not checked for hits.

Tests: `python -m unittest discover -s tests -t .` (Python, about a minute) and
`node --test tests/drawings.test.js tests/extension_background.test.js` (drawing tools, Chrome extension).

Thresholds are constants at the top of `detect()`; tune them per market and timeframe.
Not financial advice.
