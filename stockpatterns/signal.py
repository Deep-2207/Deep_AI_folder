"""CALL / PUT / WAIT trade signal: one clear rule, a trade state (ENTER / HOLD / EXIT / WAIT), and the rule's
track record on the same chart.

Two votes, each using only data up to that candle (no look-ahead, tested):
  TREND     EMA20 vs EMA50 measured in ATRs (squashed with tanh): UP if >= +TREND_MIN, DOWN if <= -TREND_MIN
  PATTERNS  candlestick patterns of the last `horizon` candles, each weighted by how much more (or less) often price
            rose after that pattern *earlier on this chart* than after any candle (z-score):
            BULLISH if >= +PATTERN_MIN, BEARISH if <= -PATTERN_MIN
  CALL = trend UP and patterns BULLISH.  PUT = trend DOWN and patterns BEARISH.  Anything else = WAIT.

Requiring both votes to agree gave fewer but better trades than a blended score on live stocks, and it shows no
profit on synthetic data where patterns carry no information (the blended score did, which was misleading).

Trades are taken one at a time, with a one-candle cool-down after each exit (re-entering on the exit candle did
worse on live stocks): enter at the close of the signal candle, stop = SL_ATR x ATR away,
target = RR x the stop distance, exit at the stop (checked first inside a candle), the target, or at the close
after `max_hold` candles; intraday trades are also squared off at the last candle before the market closes.
Double Top/Bottom are left out: they are confirmed several candles late (look-ahead).

recommend() can also run the same trade engine on the self-learning model's paper decisions (learner.py) instead of
the rule's, once the model has proven itself (or when the user picks "Model only").
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

TREND_MIN = 0.2
PATTERN_MIN = 0.15
SL_ATR = 1.5
RR = 2.0
MIN_CASES = 8
WARMUP = 100
LAGGING = {"Double Top", "Double Bottom"}
SIDE = {1: "CALL", -1: "PUT"}


def _indicators(df: pd.DataFrame):
    close = df["close"]
    atr = (df["high"] - df["low"]).rolling(14, min_periods=3).mean().bfill().to_numpy()
    ema20 = close.ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = close.ewm(span=50, adjust=False).mean().to_numpy()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50).to_numpy()
    return np.maximum(atr, 1e-12), ema20, ema50, rsi


def components(df: pd.DataFrame, patterns: list[dict], horizon: int = 5) -> dict:
    """Per-candle pattern value, trend value, EMA gap (ATRs), RSI and ATR, plus the reasoning for the last candle."""
    n = len(df)
    c = df["close"].to_numpy(dtype=float)
    t = df["time"].to_numpy()
    step = float(np.median(np.diff(t))) if n > 1 else 60.0
    atr, ema20, ema50, rsi = _indicators(df)
    gap_free = lambda j: t[j + horizon] - t[j] <= horizon * step * 1.5

    by_idx = defaultdict(list)
    for p in patterns:
        if p["name"] not in LAGGING:
            by_idx[p["index"]].append(p)

    stats = defaultdict(lambda: [0, 0])     # name -> [rises, cases] known so far
    base = [0, 0]                           # all candles -> [rises, cases] known so far
    pat = np.zeros(n)
    gap = (ema20 - ema50) / atr
    trend = np.tanh(gap)
    last = None

    for i in range(n):
        j = i - horizon                     # the move after candle j becomes known at candle i
        if j >= 0 and gap_free(j):
            up = c[i] > c[j]
            base[0] += up
            base[1] += 1
            for p in by_idx.get(j, ()):
                stats[p["name"]][0] += up
                stats[p["name"]][1] += 1

        parts = []
        if base[1] >= 50:
            b = min(max(base[0] / base[1], 0.05), 0.95)
            for k in range(max(0, i - horizon + 1), i + 1):
                for p in by_idx.get(k, ()):
                    rises, cases = stats[p["name"]]
                    if cases < MIN_CASES:
                        continue
                    rate = rises / cases
                    z = (rate - b) / math.sqrt(b * (1 - b) / cases)
                    w = 1 - (i - k) / horizon      # fresher patterns count more
                    parts.append((max(-1.0, min(1.0, z / 2.5)), w, p, rate, cases, z))
        wsum = sum(w for _, w, *_ in parts)
        pat[i] = sum(s * w for s, w, *_ in parts) / wsum if wsum else 0.0

        if i == n - 1:
            last = {
                "pattern_score": round(float(pat[i]), 2),
                "trend_score": round(float(trend[i]), 2),
                "ema_gap_atr": round(float(gap[i]), 2),
                "rsi": round(float(rsi[i]), 1),
                "market_up_rate": round(base[0] / base[1], 2) if base[1] else None,
                "patterns": [
                    {"name": p["name"], "candles_ago": i - p["index"], "direction": p["direction"],
                     "up_rate": round(rate, 2), "cases": cases, "z": round(z, 2)}
                    for _, _, p, rate, cases, z in sorted(parts, key=lambda x: -x[1])
                ],
            }
    return {"pattern": pat, "trend": trend, "gap": gap, "rsi": rsi, "atr": atr, "last": last}


def scores(df: pd.DataFrame, patterns: list[dict], horizon: int = 5):
    """Blended score (0.6 x patterns + 0.4 x trend) per candle, ATR, last-candle detail. Informational."""
    k = components(df, patterns, horizon)
    return 0.6 * k["pattern"] + 0.4 * k["trend"], k["atr"], k["last"]


def decide(pattern, trend) -> np.ndarray:
    """+1 CALL when trend is UP and patterns are BULLISH, -1 PUT when both point down, else 0 WAIT."""
    p = np.asarray(pattern, dtype=float)
    t = np.asarray(trend, dtype=float)
    return np.where((t >= TREND_MIN) & (p >= PATTERN_MIN), 1,
                    np.where((t <= -TREND_MIN) & (p <= -PATTERN_MIN), -1, 0))


def trend_vote(t: float) -> str:
    return "UP" if t >= TREND_MIN else "DOWN" if t <= -TREND_MIN else "FLAT"


def pattern_vote(p: float) -> str:
    return "BULLISH" if p >= PATTERN_MIN else "BEARISH" if p <= -PATTERN_MIN else "NONE"


def run_trades(df: pd.DataFrame, decision, atr, max_hold: int):
    """Replay the rule one trade at a time. Returns (closed trades, the trade still open at the end or None)."""
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    t = df["time"].to_numpy()
    n = len(df)
    # intraday: a candle followed by a break (night, weekend) is the last of its session -> square off there
    step = float(np.median(np.diff(t))) if n > 1 else 0.0
    session_end = np.zeros(n, dtype=bool)
    if 0 < step < 86400:
        session_end[:-1] = np.diff(t) > 1.5 * step
    trades = []
    i = WARMUP
    while i < n:
        d = int(decision[i])
        if d == 0 or session_end[i]:              # no new trade on the last candle before the market closes
            i += 1
            continue
        entry, risk = float(c[i]), float(SL_ATR * atr[i])
        stop, target = entry - d * risk, entry + d * RR * risk
        trade = {"side": SIDE[d], "dir": d, "entry_index": i, "entry_time": int(t[i]), "entry": entry,
                 "stop": stop, "target": target, "risk": risk}
        exit_ = None
        for j in range(i + 1, min(n - 1, i + max_hold) + 1):
            if (l[j] <= stop) if d > 0 else (h[j] >= stop):
                exit_ = ("stop", stop, j)
                break
            if (h[j] >= target) if d > 0 else (l[j] <= target):
                exit_ = ("target", target, j)
                break
            if session_end[j]:
                exit_ = ("close", float(c[j]), j)    # market closes after this candle
                break
        if exit_ is None:
            if i + max_hold > n - 1:              # still running at the end of the data
                trade["candles_held"] = n - 1 - i
                return trades, trade
            j = i + max_hold
            exit_ = ("timeout", float(c[j]), j)
        kind, price, j = exit_
        pts = (price - entry) * d
        trade.update(exit=kind, exit_index=j, exit_time=int(t[j]), exit_price=float(price),
                     points=float(pts), r=float(pts / risk))
        trades.append(trade)
        i = j + 1                                 # one-candle cool-down after an exit
    return trades, None


def summarize(trades: list[dict], candles: int) -> dict:
    pts = np.array([x["points"] for x in trades])
    rs = np.array([x["r"] for x in trades])
    wins, losses = pts[pts > 0], pts[pts <= 0]
    return {
        "trades": len(trades),
        "win_rate": round(float((pts > 0).mean()), 2) if len(pts) else None,
        "total_points": float(pts.sum()) if len(pts) else 0.0,
        "avg_points": float(pts.mean()) if len(pts) else 0.0,
        "total_r": round(float(rs.sum()), 1) if len(rs) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
        "targets": sum(x["exit"] == "target" for x in trades),
        "stops": sum(x["exit"] == "stop" for x in trades),
        "timeouts": sum(x["exit"] == "timeout" for x in trades),
        "market_closes": sum(x["exit"] == "close" for x in trades),
        "candles": max(0, candles - WARMUP),
        "recent": [{k: x[k] for k in ("side", "entry_time", "exit", "points")} for x in trades[-5:][::-1]],
    }


def backtest(df: pd.DataFrame, decision, atr, max_hold: int) -> dict:
    trades, _ = run_trades(df, decision, atr, max_hold)
    return summarize(trades, len(df))


def _wait_reason(tv: str, pv: str, signal_now: int) -> str:
    if signal_now:
        side = SIDE[signal_now]
        return (f"Cool-down: both votes say {side}, but the last trade ended on this candle. "
                f"If they still say {side} when the next candle closes, that is your BUY {side} NOW.")
    if tv == "UP" and pv == "NONE":
        return "Trend is UP. Waiting for a bullish pattern that has worked on this chart, then BUY CALL."
    if tv == "DOWN" and pv == "NONE":
        return "Trend is DOWN. Waiting for a bearish pattern that has worked on this chart, then BUY PUT."
    if tv == "UP" and pv == "BEARISH":
        return "Conflict: trend is UP but recent patterns are bearish. No trade until they agree."
    if tv == "DOWN" and pv == "BULLISH":
        return "Conflict: trend is DOWN but recent patterns are bullish. No trade until they agree."
    if tv == "FLAT" and pv == "BULLISH":
        return "Patterns are bullish but there is no uptrend yet. CALL needs EMA20 to rise above EMA50."
    if tv == "FLAT" and pv == "BEARISH":
        return "Patterns are bearish but there is no downtrend yet. PUT needs EMA20 to fall below EMA50."
    return "No trend and no useful pattern. Nothing to do."


def _model_wait_reason(model: dict, signal_now: int) -> str:
    if signal_now:
        side = SIDE[signal_now]
        return (f"Cool-down: the model says {side}, but the last trade ended on this candle. If it still says {side} "
                f"when the next candle closes, that is your BUY {side} NOW.")
    cr, pr = float(model["call_r"][-1]), float(model["put_r"][-1])
    if not math.isfinite(cr):
        return model.get("note") or "The model has not judged this candle yet (it is still learning)."
    return (f"The model expects {cr:+.2f}R from a CALL and {pr:+.2f}R from a PUT on this candle. It only trades when "
            f"it expects more than +{model['edge']:.2f}R, so: no trade.")


def recommend(closed: pd.DataFrame, patterns: list[dict], current_price: float, horizon: int = 5,
              live_bar: dict | None = None, model: dict | None = None) -> dict:
    """What to do now. `closed` = closed candles; `live_bar` = the still-forming candle (high/low/close) if any.
    `model` = the self-learning model's paper decisions for `closed` when it is the logic in charge
    ({"decision", "call_r", "put_r", "edge", "note"}, see learner.py); None = the fixed rule decides."""
    max_hold = horizon * 4
    k = components(closed, patterns, horizon)
    rule_dec = decide(k["pattern"], k["trend"])
    dec = np.asarray(model["decision"]) if model else rule_dec
    trades, open_t = run_trades(closed, dec, k["atr"], max_hold)
    n = len(closed)
    p, tr = float(k["pattern"][-1]), float(k["trend"][-1])
    tv, pv = trend_vote(tr), pattern_vote(p)
    signal_now = int(dec[-1])
    detail = k["last"]
    current_price = float(current_price)

    state, trade = "wait", None
    if open_t:
        d = open_t["dir"]
        held = n - 1 - open_t["entry_index"]
        hi = float(live_bar["high"]) if live_bar else current_price
        lo = float(live_bar["low"]) if live_bar else current_price
        hit = None
        if (lo <= open_t["stop"]) if d > 0 else (hi >= open_t["stop"]):
            hit = "stop"
        elif (hi >= open_t["target"]) if d > 0 else (lo <= open_t["target"]):
            hit = "target"
        pl = (current_price - open_t["entry"]) * d
        risk = open_t["risk"]
        state = "exit" if hit else "enter" if held == 0 else "hold"
        trade = {
            "side": open_t["side"], "entry_time": open_t["entry_time"], "entry": open_t["entry"],
            "stop": open_t["stop"], "target": open_t["target"], "stop_points": risk, "target_points": RR * risk,
            "candles_held": held, "candles_left": max_hold - held, "max_hold": max_hold,
            "pl_points": pl, "pl_r": pl / risk,
            # -1 = at the stop, 0 = at entry, +1 = at the target
            "progress": max(-1.0, min(1.0, pl / (RR * risk) if pl >= 0 else pl / risk)),
            "hit": hit,
        }

    explain = []
    gap = detail["ema_gap_atr"]
    explain.append(f"Trend {tv}: EMA20 is {abs(gap):.1f} ATR {'above' if gap >= 0 else 'below'} EMA50")
    if detail["patterns"]:
        for q in detail["patterns"][:3]:
            way = "bullish" if q["z"] > 0 else "bearish"
            explain.append(f"{q['name']} ({q['candles_ago']} candles ago): price rose after it {q['up_rate']:.0%} of "
                           f"{q['cases']} times on this chart vs {detail['market_up_rate']:.0%} for any candle, so {way}")
    else:
        explain.append("Patterns NONE: no recent pattern with at least 8 earlier cases on this chart")

    last_trade = None
    if trades:
        x = trades[-1]
        last_trade = {k2: x[k2] for k2 in ("side", "entry_time", "entry", "stop", "target", "exit", "exit_time",
                                            "exit_price", "points", "r")}

    blended = 0.6 * p + 0.4 * tr
    bt = summarize(trades, n)
    if model:                                     # the model's record only covers candles it had judged
        bt["candles"] = int(np.isfinite(np.asarray(model["call_r"], dtype=float)).sum())
    if trade:
        wait_reason = None
    elif model:
        wait_reason = _model_wait_reason(model, signal_now)
    else:
        wait_reason = _wait_reason(tv, pv, signal_now)
    return {
        "state": state,
        "action": trade["side"] if trade else "WAIT",
        "logic": "model" if model else "rule",
        "trade": trade,
        "last_trade": last_trade,
        "signal_now": SIDE.get(signal_now, "WAIT"),
        "rule_signal_now": SIDE.get(int(rule_dec[-1]), "WAIT"),
        "votes": {"trend": tv, "trend_value": round(tr, 2), "pattern": pv, "pattern_value": round(p, 2),
                  "trend_min": TREND_MIN, "pattern_min": PATTERN_MIN},
        "wait_reason": wait_reason,
        "explain": explain,
        "reasons": explain,
        "score": round(blended, 2),
        "lean": "CALL" if blended > 0 else "PUT" if blended < 0 else "NONE",
        "rsi": detail["rsi"],
        # trade levels (None while waiting)
        "entry": trade["entry"] if trade else None,
        "stop": trade["stop"] if trade else None,
        "target": trade["target"] if trade else None,
        "stop_points": trade["stop_points"] if trade else None,
        "target_points": trade["target_points"] if trade else None,
        "rr": RR,
        "max_hold": max_hold,
        "current_price": current_price,
        "detail": detail,
        "backtest": bt,
        "trades": [{k2: x[k2] for k2 in ("side", "entry_time", "exit", "exit_time", "points", "r")} for x in trades[-150:]],
    }
