"""Historical study of single patterns (Hammer, Inverted Hammer, ...): every occurrence, why it qualified,
and what price did in the next `horizon` candles."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .patterns import TREND_LOOKBACK, detect

TEXTBOOK = {"Hammer": 1, "Inverted Hammer": 1, "Hanging Man": -1, "Shooting Star": -1}


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
        i, d = p["index"], TEXTBOOK.get(p["name"], 0)
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
        d = TEXTBOOK.get(name, 0)
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
            "textbook": "UP" if d > 0 else "DOWN",
        }
    return {"horizon": horizon, "baseline_up_pct": base_up, "occurrences": occ, "summary": summary}
