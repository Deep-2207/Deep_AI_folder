"""Self-learning model: a small machine-learning model per chart that keeps re-training itself and paper-trades next
to the fixed CALL/PUT rule. It only takes over the trade signal ("auto-upgrade") once it has proven, on candles it
had never seen, that it does better than the rule.

How it learns (no look-ahead, tested):
  1. Every closed candle is described by ~20 numbers (FEATURES): trend, pattern score, RSI, recent moves, candle
     shape, place in the recent range, volatility, volume, time of day. All of them use only that candle and older.
  2. Every candle also becomes a lesson once its trade is over: "a CALL bought at this close made +2R" (or -1R...),
     with exactly the rule's stop-loss, target and exits; a PUT likewise.
  3. Every RETRAIN_EVERY new candles it re-trains on all lessons that had finished by then: two models that
     estimate the R a CALL and a PUT would make (gradient-boosted trees, scikit-learn).
  4. Each new candle is judged by the newest model, which has never seen it: CALL or PUT when it expects more than
     +EDGE R, otherwise WAIT. These paper decisions are stored and never changed: they are its track record.
  5. The gate: it takes over (Auto mode) only after GATE_TRADES paper trades, with an average R that is above 0 by
     GATE_Z standard errors (so not luck) and higher than the rule's on the same candles. It falls back to the
     rule by itself if its record drops below that.

Live charts are saved in models/<chart>/ (candles, paper decisions, current model), so what it learns from keeps
growing every day the app runs (up to MAX_CANDLES candles). Test Lab charts are kept in memory only and start over
when the replay data changes.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from . import signal as S
from .patterns import detect

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
FIRST_LESSONS = 800        # finished paper trades (each side) needed before the first training
RETRAIN_EVERY = 200        # re-train after this many new candles
EDGE = 0.10                # trade only when the model expects more than +0.10R
GATE_TRADES = 100          # paper trades on unseen candles needed before it may take over
GATE_Z = 2.0               # ... with average R - 2 standard errors > 0
MAX_CANDLES = 20_000       # candles kept per chart (the oldest are dropped)
WARM = 60                  # first candles have too little history for the features
WAIT_SECONDS = 4.0         # how long a request waits for the newest candle to be judged

COLS = ["time", "open", "high", "low", "close", "volume"]
PRED_COLS = ["time", "call_r", "put_r", "version"]
FEATURES = [
    ("trend", "Trend (EMA20 vs EMA50)"),
    ("patterns", "Pattern score"),
    ("rsi", "RSI"),
    ("gap", "EMA gap"),
    ("ret1", "Last candle's move"),
    ("ret3", "Move over 3 candles"),
    ("ret5", "Move over 5 candles"),
    ("ret10", "Move over 10 candles"),
    ("ret20", "Move over 20 candles"),
    ("body", "Candle body"),
    ("upper_wick", "Upper wick"),
    ("lower_wick", "Lower wick"),
    ("range_atr", "Candle size"),
    ("pos_in_20", "Place in the 20-candle range"),
    ("dist_ema20", "Distance from EMA20"),
    ("vol_regime", "Volatility vs usual"),
    ("volume", "Volume vs usual"),
    ("textbook_bull", "Bullish textbook patterns"),
    ("textbook_bear", "Bearish textbook patterns"),
    ("session_pos", "Time of day"),
]
NEVER = np.iinfo(np.int64).max


# ---------------------------------------------------------------- features and lessons

def features(df: pd.DataFrame, patterns: list[dict], comp: dict) -> np.ndarray:
    """One row of FEATURES per candle, using only that candle and older ones."""
    o, h, l, c, v = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close", "volume"))
    atr, n = comp["atr"], len(df)
    cs = pd.Series(c)
    f = {"trend": comp["trend"], "patterns": comp["pattern"], "rsi": comp["rsi"] / 100 - 0.5,
         "gap": np.clip(comp["gap"], -5, 5)}
    for m in (1, 3, 5, 10, 20):
        f[f"ret{m}"] = np.clip((cs - cs.shift(m)).to_numpy() / atr, -10, 10)
    rng = np.maximum(h - l, 1e-12)
    f["body"] = (c - o) / rng
    f["upper_wick"] = (h - np.maximum(o, c)) / rng
    f["lower_wick"] = (np.minimum(o, c) - l) / rng
    f["range_atr"] = np.clip(rng / atr, 0, 10)
    hi20 = pd.Series(h).rolling(20, min_periods=5).max().to_numpy()
    lo20 = pd.Series(l).rolling(20, min_periods=5).min().to_numpy()
    f["pos_in_20"] = (c - lo20) / np.maximum(hi20 - lo20, 1e-12)
    f["dist_ema20"] = np.clip((c - cs.ewm(span=20, adjust=False).mean().to_numpy()) / atr, -10, 10)
    f["vol_regime"] = np.clip(atr / pd.Series(atr).rolling(100, min_periods=20).mean().to_numpy(), 0, 10)
    vm = pd.Series(v).rolling(20, min_periods=5).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        f["volume"] = np.where(vm > 0, np.log1p(v) - np.log1p(np.nan_to_num(vm)), 0.0)
    bull, bear = np.zeros(n), np.zeros(n)
    for p in patterns:                                  # textbook patterns on this or the 2 previous candles
        if p["name"] in S.LAGGING:
            continue
        for i in range(p["index"], min(n, p["index"] + 3)):
            if p["direction"] == "bullish":
                bull[i] += 1
            elif p["direction"] == "bearish":
                bear[i] += 1
    f["textbook_bull"], f["textbook_bear"] = bull, bear
    t = df["time"].to_numpy()
    step = float(np.median(np.diff(t))) if n > 1 else 60.0
    if step < 86400:                                    # candles since the session opened
        idx = np.arange(n)
        first = np.r_[True, np.diff(t) > 1.5 * step]
        f["session_pos"] = np.minimum((idx - np.maximum.accumulate(np.where(first, idx, 0))) / 400, 1.0)
    else:
        f["session_pos"] = np.zeros(n)
    x = pd.DataFrame(f)[[k for k, _ in FEATURES]]
    return x.replace([np.inf, -np.inf], 0).fillna(0).to_numpy(dtype=float)


def session_ends(t) -> np.ndarray:
    """True for the last candle before a break (night, weekend), as in the trade engine."""
    n = len(t)
    e = np.zeros(n, dtype=bool)
    step = float(np.median(np.diff(t))) if n > 1 else 0.0
    if 0 < step < 86400:
        e[:-1] = np.diff(t) > 1.5 * step
    return e


def outcomes(df: pd.DataFrame, atr, d: int, max_hold: int):
    """For every candle: the R that a trade on side d (+1 CALL, -1 PUT) bought at its close made, with the trade
    rule's exits (stop first, target, market close, time limit), and the index of the candle where it ended.
    NaN / -1 = no trade possible there (last candle of a session) or not finished yet."""
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    n = len(c)
    ends = session_ends(df["time"].to_numpy())
    risk = S.SL_ATR * np.asarray(atr, dtype=float)
    stop, target = c - d * risk, c + d * S.RR * risk
    r = np.full(n, np.nan)
    done = np.full(n, -1)
    can = ~ends
    for j in range(1, max_hold + 1):
        m = n - j
        if m <= 0:
            break
        a = can[:m] & (done[:m] < 0)
        if not a.any():
            continue
        hit_stop = a & ((l[j:] <= stop[:m]) if d > 0 else (h[j:] >= stop[:m]))
        hit_tgt = a & ~hit_stop & ((h[j:] >= target[:m]) if d > 0 else (l[j:] <= target[:m]))
        out = a & ~hit_stop & ~hit_tgt & (ends[j:] | (j == max_hold))
        i_s, i_t, i_o = np.nonzero(hit_stop)[0], np.nonzero(hit_tgt)[0], np.nonzero(out)[0]
        r[i_s], r[i_t] = -1.0, S.RR
        r[i_o] = (c[i_o + j] - c[i_o]) * d / risk[i_o]
        for ii in (i_s, i_t, i_o):
            done[ii] = ii + j
    return r, done


def to_decision(call_r, put_r) -> np.ndarray:
    """+1 CALL / -1 PUT when the model expects more than +EDGE R (the better side), else 0 WAIT."""
    cr = np.nan_to_num(np.asarray(call_r, dtype=float), nan=-9.0)
    pr = np.nan_to_num(np.asarray(put_r, dtype=float), nan=-9.0)
    return np.where((cr > EDGE) & (cr >= pr), 1, np.where((pr > EDGE) & (pr > cr), -1, 0))


def _estimator():
    return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=40,
                                         l2_regularization=1.0, early_stopping=False, random_state=0)


def _train(X, rc, kc, rp, kp, upto: int, version: int):
    """Two models on the lessons that had finished by time `upto`, or None if there are too few."""
    ok = np.arange(len(X)) >= WARM
    mc = ok & np.isfinite(rc) & (kc <= upto)
    mp = ok & np.isfinite(rp) & (kp <= upto)
    lessons = int(min(mc.sum(), mp.sum()))
    if lessons < FIRST_LESSONS:
        return None
    t0 = time.time()
    model = {"call": _estimator().fit(X[mc], rc[mc]), "put": _estimator().fit(X[mp], rp[mp])}
    model.update(version=version, cutoff=int(upto), trained_at=time.time(), lessons=lessons,
                 seconds=round(time.time() - t0, 2), importance=[])
    return model


def _sensitivity(model, X) -> list[float]:
    """How much the model's opinion moves when one feature is shuffled, in % of the total (what it looks at)."""
    if len(X) < 50:
        return []
    rng = np.random.default_rng(0)
    base = {s: model[s].predict(X) for s in ("call", "put")}
    out = []
    for j in range(X.shape[1]):
        xp = X.copy()
        xp[:, j] = rng.permutation(xp[:, j])
        out.append(sum(float(np.mean(np.abs(model[s].predict(xp) - base[s]))) for s in ("call", "put")))
    tot = sum(out) or 1.0
    return [round(100 * v / tot, 1) for v in out]


# ---------------------------------------------------------------- track record and the gate

def record(trades: list[dict]) -> dict:
    r = np.array([x["r"] for x in trades], dtype=float)
    n = len(r)
    return {"trades": n,
            "win_rate": round(float((r > 0).mean()), 2) if n else None,
            "total_r": round(float(r.sum()), 1) if n else 0.0,
            "avg_r": round(float(r.mean()), 3) if n else None,
            "se_r": round(float(r.std(ddof=1) / math.sqrt(n)), 3) if n > 1 else None}


def gate(model_rec: dict, rule_rec: dict) -> dict:
    """May the model take over? Enough unseen trades, profit beyond luck, and better than the rule."""
    enough = model_rec["trades"] >= GATE_TRADES
    lower = model_rec["avg_r"] - GATE_Z * model_rec["se_r"] if model_rec["se_r"] is not None else None
    beyond_luck = lower is not None and lower > 0
    rule_avg = rule_rec["avg_r"] if rule_rec["trades"] else 0.0
    beats = model_rec["avg_r"] is not None and model_rec["avg_r"] > rule_avg
    return {"trades_needed": GATE_TRADES, "z": GATE_Z, "enough": enough, "beyond_luck": beyond_luck,
            "beats_rule": beats, "lower": None if lower is None else round(lower, 3),
            "promoted": bool(enough and beyond_luck and beats)}


def _empty_summary() -> dict:
    empty = record([])
    return {"phase": "learning", "candles": 0, "unseen_candles": 0, "since": None, "lessons": 0,
            "lessons_needed": FIRST_LESSONS, "version": 0, "trained_at": None, "trained_lessons": 0,
            "next_retrain_in": None, "record": {"model": empty, "rule": empty}, "gate": gate(empty, empty),
            "importance": [], "history": []}


# ---------------------------------------------------------------- one learner per chart

def _slug(key) -> str:
    provider, symbol, interval, horizon = key
    return re.sub(r"[^A-Za-z0-9._-]", "_", f"{provider}_{symbol}_{interval}_h{horizon}")


class Learner:
    def __init__(self, key: tuple, persist: bool):
        self.key, self.persist = key, persist
        self.horizon = int(key[3])
        self.max_hold = 4 * self.horizon
        self.folder = MODEL_DIR / _slug(key)
        self.cond = threading.Condition()
        self.busy = False
        self.pending = None          # newest frame waiting to be learned from
        self.force = False           # "Retrain now" was pressed
        self.queued = 0              # newest candle time already handed to the worker
        self.generation = 0          # bumped on reset: results computed for older data are thrown away
        self.dead = False
        self.error = None
        self._clear()
        self.saved_version = 0
        if persist:
            self._load()

    def _clear(self):
        self.candles = pd.DataFrame({k: pd.Series(dtype="int64" if k == "time" else "float64") for k in COLS})
        self.preds = pd.DataFrame({k: pd.Series(dtype="float64") for k in PRED_COLS}).astype({"time": "int64",
                                                                                             "version": "int64"})
        self.model = None
        self.log = []
        self.processed = 0           # newest candle time that went through the walk-forward step
        self.queued = 0
        self.summary = _empty_summary()
        self.generation += 1

    # ---- what the web app calls
    def submit(self, frame: pd.DataFrame | None, retrain: bool = False) -> None:
        """Learn from `frame` (closed candles, oldest first) in the background, if it holds anything new."""
        with self.cond:
            if frame is not None and len(frame):
                frame = frame[COLS].reset_index(drop=True)
                last = int(frame["time"].iloc[-1])
                if not self.persist and self._data_changed(frame):
                    self._clear()                       # Test Lab: new data, new follow-through, or jumped back
                if last <= max(self.processed, self.queued) and not retrain:
                    return
                self.pending, self.queued = frame, last
            elif not retrain:
                return
            self.force = self.force or retrain
            if not self.busy:
                self.busy = True
                threading.Thread(target=self._work, daemon=True).start()

    def wait(self, last_time: int, timeout: float = WAIT_SECONDS) -> None:
        """Wait (a little) until the candle at `last_time` has been judged, unless the first training is still
        running: then the page shows 'studying' and asks again."""
        end = time.time() + timeout
        with self.cond:
            while self.busy and self.processed < last_time and self.model is not None:
                left = end - time.time()
                if left <= 0:
                    break
                self.cond.wait(left)

    def view(self, frame: pd.DataFrame) -> dict:
        """The stored paper decisions for the candles of `frame`, plus the model's status."""
        with self.cond:
            preds, summary, busy, error = self.preds, self.summary, self.busy, self.error
        m = frame[["time"]].merge(preds[["time", "call_r", "put_r"]], on="time", how="left")
        call_r, put_r = m["call_r"].to_numpy(dtype=float), m["put_r"].to_numpy(dtype=float)
        return {"call_r": call_r, "put_r": put_r, "decision": to_decision(call_r, put_r), "summary": summary,
                "busy": busy, "error": error, "edge": EDGE}

    # ---- background work
    def _work(self):
        while True:
            with self.cond:
                frame, force = self.pending, self.force
                self.pending, self.force = None, False
                if (frame is None and not force) or self.dead:
                    self.busy = False
                    self.cond.notify_all()
                    return
                gen = self.generation
                state = (self.candles, self.preds, self.model, list(self.log), self.processed)
            try:
                new, err = self.update(state, frame, force), None
            except Exception as e:                     # keep the app running; the card shows the problem
                new, err = None, f"{type(e).__name__}: {e}"
            with self.cond:
                if gen != self.generation or self.dead:
                    continue
                self.error = err
                if new:
                    self.candles, self.preds, self.model, self.log, self.processed, self.summary = new
                self.cond.notify_all()
            if new and self.persist:
                try:
                    self._save(new)
                except OSError as e:
                    self.error = f"could not save the model: {e}"

    def update(self, state, frame, force=False):
        """Add the new candles of `frame`, walk forward over every candle not judged yet (re-training every
        RETRAIN_EVERY candles), then re-measure the track records and the gate. Pure: returns the new state."""
        candles, preds, model, log, processed = state
        if frame is not None and len(frame):
            last_old = int(candles["time"].iloc[-1]) if len(candles) else -1
            add = frame.loc[frame["time"] > last_old, COLS]
            if len(add):
                candles = pd.concat([candles, add], ignore_index=True) if len(candles) else add.reset_index(drop=True)
                candles = candles.astype({"time": "int64"})
            if len(candles) > MAX_CANDLES:
                candles = candles.iloc[-MAX_CANDLES:].reset_index(drop=True)
                preds = preds[preds["time"] >= candles["time"].iloc[0]]
        n = len(candles)
        if n == 0:
            return candles, preds, model, log, processed, _empty_summary()
        t = candles["time"].to_numpy(dtype=np.int64)
        pats = detect(candles)
        comp = S.components(candles, pats, self.horizon)
        X = features(candles, pats, comp)
        rc, dc = outcomes(candles, comp["atr"], +1, self.max_hold)
        rp, dp = outcomes(candles, comp["atr"], -1, self.max_hold)
        kc = np.where(dc >= 0, t[np.clip(dc, 0, n - 1)], NEVER)
        kp = np.where(dp >= 0, t[np.clip(dp, 0, n - 1)], NEVER)
        version = max([x["version"] for x in log] + [model["version"] if model else 0])
        fresh = False

        def retrain(upto):
            nonlocal model, version, fresh
            m = _train(X, rc, kc, rp, kp, int(upto), version + 1)
            if m:
                model, version, fresh = m, version + 1, True
                log.append({k: m[k] for k in ("version", "cutoff", "trained_at", "lessons", "seconds")})

        if force and processed:
            retrain(processed)                         # lessons finished by the last judged candle, never later
        cut = lambda: int(np.searchsorted(t, model["cutoff"]))
        i = max(WARM, int(np.searchsorted(t, processed, side="right")) if processed else 0)
        new_rows = []
        while i < n:
            if model is None or i - cut() > RETRAIN_EVERY:
                retrain(t[i - 1])
            if model is None:                          # still collecting lessons
                i += 1
                continue
            stop = max(i + 1, min(n, cut() + RETRAIN_EVERY + 1))
            new_rows.append(pd.DataFrame({"time": t[i:stop], "call_r": model["call"].predict(X[i:stop]),
                                          "put_r": model["put"].predict(X[i:stop]), "version": model["version"]}))
            i = stop
        if new_rows:
            preds = pd.concat([preds] + new_rows, ignore_index=True) if len(preds) else pd.concat(new_rows, ignore_index=True)
        if fresh:
            model = {**model, "importance": _sensitivity(model, X[max(WARM, n - 1500):])}
        return candles, preds, model, log, int(t[-1]), self._summarize(candles, comp, preds, model, rc, rp, log)

    def _summarize(self, candles, comp, preds, model, rc, rp, log) -> dict:
        n = len(candles)
        t = candles["time"].to_numpy(dtype=np.int64)
        m = candles[["time"]].merge(preds, on="time", how="left")
        call_r, put_r = m["call_r"].to_numpy(dtype=float), m["put_r"].to_numpy(dtype=float)
        has = np.isfinite(call_r)
        rec_m = rec_r = record([])
        since = None
        if has.any():
            w0 = int(np.argmax(has))
            since = int(t[w0])
            rule = S.decide(comp["pattern"], comp["trend"]).copy()
            rule[:w0] = 0                               # the rule judged on the same candles as the model
            rec_m = record(S.run_trades(candles, to_decision(call_r, put_r), comp["atr"], self.max_hold)[0])
            rec_r = record(S.run_trades(candles, rule, comp["atr"], self.max_hold)[0])
        imp = model.get("importance") if model else []
        top = sorted(zip([name for _, name in FEATURES], imp or []), key=lambda x: -x[1])[:6]
        lessons = int(min(np.isfinite(rc[WARM:]).sum(), np.isfinite(rp[WARM:]).sum())) if n > WARM else 0
        return {
            "phase": "ready" if model else "learning",
            "candles": n, "unseen_candles": int(has.sum()), "since": since,
            "lessons": lessons, "lessons_needed": FIRST_LESSONS,
            "version": model["version"] if model else 0,
            "trained_at": model["trained_at"] if model else None,
            "trained_lessons": model["lessons"] if model else 0,
            "next_retrain_in": max(0, RETRAIN_EVERY - (n - 1 - int(np.searchsorted(t, model["cutoff"]))))
            if model else None,
            "record": {"model": rec_m, "rule": rec_r},
            "gate": gate(rec_m, rec_r),
            "importance": [{"name": a, "pct": b} for a, b in top],
            "history": [{k: x[k] for k in ("version", "trained_at", "lessons")} for x in log[-5:]][::-1],
        }

    def _data_changed(self, frame) -> bool:
        """Test Lab only: did the replay restart, get new data, or jump back before what was learned?"""
        if not self.processed:
            return False
        if int(frame["time"].iloc[-1]) < self.processed:
            return True
        a = frame.loc[frame["time"] == self.processed, "close"]
        b = self.candles.loc[self.candles["time"] == self.processed, "close"]
        return a.empty or b.empty or abs(float(a.iloc[0]) - float(b.iloc[0])) > 1e-9

    # ---- saving (live charts only)
    def _save(self, state):
        candles, preds, model, log, processed, summary = state
        self.folder.mkdir(parents=True, exist_ok=True)
        _atomic(self.folder / "candles.csv", lambda p: candles.to_csv(p, index=False))
        _atomic(self.folder / "paper_decisions.csv", lambda p: preds.to_csv(p, index=False))
        if model and model["version"] != self.saved_version:
            _atomic(self.folder / "model.joblib", lambda p: joblib.dump(model, p))
            self.saved_version = model["version"]
        meta = {"chart": list(self.key), "processed": processed, "saved_at": time.time(), "log": log[-500:],
                "summary": summary}
        _atomic(self.folder / "meta.json", lambda p: Path(p).write_text(json.dumps(meta, indent=1), encoding="utf-8"))

    def _load(self):
        try:
            meta = json.loads((self.folder / "meta.json").read_text(encoding="utf-8"))
            candles = pd.read_csv(self.folder / "candles.csv").astype({"time": "int64"})
            preds = pd.read_csv(self.folder / "paper_decisions.csv").astype({"time": "int64", "version": "int64"})
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError) as e:
            self.error = f"could not read the saved model, starting over ({e})"
            return
        self.candles, self.preds = candles[COLS], preds[PRED_COLS]
        self.processed, self.log, self.summary = int(meta["processed"]), meta.get("log", []), meta["summary"]
        try:
            self.model = joblib.load(self.folder / "model.joblib")
            self.saved_version = self.model["version"]
        except Exception:                               # missing or from another scikit-learn: re-train
            self.model = None


def _atomic(path: Path, write) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    write(tmp)
    os.replace(tmp, path)


# ---------------------------------------------------------------- registry

_learners: dict[tuple, Learner] = {}
_lock = threading.Lock()


def chart_key(provider: str, symbol: str, interval: str, horizon: int) -> tuple:
    return provider, symbol.strip().upper(), interval, int(horizon)


def get(provider: str, symbol: str, interval: str, horizon: int, persist: bool = True) -> Learner:
    key = chart_key(provider, symbol, interval, horizon)
    with _lock:
        lr = _learners.get(key)
        if lr is None:
            lr = _learners[key] = Learner(key, persist)
        return lr


def reset(provider: str, symbol: str, interval: str, horizon: int) -> None:
    """Forget everything learned on this chart (also on disk)."""
    key = chart_key(provider, symbol, interval, horizon)
    with _lock:
        lr = _learners.pop(key, None)
    if lr:
        with lr.cond:
            lr.dead = True
    shutil.rmtree(MODEL_DIR / _slug(key), ignore_errors=True)


def describe(view: dict, mode: str, active: bool, persist: bool, key: tuple) -> dict:
    """JSON for the Self-learning model card."""
    cr = float(view["call_r"][-1]) if len(view["call_r"]) else float("nan")
    pr = float(view["put_r"][-1]) if len(view["put_r"]) else float("nan")
    opinion = None
    if math.isfinite(cr):
        says = int(view["decision"][-1])
        opinion = {"call_r": round(cr, 3), "put_r": round(pr, 3), "says": S.SIDE.get(says, "WAIT")}
    return {**view["summary"], "mode": mode, "active": "model" if active else "rule", "busy": view["busy"],
            "error": view["error"], "opinion": opinion, "edge": EDGE, "retrain_every": RETRAIN_EVERY,
            "saved": persist, "folder": f"models/{_slug(key)}" if persist else None}
