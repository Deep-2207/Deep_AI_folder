"""Test data for learning when the market is closed: candles are revealed one by one as if live.

Providers:
  nse_replay  real past NSE candles from Yahoo (RELIANCE -> RELIANCE.NS, ^NSEI = NIFTY 50, ^NSEBANK = Bank Nifty)
  seeder      synthetic NSE-like candles full of textbook patterns; after a pattern, price ends up moving the
              textbook way about `follow` of the time (0.5 = patterns carry no information, nothing to learn)

A replay session per (provider, symbol, interval) keeps a play position that advances `speed` candles per
minute of wall time. The newest candle is built up gradually (open -> full candle) so it looks like a live feed.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .feeds import INTERVAL_SECONDS, get_candles
from .patterns import detect

PROVIDERS = ("nse_replay", "seeder")
IST = timezone(timedelta(hours=5, minutes=30))
SESSION_MINUTES = 375                    # NSE 09:15 - 15:30 IST

# ---------------------------------------------------------------- pattern seeder
#
# Closes are a pure random walk: the step from one close to the next never depends on the past, so at
# follow = 0.5 there is nothing to predict, for the trade rule or for a learning model. Textbook patterns are
# made frequent by drawing each candle's open (a small gap) and wicks from the candles before it and its own
# close only, never from the future: e.g. a long lower wick after a fall is a Hammer, a small gap-down candle
# after a big red one is the star of a Morning Star. With follow > 0.5, after a textbook pattern price makes a
# clear 5-candle move the textbook way with probability 2 x follow - 1 (so it ends up moving the textbook way
# about `follow` of the time); below 0.5 the move goes the other way.
#
# (An earlier version planted ready-made multi-candle shapes after big moves. Their later candles could be
# predicted from the first one, which a machine-learning model exploited even at follow = 0.5.)

UNIT = 0.0012                            # one "unit" = 0.12% of price, about one typical close-to-close move
TICK = 0.05                              # NSE price tick
COOLDOWN = 7                             # candles after a planted pattern before the next one counts


def _tick(v: float) -> float:
    return round(round(v / TICK) * TICK, 2)


def seed_candles(n: int = 3000, follow: float = 0.7, seed: int = 7, price: float = 2500.0) -> tuple[list, list]:
    """Synthetic OHLC rows (prices on the 0.05 tick) plus (row index, name) of every planted pattern: the
    textbook (bullish / bearish) patterns that decided a follow-through, at least COOLDOWN candles apart."""
    rng = np.random.default_rng(seed)
    u = price * UNIT
    strength = 2 * follow - 1
    rows: list[tuple] = []

    def trend_before(start: int) -> int:   # same as detect(): 5-candle close change vs the 14-candle avg range
        if start < 6:
            return 0
        lo = max(0, start - 14)
        atr = sum(r[1] - r[2] for r in rows[lo:start]) / (start - lo)
        chg = rows[start - 1][3] - rows[start - 6][3]
        return 1 if chg > atr else -1 if chg < -atr else 0

    def avg_body(k: int) -> float:
        lo = max(0, k - 13)
        return sum(abs(r[3] - r[0]) for r in rows[lo:k + 1]) / (k + 1 - lo)

    def next_candle(extra: float) -> tuple:
        i = len(rows)
        x = rows[-1][3] if rows else price
        s = ((extra + rng.normal(0, 0.3)) if extra else rng.normal(0, 1.0)) * u    # the only thing moving price
        o, c, b = x, x + s, abs(s)
        up, lo = rng.uniform(0.2, 0.5) * u, rng.uniform(0.2, 0.5) * u
        roll = rng.random()
        if i >= 20:
            op, _, _, cp = rows[-1]
            bp = abs(cp - op)
            t = trend_before(i - 1)                         # context of a pattern whose first candle is the previous
            with_trend = t and (cp - op) * t > 0 and bp >= avg_body(i - 1)   # big red after a fall / green after a rise
            if b >= 1.8 * u and roll < 0.25:                # Marubozu: (almost) no wicks
                up, lo = rng.uniform(0, 0.02) * b, rng.uniform(0, 0.02) * b
            elif b <= 0.08 * u and roll < 0.5:              # Dragonfly / Gravestone doji
                long, short = rng.uniform(1.0, 1.6) * u, rng.uniform(0, 0.05) * u
                up, lo = (long, short) if rng.random() < 0.5 else (short, long)
            elif b <= 0.6 * u and roll < 0.35 and trend_before(i):
                # Hammer / Inverted Hammer after a fall, Hanging Man / Shooting Star after a rise (either wick, 50/50)
                long = max(2.2 * b, rng.uniform(1.0, 1.8) * u)
                short = rng.uniform(0, 0.08) * (b + long)
                up, lo = (long, short) if rng.random() < 0.5 else (short, long)
            elif with_trend and bp / 2 < -s * t < bp and roll < 0.8:
                o = cp + t * rng.uniform(0.02, 0.15) * u    # Piercing Line / Dark Cloud Cover: open beyond the close
            elif with_trend and 0 <= s * t <= 0.6 * bp and roll < 0.6:
                # the star of a Morning / Evening Star: opens beyond the big candle's close, near its own close
                o = cp + t * max(0.02 * u, b + rng.uniform(-0.15, 0.15) * bp)
            elif (cp - op) * s > 0 and b >= 0.5 * u and bp >= 0.5 * u and roll < 0.3:
                # Three White Soldiers / Black Crows: opens inside the previous body, short wick at the far end
                o = cp - (cp - op) * rng.uniform(0.1, 0.4)
                if s > 0:
                    up = rng.uniform(0, 0.25) * (b + abs(cp - o))
                else:
                    lo = rng.uniform(0, 0.25) * (b + abs(cp - o))
        return _tick(o), _tick(max(o, c) + up), _tick(min(o, c) - lo), _tick(c)

    def textbook(start: int) -> list[tuple]:
        """(index, name, +1/-1) of textbook patterns completing at index >= start, earliest first."""
        lo = max(0, start - 30)
        win = pd.DataFrame(rows[lo:], columns=["open", "high", "low", "close"])
        if len(win) < 20:
            return []
        win.insert(0, "time", np.arange(len(win)))
        by = {}
        for p in detect(win, chart_patterns=False):
            if p["index"] + lo >= start and p["direction"] in ("bullish", "bearish"):
                by.setdefault(p["index"] + lo, []).append(p)
        return [(k, ps[0]["name"], 1 if ps[0]["direction"] == "bullish" else -1)
                for k, ps in sorted(by.items()) if len({p["direction"] for p in ps}) == 1]

    planted, drift = [], []
    if not strength:                                        # nothing follows a pattern: draw, then just list them
        while len(rows) < n:
            rows.append(next_candle(0.0))
        free = 25
        for k, name, _ in textbook(0):
            if k >= free:
                planted.append((k, name))
                free = k + COOLDOWN
        return rows, planted

    free, checked = 25, 0
    while len(rows) < n:
        rows.append(next_candle(drift.pop(0) if drift else 0.0))
        if len(rows) - checked < 20 and len(rows) < n:
            continue
        found = textbook(max(checked, free))
        if not found:
            checked = len(rows)
            continue
        k, name, d = found[0]
        del rows[k + 1:]                                    # re-draw what comes after the pattern
        planted.append((k, name))
        if rng.random() < abs(strength):
            way = d if strength > 0 else -d
            drift = [way * rng.uniform(0.5, 1.0) for _ in range(5)]
        free, checked = k + COOLDOWN, k + 1
    return rows, planted


def nse_times(n: int, step: int) -> list[int]:
    """`n` candle open times inside NSE sessions (weekdays 09:15-15:30 IST), ending with the latest session."""
    per_day = max(1, SESSION_MINUTES * 60 // step)
    days, d = [], datetime.now(IST).date()
    while len(days) * per_day < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    out = []
    for day in reversed(days):
        start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp()
        out += [int(start + k * step) for k in range(per_day)]
    return out[-n:]


def seeded_frame(interval: str, follow: float, seed: int, n: int = 3000) -> pd.DataFrame:
    rows, _ = seed_candles(n, follow, seed)
    df = (pd.DataFrame(rows, columns=["open", "high", "low", "close"]) / 0.05).round() * 0.05   # NSE tick 0.05
    df = df.round(2)
    df.insert(0, "time", nse_times(len(df), INTERVAL_SECONDS[interval]))
    df["volume"] = np.random.default_rng(seed).integers(1_000, 50_000, len(df)).astype(float)
    return df


# ---------------------------------------------------------------- replay sessions

def nse_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    return s if s.startswith("^") or "." in s else s + ".NS"


class Session:
    def __init__(self, provider: str, symbol: str, interval: str, follow: float = 0.7, seed: int = 7):
        self.provider, self.symbol, self.interval = provider, symbol, interval
        self.follow, self.seed = follow, seed
        self.step = INTERVAL_SECONDS[interval]
        if provider == "nse_replay":
            self.source = get_candles("yahoo", nse_symbol(symbol), interval, 20_000)
        else:
            self.source = seeded_frame(interval, follow, seed)
        n = len(self.source)
        self.pos = float(min(n, max(min(300, n), n - 400)))   # start with history, leave ~400 candles to play
        self.speed = 20.0                                     # candles per minute
        self.playing = True
        self.last = time.time()

    def advance(self):
        now = time.time()
        if self.playing:
            self.pos = min(float(len(self.source)), self.pos + (now - self.last) * self.speed / 60)
            if self.pos >= len(self.source):
                self.playing = False
        self.last = now

    def view(self) -> tuple[pd.DataFrame, bool]:
        """Candles revealed so far; the last one is partial while it is 'forming'."""
        k = int(self.pos)
        f = self.pos - k
        df = self.source.iloc[:k]
        if f > 0 and k < len(self.source):
            o, h, l, c, v = (float(self.source[x].iloc[k]) for x in ("open", "high", "low", "close", "volume"))
            cp = o + (c - o) * f
            part = {"time": int(self.source["time"].iloc[k]), "open": o, "close": cp, "volume": v * f,
                    "high": max(o, cp) + (h - max(o, c)) * f, "low": min(o, cp) - (min(o, c) - l) * f}
            df = pd.concat([df, pd.DataFrame([part])], ignore_index=True)
            return df.reset_index(drop=True), True
        return df.reset_index(drop=True), False

    def state(self) -> dict:
        n = len(self.source)
        k = min(int(self.pos), n - 1)
        t = int(self.source["time"].iloc[k])
        return {
            "provider": self.provider, "symbol": self.symbol, "interval": self.interval,
            "position": round(self.pos, 2), "total": n, "playing": self.playing, "speed": self.speed,
            "follow": self.follow, "seed": self.seed,
            "current_time_ist": datetime.fromtimestamp(t, IST).strftime("%a %d %b %Y %H:%M IST"),
            "start_time_ist": datetime.fromtimestamp(int(self.source["time"].iloc[0]), IST).strftime("%d %b %H:%M"),
            "end_time_ist": datetime.fromtimestamp(int(self.source["time"].iloc[-1]), IST).strftime("%d %b %H:%M"),
        }


_sessions: dict[tuple, Session] = {}
_lock = threading.Lock()


def _key(provider, symbol, interval):
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {PROVIDERS}")
    if interval not in INTERVAL_SECONDS:
        raise ValueError(f"interval must be one of {sorted(INTERVAL_SECONDS)}")
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    return provider, symbol.strip().upper(), interval


def session(provider: str, symbol: str, interval: str) -> Session:
    key = _key(provider, symbol, interval)
    with _lock:
        s = _sessions.get(key)
        if s is None:
            s = _sessions[key] = Session(*key)
        s.advance()
        return s


def control(provider: str, symbol: str, interval: str, action: str, value=None) -> Session:
    key = _key(provider, symbol, interval)
    s = session(provider, symbol, interval)
    with _lock:
        n = len(s.source)
        if action == "play":
            s.playing = s.pos < n
        elif action == "pause":
            s.playing = False
        elif action == "step":                      # finish the forming candle, or reveal one more
            s.pos = float(min(n, int(s.pos) + 1))
            s.playing = False
        elif action == "seek":
            s.pos = float(max(30, min(n, int(value))))
        elif action == "speed":
            s.speed = float(max(0.1, min(600, float(value))))
        elif action == "follow":                    # seeder only: rebuild data with a new follow-through
            if s.provider != "seeder":
                raise ValueError("follow-through only applies to the pattern seeder")
            s = _sessions[key] = Session(*key, follow=float(value), seed=s.seed)
        elif action == "new":                       # seeder: fresh random data; replay: restart
            if s.provider == "seeder":
                s = _sessions[key] = Session(*key, follow=s.follow, seed=s.seed + 1)
            else:
                s = _sessions[key] = Session(*key)
        else:
            raise ValueError(f"unknown action '{action}'")
        s.last = time.time()
        return s
