"""Rule-based candlestick + simple chart pattern detection on an OHLC DataFrame.

Each detected pattern is a dict:
  index       candle index where the pattern completes (last candle of the pattern)
  time        that candle's unix time
  name        e.g. "Bullish Engulfing"
  direction   "bullish" | "bearish" | "neutral"
  confidence  0..1 heuristic score (trend context + candle size), NOT a win probability
  span        number of candles the pattern uses
  note        extra context (may be empty)

Trend context ("downtrend before a hammer") is measured as the close change over the
5 candles before the pattern, compared with the average candle range (ATR-like).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TREND_LOOKBACK = 5
PIVOT_K = 3


def _score(base: float, aligned: bool, size_ratio: float) -> float:
    return round(min(0.95, base + (0.15 if aligned else 0.0) + 0.1 * min(size_ratio, 2.0) / 2.0), 2)


def detect(df: pd.DataFrame, chart_patterns: bool = True) -> list[dict]:
    n = len(df)
    if n < 20:
        return []
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    times = df["time"].to_numpy()
    body = np.abs(c - o)
    rng = h - l
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    avg_body = np.maximum(pd.Series(body).rolling(14, min_periods=3).mean().bfill().to_numpy(), 1e-12)
    atr = np.maximum(pd.Series(rng).rolling(14, min_periods=3).mean().bfill().to_numpy(), 1e-12)

    def green(i): return c[i] > o[i]
    def red(i): return c[i] < o[i]

    def trend_before(start: int) -> int:
        """+1 up, -1 down, 0 flat, measured on candles before `start`."""
        if start < TREND_LOOKBACK + 1:
            return 0
        chg = c[start - 1] - c[start - 1 - TREND_LOOKBACK]
        thr = atr[start - 1]
        return 1 if chg > thr else -1 if chg < -thr else 0

    out: list[dict] = []

    def add(i, name, direction, base, aligned, span, size_ratio=1.0, note=""):
        out.append(
            {
                "index": int(i),
                "time": int(times[i]),
                "name": name,
                "direction": direction,
                "confidence": _score(base, aligned, size_ratio),
                "span": span,
                "note": note,
            }
        )

    for i in range(TREND_LOOKBACK + 1, n):
        # ---------- single candle ----------
        r, b = rng[i], body[i]
        if r > 0:
            t = trend_before(i)
            size = r / atr[i]
            if b <= 0.1 * r:
                if lower[i] >= 0.6 * r and upper[i] <= 0.1 * r:
                    add(i, "Dragonfly Doji", "bullish", 0.5, t == -1, 1, size)
                elif upper[i] >= 0.6 * r and lower[i] <= 0.1 * r:
                    add(i, "Gravestone Doji", "bearish", 0.5, t == 1, 1, size)
                else:
                    add(i, "Doji", "neutral", 0.4, False, 1, size, "indecision")
            elif b >= 0.95 * r and b >= 2.0 * avg_body[i]:
                add(i, "Bullish Marubozu" if green(i) else "Bearish Marubozu",
                    "bullish" if green(i) else "bearish", 0.55, True, 1, b / avg_body[i])
            elif b <= 0.4 * r:
                if lower[i] >= 2 * b and upper[i] <= 0.15 * r:
                    if t == -1:
                        add(i, "Hammer", "bullish", 0.55, True, 1, size)
                    elif t == 1:
                        add(i, "Hanging Man", "bearish", 0.5, True, 1, size)
                elif upper[i] >= 2 * b and lower[i] <= 0.15 * r:
                    if t == -1:
                        add(i, "Inverted Hammer", "bullish", 0.5, True, 1, size)
                    elif t == 1:
                        add(i, "Shooting Star", "bearish", 0.55, True, 1, size)

        # ---------- two candles ----------
        p = i - 1
        if p >= TREND_LOOKBACK + 1:
            t = trend_before(p)
            size = max(body[i], body[p]) / avg_body[i]
            big_p = body[p] >= avg_body[p]
            if t == -1 and red(p) and green(i):
                if o[i] <= c[p] and c[i] >= o[p] and body[i] > body[p]:
                    add(i, "Bullish Engulfing", "bullish", 0.6, True, 2, size)
                elif big_p and max(o[i], c[i]) <= o[p] and min(o[i], c[i]) >= c[p] and body[i] < 0.6 * body[p]:
                    add(i, "Bullish Harami", "bullish", 0.45, True, 2, size)
                elif big_p and o[i] < c[p] and (o[p] + c[p]) / 2 < c[i] < o[p]:
                    add(i, "Piercing Line", "bullish", 0.55, True, 2, size)
                if abs(l[i] - l[p]) <= 0.1 * atr[i]:
                    add(i, "Tweezer Bottom", "bullish", 0.5, True, 2, size)
            elif t == 1 and green(p) and red(i):
                if o[i] >= c[p] and c[i] <= o[p] and body[i] > body[p]:
                    add(i, "Bearish Engulfing", "bearish", 0.6, True, 2, size)
                elif big_p and max(o[i], c[i]) <= c[p] and min(o[i], c[i]) >= o[p] and body[i] < 0.6 * body[p]:
                    add(i, "Bearish Harami", "bearish", 0.45, True, 2, size)
                elif big_p and o[i] > c[p] and o[p] < c[i] < (o[p] + c[p]) / 2:
                    add(i, "Dark Cloud Cover", "bearish", 0.55, True, 2, size)
                if abs(h[i] - h[p]) <= 0.1 * atr[i]:
                    add(i, "Tweezer Top", "bearish", 0.5, True, 2, size)

        # ---------- three candles ----------
        j, k = i - 1, i - 2
        if k >= TREND_LOOKBACK + 1:
            t = trend_before(k)
            size = body[k] / avg_body[k]
            small_mid = body[j] <= 0.3 * body[k]
            if t == -1 and red(k) and body[k] >= avg_body[k] and small_mid \
                    and max(o[j], c[j]) <= c[k] and green(i) and c[i] > (o[k] + c[k]) / 2:
                add(i, "Morning Star", "bullish", 0.65, True, 3, size)
            if t == 1 and green(k) and body[k] >= avg_body[k] and small_mid \
                    and min(o[j], c[j]) >= c[k] and red(i) and c[i] < (o[k] + c[k]) / 2:
                add(i, "Evening Star", "bearish", 0.65, True, 3, size)
            if t <= 0 and all(green(x) for x in (k, j, i)) \
                    and all(body[x] >= 0.6 * avg_body[x] for x in (k, j, i)) \
                    and o[k] <= o[j] <= c[k] and o[j] <= o[i] <= c[j] and c[k] < c[j] < c[i] \
                    and all(upper[x] <= 0.3 * body[x] for x in (k, j, i)):
                add(i, "Three White Soldiers", "bullish", 0.65, t == -1, 3, size)
            if t >= 0 and all(red(x) for x in (k, j, i)) \
                    and all(body[x] >= 0.6 * avg_body[x] for x in (k, j, i)) \
                    and c[k] <= o[j] <= o[k] and c[j] <= o[i] <= o[j] and c[k] > c[j] > c[i] \
                    and all(lower[x] <= 0.3 * body[x] for x in (k, j, i)):
                add(i, "Three Black Crows", "bearish", 0.65, t == 1, 3, size)

    if chart_patterns:
        out.extend(_double_tops_bottoms(h, l, c, times, atr, n))

    out.sort(key=lambda d: (d["index"], d["name"]))
    return out


def _double_tops_bottoms(h, l, c, times, atr, n) -> list[dict]:
    """Two similar swing highs (or lows) with a clear trough (peak) between them."""
    k = PIVOT_K
    hi_piv, lo_piv = [], []
    for p in range(k, n - k):
        if h[p] > h[p - k:p].max() and h[p] >= h[p + 1:p + k + 1].max():
            hi_piv.append(p)
        if l[p] < l[p - k:p].min() and l[p] <= l[p + 1:p + k + 1].min():
            lo_piv.append(p)

    res = []
    for a, b in zip(hi_piv, hi_piv[1:]):
        if not 5 <= b - a <= 60:
            continue
        neckline = l[a:b + 1].min()
        if abs(h[a] - h[b]) <= 0.6 * atr[b] and min(h[a], h[b]) - neckline >= 1.5 * atr[b]:
            broken = bool((c[b + 1:] < neckline).any())
            res.append(_chart("Double Top", "bearish", b, a, times, broken))
    for a, b in zip(lo_piv, lo_piv[1:]):
        if not 5 <= b - a <= 60:
            continue
        neckline = h[a:b + 1].max()
        if abs(l[a] - l[b]) <= 0.6 * atr[b] and neckline - max(l[a], l[b]) >= 1.5 * atr[b]:
            broken = bool((c[b + 1:] > neckline).any())
            res.append(_chart("Double Bottom", "bullish", b, a, times, broken))
    return res


def _chart(name, direction, b, a, times, broken):
    return {
        "index": int(b),
        "time": int(times[b]),
        "name": name,
        "direction": direction,
        "confidence": 0.8 if broken else 0.6,
        "span": int(b - a + 1),
        "note": "neckline broken" if broken else "waiting for neckline break",
    }


def bias(patterns: list[dict], last_index: int, recent: int = 5) -> dict:
    """Net bullish/bearish lean from patterns completing in the last `recent` candles."""
    score = 0.0
    for p in patterns:
        if p["index"] > last_index - recent:
            score += p["confidence"] * {"bullish": 1, "bearish": -1}.get(p["direction"], 0)
    label = "bullish" if score > 0.3 else "bearish" if score < -0.3 else "neutral"
    return {"score": round(score, 2), "label": label}


def predict(df: pd.DataFrame, patterns: list[dict], horizon: int = 5, min_cases: int = 8) -> dict | None:
    """Predict the move (in price points) after the latest pattern from how the same pattern
    played out earlier in `df`.

    For every earlier occurrence we measure close[idx + horizon] - close[idx]. The call is the
    median of those moves; the range is their 25th..75th percentile. With fewer than `min_cases`
    earlier cases we fall back to the textbook direction of the pattern and a 2x ATR move.
    `df` should contain closed candles only.
    """
    if not patterns:
        return None
    n = len(df)
    c = df["close"].to_numpy(dtype=float)
    t = df["time"].to_numpy()
    step = float(np.median(np.diff(t))) if n > 1 else 60.0
    atr = max(float((df["high"] - df["low"]).rolling(14, min_periods=3).mean().iloc[-1]), 1e-12)

    top = max(patterns, key=lambda p: (p["index"], p["confidence"]))
    rule = {"bullish": 1, "bearish": -1}.get(top["direction"], 0)

    cases = []  # (time, move) for earlier occurrences with a complete, gap-free look-ahead
    for p in patterns:
        i = p["index"]
        gap_free = i + horizon <= n - 1 and t[i + horizon] - t[i] <= horizon * step * 1.5
        if p["name"] == top["name"] and i != top["index"] and gap_free:
            cases.append((int(t[i]), float(c[i + horizon] - c[i])))
    moves = np.array([m for _, m in cases])
    samples = len(moves)

    entry = float(c[top["index"]])
    # how often ANY candle in this window was followed by a rise, so drift isn't mistaken for edge
    fwd = c[horizon:] - c[:-horizon]
    base_up = float((fwd > 0).mean()) if len(fwd) else 0.5
    base_up = min(max(base_up, 0.05), 0.95)
    up_pct = down_pct = median = lo = hi = None
    edge = "none"
    if samples:
        up_pct = round(float((moves > 0).mean()), 2)
        down_pct = round(float((moves < 0).mean()), 2)
        nz = int((moves != 0).sum())
        if nz:
            z = abs((moves > 0).sum() / nz - base_up) / np.sqrt(base_up * (1 - base_up) / nz)
            edge = "strong" if z >= 2 else "moderate" if z >= 1.3 else "weak" if z >= 0.7 else "none"
    if samples >= min_cases:
        median = float(np.median(moves))
        lo, hi = (float(x) for x in np.percentile(moves, [25, 75]))
        sign = 1 if median > 0 else -1 if median < 0 else 0
        expected, basis = median, "history"
    else:
        sign, expected, basis = rule, rule * 2 * atr, "rule"
        lo, hi = (min(0.0, expected), max(0.0, expected))
        edge = "none"

    age = n - 1 - top["index"]
    return {
        "pattern": top["name"],
        "pattern_time": top["time"],
        "confidence": top["confidence"],
        "note": top["note"],
        "rule_direction": {1: "UP", -1: "DOWN", 0: "SIDEWAYS"}[rule],
        "direction": {1: "UP", -1: "DOWN", 0: "SIDEWAYS"}[sign],
        "basis": basis,
        "edge": edge,
        "horizon": horizon,
        "age": age,
        "active": age < horizon,
        "entry_price": entry,
        "expected_move": expected,
        "expected_pct": expected / entry * 100 if entry else 0.0,
        "target_price": entry + expected,
        "range_low_price": entry + lo,
        "range_high_price": entry + hi,
        "moved_so_far": float(c[-1] - entry),
        "samples": samples,
        "baseline_up_pct": round(base_up, 2),
        "up_pct": up_pct,
        "down_pct": down_pct,
        "past_cases": [{"time": ts, "move": m} for ts, m in cases[-6:]][::-1],
    }
