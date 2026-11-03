"""Live dashboard: python app.py  ->  http://127.0.0.1:5000"""
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from stockpatterns.feeds import INTERVAL_SECONDS, FeedError, get_candles, get_history
from stockpatterns.patterns import detect, predict
from stockpatterns import learner, markets, replay
from stockpatterns.backtest import TEXTBOOK, study
from stockpatterns.signal import recommend

HISTORY_CANDLES = 5000   # candles used as "past data" for the statistics

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/test")
def test_page():
    """Same dashboard in test mode: NSE replay / pattern seeder instead of live feeds."""
    html = open(app.static_folder + "/index.html", encoding="utf-8").read()
    html = html.replace('<script src="/static/drawings.js"></script>',
                        '<script src="/static/testmode.js"></script>\n<script src="/static/drawings.js"></script>', 1)
    return Response(html, mimetype="text/html")


def load(provider, symbol, interval):
    """(candles, last candle still forming?, feed stale?) from a live feed or a replay session."""
    sec = INTERVAL_SECONDS.get(interval)
    if provider in replay.PROVIDERS:
        df, forming = replay.session(provider, symbol, interval).view()
        if df.empty:
            raise FeedError("replay has no candles yet")
        return df, forming, False
    if provider == "nse":                          # live NSE stocks via Yahoo: SBIN -> SBIN.NS
        provider, symbol = "yahoo", replay.nse_symbol(symbol)
    df = get_history(provider, symbol, interval, HISTORY_CANDLES)
    last_open = int(df["time"].iloc[-1])
    now = time.time()
    return df, now < last_open + sec, now - (last_open + sec) > 3 * sec


@app.get("/api/scan")
def scan():
    provider = request.args.get("provider", "binance")
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "1m")
    try:
        show = max(50, min(int(request.args.get("limit", 200)), 500))
        horizon = max(1, min(int(request.args.get("horizon", 5)), 30))
    except ValueError:
        return jsonify(error="limit and horizon must be integers"), 400
    try:
        df, forming, stale = load(provider, symbol, interval)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502

    sec = INTERVAL_SECONDS[interval]
    now = time.time()
    closed = df.iloc[:-1] if forming else df       # only closed candles count as pattern evidence

    patterns = detect(closed)
    shown = df.tail(show)
    first_time = int(shown["time"].iloc[0])

    return jsonify(
        provider=provider,
        symbol=symbol,
        interval=interval,
        interval_seconds=sec,
        server_time=int(now),
        last_price=float(df["close"].iloc[-1]),
        last_candle_forming=forming,
        stale=stale,
        history_candles=len(df),
        candles=shown[["time", "open", "high", "low", "close", "volume"]].to_dict("records"),
        patterns=[p for p in patterns if p["time"] >= first_time],
        prediction=predict(closed, patterns, horizon),
    )


def chart_learner(provider, symbol, interval, horizon):
    """The self-learning model of this chart. Live charts are saved to disk, Test Lab charts are not."""
    persist = provider not in replay.PROVIDERS
    feed, sym = ("yahoo", replay.nse_symbol(symbol)) if provider == "nse" else (provider, symbol)
    return learner.get(feed, sym, interval, horizon, persist=persist), persist


@app.get("/api/signal")
def signal():
    """CALL / PUT / WAIT with entry at the current price, stop and target, plus the track record of the logic in
    charge: the fixed rule, or the self-learning model once it has proven itself (logic=auto|rule|model)."""
    provider = request.args.get("provider", "binance")
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "1m")
    mode = request.args.get("logic", "auto")
    if mode not in ("auto", "rule", "model"):
        return jsonify(error="logic must be auto, rule or model"), 400
    try:
        horizon = max(1, min(int(request.args.get("horizon", 5)), 30))
    except ValueError:
        return jsonify(error="horizon must be an integer"), 400
    try:
        df, forming, stale = load(provider, symbol, interval)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502

    sec = INTERVAL_SECONDS[interval]
    last_open = int(df["time"].iloc[-1])
    now = time.time()
    closed = df.iloc[:-1] if forming else df
    live_bar = {k: float(df[k].iloc[-1]) for k in ("high", "low", "close")} if forming else None

    lr, persist = chart_learner(provider, symbol, interval, horizon)
    lr.submit(closed)                                   # learns from new candles in the background
    lr.wait(int(closed["time"].iloc[-1]))
    view = lr.view(closed)
    s = view["summary"]
    active = mode == "model" or (mode == "auto" and s["gate"]["promoted"])
    note = None
    if s["phase"] == "learning":
        note = (f"The model is still learning: {s['lessons']} of {s['lessons_needed']} finished trades needed "
                "before its first training." if s["lessons"] else "The model is studying this chart for the first time.")
    model = {**view, "note": note} if active else None
    rec = recommend(closed, detect(closed), float(df["close"].iloc[-1]), horizon, live_bar, model=model)
    rec.update(provider=provider, symbol=symbol, interval=interval, interval_seconds=sec, stale=stale,
               forming=forming, signal_candle_time=int(closed["time"].iloc[-1]),
               candle_closes_at=last_open + sec if forming else None, server_time=int(now),
               model=learner.describe(view, mode, active, persist, lr.key))
    return jsonify(rec)


@app.post("/api/model/<action>")
def model_action(action):
    """Retrain the chart's self-learning model now, or reset it (forget everything it learned)."""
    b = request.get_json(force=True, silent=True) or {}
    try:
        horizon = max(1, min(int(b.get("horizon", 5)), 30))
        provider, symbol, interval = b.get("provider", "binance"), b.get("symbol", "BTCUSDT"), b.get("interval", "1m")
        if interval not in INTERVAL_SECONDS or not str(symbol).strip():
            raise ValueError("bad chart")
    except (TypeError, ValueError) as e:
        return jsonify(error=str(e)), 400
    lr, _ = chart_learner(provider, symbol, interval, horizon)
    if action == "retrain":
        lr.submit(None, retrain=True)
    elif action == "reset":
        learner.reset(*lr.key)
    else:
        return jsonify(error="action must be retrain or reset"), 404
    return jsonify(ok=True)


@app.get("/api/markets")
def markets_api():
    return jsonify(markets.status())


@app.get("/api/movers")
def movers_api():
    """Most active stocks right now (or in the last session) ranked by average 1-minute candle size."""
    try:
        return jsonify(markets.movers(request.args.get("market", "us")))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.get("/backtest")
def backtest_page():
    return send_from_directory("static", "backtest.html")


_bt_cache: dict[tuple, tuple[float, object]] = {}


@app.get("/api/backtest")
def backtest_api():
    """All candles of the chosen history + every occurrence of the chosen patterns and what happened next."""
    provider = request.args.get("provider", "nse")
    symbol = request.args.get("symbol", "RELIANCE").strip()
    interval = request.args.get("interval", "1d")
    names = [x for x in request.args.get("patterns", "Hammer,Inverted Hammer").split(",") if x in TEXTBOOK]
    try:
        horizon = max(1, min(int(request.args.get("horizon", 5)), 50))
        total = max(200, min(int(request.args.get("candles", 5000)), 20000))
    except ValueError:
        return jsonify(error="horizon and candles must be integers"), 400
    if not names:
        return jsonify(error="pick at least one pattern"), 400
    feed, sym = ("yahoo", replay.nse_symbol(symbol)) if provider == "nse" else (provider, symbol)
    key = (feed, sym.upper(), interval, total)
    try:
        hit = _bt_cache.get(key)
        if hit and time.time() - hit[0] < 600:
            df = hit[1]
        else:
            df = get_candles(feed, sym, interval, total)
            _bt_cache[key] = (time.time(), df)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502
    res = study(df, names, horizon)
    res.update(symbol=sym, interval=interval, interval_seconds=INTERVAL_SECONDS[interval],
               candles=df[["time", "open", "high", "low", "close", "volume"]].to_dict("records"))
    return jsonify(res)


@app.get("/api/replay/state")
def replay_state():
    try:
        s = replay.session(request.args.get("provider", "seeder"), request.args.get("symbol", "SEEDED"),
                           request.args.get("interval", "1m"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502
    return jsonify(s.state())


@app.post("/api/replay/control")
def replay_control():
    b = request.get_json(force=True, silent=True) or {}
    try:
        s = replay.control(b.get("provider", "seeder"), b.get("symbol", "SEEDED"), b.get("interval", "1m"),
                           b.get("action", ""), b.get("value"))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502
    return jsonify(s.state())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
