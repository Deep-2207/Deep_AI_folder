"""Historical study of single patterns (Hammer, Inverted Hammer, ...): every occurrence, why it qualified,
and what price did in the next `horizon` candles."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .patterns import TREND_LOOKBACK, detect

TEXTBOOK = {"Hammer": 1, "Inverted Hammer": 1, "Hanging Man": -1, "Shooting Star": -1}
DIRECTION = {"bullish": 1, "bearish": -1}


def study(df: pd.DataFrame, names: list[str], horizon: int = 5) -> dict:
    n = len(df)
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    t = df["time"].to_numpy()
    step = float(np.median(np.diff(t))) if n > 1 else 60.0
    atr = np.maximum((df["high"] - df["low"]).rolling(14, min_periods=3).mean().bfill().to_numpy(), 1e-12)
    intraday = step < 86400                 # daily candles always skip weekends/holidays: that's normal
    gap_free = lambda i: i + horizon <= n - 1 and (not intraday or t[i + horizon] - t[i] <= horizon * step * 1.5)

    fwd = [c[i + horizon] - c[i] for i in range(n) if gap_free(i)]
    base_up = float(np.mean(np.array(fwd) > 0)) if fwd else None

    occ = []
    for p in detect(df, chart_patterns=False):
        if p["name"] not in names:
            continue
        i, d = p["index"], TEXTBOOK.get(p["name"], DIRECTION.get(p["direction"], 0))
        rng = h[i] - l[i]
        body = abs(c[i] - o[i])
        row = {
            "index": i, "time": int(t[i]), "name": p["name"], "direction": p["direction"],
            "confidence": p["confidence"], "open": o[i], "high": h[i], "low": l[i], "close": c[i],
            # why it qualified (same rules as patterns.detect)
            "body_pct": body / rng * 100 if rng else 0,
            "lower_wick_x_body": (min(o[i], c[i]) - l[i]) / body if body else None,
            "upper_wick_x_body": (h[i] - max(o[i], c[i])) / body if body else None,
            "upper_wick_pct": (h[i] - max(o[i], c[i])) / rng * 100 if rng else 0,
            "lower_wick_pct": (min(o[i], c[i]) - l[i]) / rng * 100 if rng else 0,
            "trend_move": c[i - 1] - c[i - 1 - TREND_LOOKBACK],
            "trend_atr": (c[i - 1] - c[i - 1 - TREND_LOOKBACK]) / atr[i - 1],
            "status": "pending",
        }
        if gap_free(i):
            seg_h, seg_l = h[i + 1:i + horizon + 1], l[i + 1:i + horizon + 1]
            move = c[i + horizon] - c[i]
            row.update(
                status="done",
                move=float(move),
                move_pct=float(move / c[i] * 100),
                best_up=float(seg_h.max() - c[i]),        # largest rise seen during the look-ahead
                worst_down=float(seg_l.min() - c[i]),     # largest drop seen during the look-ahead
                worked=bool(move * d > 0),
            )
        elif i + horizon <= n - 1:
            row["status"] = "gap"                         # look-ahead crosses a market close
        occ.append(row)

    summary = {}
    for name in names:
        rows = [r for r in occ if r["name"] == name]
        done = [r for r in rows if r["status"] == "done"]
        d = TEXTBOOK.get(name, DIRECTION.get(rows[0]["direction"], 0) if rows else 0)
        moves = np.array([r["move"] for r in done])
        summary[name] = {
            "found": len(rows),
            "measured": len(done),
            "worked_pct": round(float(np.mean([r["worked"] for r in done])), 3) if done else None,
            "rose_pct": round(float(np.mean(moves > 0)), 3) if done else None,
            "avg_move": float(moves.mean()) if done else None,
            "median_move": float(np.median(moves)) if done else None,
            "avg_best_up": float(np.mean([r["best_up"] for r in done])) if done else None,
            "avg_worst_down": float(np.mean([r["worst_down"] for r in done])) if done else None,
            "textbook": "UP" if d > 0 else "DOWN" if d < 0 else "NONE",
        }
    return {"horizon": horizon, "baseline_up_pct": base_up, "occurrences": occ, "summary": summary}


# ---------------------------------------------------------------- knowledge-base backtests (Knowledge page)
# Development data = the first DEV_SPLIT of the candles, out-of-sample = the rest, reported separately
# (book: "Keep development data separate from out-of-sample evaluation data"). No costs or slippage.
DEV_SPLIT = 0.7


def pattern_performance(df: pd.DataFrame, name: str, horizon: int = 5, split: float = DEV_SPLIT) -> dict:
    """How often price moved the pattern's way `horizon` candles later, vs how often ANY candle did, in the
    development part and in the out-of-sample part of the history."""
    res = study(df, [name], horizon)
    n, cut = len(df), int(len(df) * split)
    c = df["close"].to_numpy(dtype=float)
    occ = [r for r in res["occurrences"] if r["status"] == "done"]
    d = DIRECTION.get(occ[0]["direction"], 0) if occ else 0

    def part(lo, hi):
        rows = [r for r in occ if lo <= r["index"] < hi]
        moves = np.array([c[j + horizon] - c[j] for j in range(lo, min(hi, n - horizon))])
        base = float(np.mean(moves * d > 0)) if d and len(moves) else (float(np.mean(moves > 0)) if len(moves) else None)
        out = {"candles": hi - lo, "found": len(rows), "baseline_pct": round(base * 100, 1) if base is not None else None}
        if rows:
            hit = float(np.mean([(r["move"] * d > 0) if d else (r["move"] > 0) for r in rows]))
            out.update(hit_pct=round(hit * 100, 1), edge_pct=round((hit - base) * 100, 1) if base is not None else None,
                       avg_move_pct=round(float(np.mean([r["move_pct"] for r in rows])), 3))
        return out

    return {"pattern": name, "direction": {1: "UP", -1: "DOWN"}.get(d, "NONE"), "horizon": horizon,
            "development": part(0, cut), "out_of_sample": part(cut, n)}


def rule_performance(df: pd.DataFrame, pattern_names: set[str], horizon: int = 5, split: float = DEV_SPLIT) -> dict:
    """The trend + pattern rule (signal.py) replayed on this history with only `pattern_names`, trades split by
    entry candle into development and out-of-sample."""
    from . import signal as S
    pats = [p for p in detect(df) if p["name"] in pattern_names]
    k = S.components(df, pats, horizon)
    trades, _ = S.run_trades(df, S.decide(k["pattern"], k["trend"]), k["atr"], horizon * 4)
    cut = int(len(df) * split)
    part = lambda ts: {kk: v for kk, v in S.summarize(ts, 0).items() if kk not in ("recent", "candles")} | {
        "avg_r": round(float(np.mean([x["r"] for x in ts])), 3) if ts else None}
    return {"patterns": sorted(pattern_names), "horizon": horizon,
            "development": part([x for x in trades if x["entry_index"] < cut]),
            "out_of_sample": part([x for x in trades if x["entry_index"] >= cut])}
