"""Live dashboard: python app.py  ->  http://127.0.0.1:5000"""
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from stockpatterns.feeds import INTERVAL_SECONDS, FeedError, get_candles, get_history
from stockpatterns.patterns import detect, predict
from stockpatterns import knowledge, learner, markets, replay
from stockpatterns.backtest import TEXTBOOK, pattern_performance, rule_performance, study
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
    with open(app.static_folder + "/index.html", encoding="utf-8") as f:
        html = f.read()
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
    usable = knowledge.KB.usable_patterns()
    for p in patterns:                              # knowledge gate: only approved patterns drive the signal
        p["approved"] = p["name"] in usable
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
    gate = knowledge.KB.gate()                         # only APPROVED + implemented knowledge is used
    active = gate["model"] and (mode == "model" or (mode == "auto" and s["gate"]["promoted"]))
    blocked = None
    if not gate["rule"]:
        blocked = (f"Knowledge gate: the trading rule is {gate['rule_status'] or 'missing'}, not approved yet. "
                   "Review and approve it on the Knowledge page (/knowledge).")
    elif not gate["patterns"]:
        blocked = "Knowledge gate: no approved patterns yet. Approve patterns on the Knowledge page (/knowledge)."
    if mode == "model" and not gate["model"] and not blocked:
        blocked = (f"Knowledge gate: the self-learning model is {gate['model_status'] or 'missing'}, not approved, "
                   "so it may not give signals. Approve it on the Knowledge page, or use Auto / Rule only.")
    note = None
    if s["phase"] == "learning":
        note = (f"The model is still learning: {s['lessons']} of {s['lessons_needed']} finished trades needed "
                "before its first training." if s["lessons"] else "The model is studying this chart for the first time.")
    model = {**view, "note": note} if active else None
    usable = set(gate["patterns"])
    pats = [p for p in detect(closed) if p["name"] in usable]
    rec = recommend(closed, pats, float(df["close"].iloc[-1]), horizon, live_bar, model=model, blocked=blocked)
    rec.update(provider=provider, symbol=symbol, interval=interval, interval_seconds=sec, stale=stale,
               forming=forming, signal_candle_time=int(closed["time"].iloc[-1]),
               candle_closes_at=last_open + sec if forming else None, server_time=int(now),
               model=learner.describe(view, mode, active, persist, lr.key),
               knowledge={"patterns": gate["patterns"], "rule": gate["rule_status"], "model": gate["model_status"],
                          "rule_usable": gate["rule"], "model_usable": gate["model"]})
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


@app.get("/market")
def market_page():
    return send_from_directory("static", "market.html")


@app.get("/strategy/ema")
def ema_strategy_page():
    return send_from_directory("static", "ema_visualizer.html")


@app.get("/api/market/radar")
def market_radar():
    """Today's gainers, losers, and big stocks near 52-week low."""
    universe = request.args.get("universe", "nifty50")
    custom = request.args.get("symbols")
    custom_list = [s.strip() for s in custom.split(",") if s.strip()] if custom else None
    force = request.args.get("refresh", "0") in ("1", "true")
    try:
        return jsonify(markets.radar(universe, custom_symbols=custom_list, force=force))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 502


@app.get("/api/market/universes")
def market_universes():
    return jsonify([
        {"key": k, "name": v["name"], "market": v["market"], "count": len(v["symbols"])}
        for k, v in markets.UNIVERSES.items()
    ])


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


# ---------------------------------------------------------------- Knowledge Management (layers 1-4)
BACKTEST_MARKETS = (("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY"))
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024        # largest book upload


@app.get("/knowledge")
def knowledge_page():
    return send_from_directory("static", "knowledge.html")


def _knowledge_json(it: dict) -> dict:
    from document_reader.source_reference import fmt, verify
    kb = knowledge.KB
    return {**{k: v for k, v in it.items()},
            "sources": [{**s_, "ref": fmt(s_), "check": verify(s_, kb.text_dir, kb.books)} for s_ in it.get("sources") or []],
            "next": sorted(knowledge.TRANSITIONS.get(it["status"], set()) - {"BACKTESTED"}),
            "can_backtest": it["status"] in knowledge.USABLE and (
                (it["kind"] == "pattern" and it.get("code_name") not in ("Double Top", "Double Bottom"))
                or (it["kind"] == "strategy" and it["id"] == knowledge.RULE_STRATEGY))}


@app.get("/api/knowledge")
def knowledge_api():
    kb = knowledge.KB
    return jsonify(gate=kb.gate(), statuses=knowledge.STATUSES, items=[_knowledge_json(i) for i in kb.items()],
                   documents=kb.documents())


@app.post("/api/knowledge/<kind>/<id_>/status")
def knowledge_status(kind, id_):
    b = request.get_json(force=True, silent=True) or {}
    try:
        it = knowledge.KB.set_status(kind, id_, str(b.get("status", "")), str(b.get("note", "")))
    except knowledge.KnowledgeError as e:
        return jsonify(error=str(e)), 400
    return jsonify(item=_knowledge_json(it), gate=knowledge.KB.gate())


def _daily(sym: str):
    key = ("yahoo", sym, "1d", 5000)
    hit = _bt_cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    df = get_candles("yahoo", sym, "1d", 5000)
    _bt_cache[key] = (time.time(), df)
    return df


@app.post("/api/knowledge/<kind>/<id_>/backtest")
def knowledge_backtest(kind, id_):
    """Measure an IMPLEMENTED pattern (or the rule) on NIFTY 50 and BANK NIFTY daily candles, development vs
    out-of-sample, and store the result in its knowledge file (status BACKTESTED)."""
    kb = knowledge.KB
    try:
        it = kb.get(kind, id_)
        if not _knowledge_json(it)["can_backtest"]:
            raise knowledge.KnowledgeError(f"{it['name']} cannot be backtested here (status {it['status']})")
        horizon = 5
        runs, lines = [], []
        for sym, label in BACKTEST_MARKETS:
            df = _daily(sym)
            if kind == "pattern":
                r = pattern_performance(df, it["code_name"], horizon)
                o = r["out_of_sample"]
                lines.append(f"{label}: out-of-sample {o.get('hit_pct', '-')}% moved {r['direction']} vs "
                             f"{o.get('baseline_pct', '-')}% for any candle ({o['found']} cases)")
            else:
                r = rule_performance(df, kb.usable_patterns(), horizon)
                o = r["out_of_sample"]
                lines.append(f"{label}: out-of-sample {o['trades']} trades, avg {o['avg_r'] if o['avg_r'] is not None else '-'}R")
            runs.append({"symbol": sym, "market": label, "interval": "1d", "candles": len(df),
                         "from": time.strftime("%Y-%m-%d", time.gmtime(int(df["time"].iloc[0]))),
                         "to": time.strftime("%Y-%m-%d", time.gmtime(int(df["time"].iloc[-1]))), **r})
        res = {"date": time.strftime("%Y-%m-%d"), "horizon_candles": horizon, "split": "first 70% development, "
               "last 30% out-of-sample", "costs": "not included (no fees, no slippage)", "runs": runs,
               "summary": "; ".join(lines)}
        it = kb.record_backtest(kind, id_, res)
    except knowledge.KnowledgeError as e:
        return jsonify(error=str(e)), 400
    except FeedError as e:
        return jsonify(error=str(e)), 502
    return jsonify(item=_knowledge_json(it), gate=kb.gate())


@app.post("/api/documents/upload")
def document_upload():
    from werkzeug.utils import secure_filename
    from document_reader.pdf_reader import SUPPORTED
    f = request.files.get("file")
    name = secure_filename(f.filename or "") if f else ""
    if not name or not name.lower().endswith(SUPPORTED):
        return jsonify(error=f"choose a {', '.join(SUPPORTED)} file"), 400
    dst = knowledge.KB.books / name
    if dst.exists():
        return jsonify(error=f"{name} is already uploaded"), 409
    dst.parent.mkdir(parents=True, exist_ok=True)
    f.save(dst)
    try:
        rep = knowledge.KB.read_document(name)
    except Exception as e:                                  # keep the file; reading can be retried
        return jsonify(name=name, error=f"uploaded, but could not read it: {e}"), 200
    return jsonify(name=name, report=rep)


@app.post("/api/documents/read")
def document_read():
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(report=knowledge.KB.read_document(str(b.get("name", ""))))
    except knowledge.KnowledgeError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:                                  # unreadable PDF etc.
        return jsonify(error=str(e)), 400


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
