"""Market hours (NSE, US) and a live ranking of stocks that are actually moving, so tests use a lively chart.

Holidays are not included: on an exchange holiday the market shows as 'open' but the data will look stale.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .feeds import get_candles

IST = timezone(timedelta(hours=5, minutes=30))

# Liquid, usually-volatile names (US: high-beta stocks and 3x ETFs; NSE: high-beta F&O stocks).
WATCH = {
    "us": ["SOXL", "RIOT", "UPST", "MARA", "PLTR", "IONQ", "COIN", "RGTI", "RIVN", "SMCI", "QBTS", "AMD", "MSTR",
           "AFRM", "TQQQ", "SOFI", "HOOD", "TSLA", "NVDA", "AAPL", "META", "AMZN", "NFLX", "AMC"],
    "nse": ["MCX", "ANGELONE", "SBIN", "DIXON", "CDSL", "BSE", "IDEA", "POLICYBZR", "PAYTM", "RELIANCE", "NBCC",
            "SUZLON", "YESBANK", "TMPV", "VEDL", "BHEL", "BEL", "HAL", "TCS", "HDFCBANK", "RVNL", "PNB", "ADANIENT",
            "TRENT", "ICICIBANK", "ADANIPOWER", "HINDCOPPER", "TATASTEEL", "IRFC", "INFY", "ETERNAL"],
}


def _us_fallback(now_utc: datetime) -> datetime:
    """New York time without a tz database: DST runs from the 2nd Sunday of March to the 1st Sunday of November."""
    y = now_utc.year

    def sunday(month, nth):
        d = datetime(y, month, 1, tzinfo=timezone.utc)
        return d + timedelta(days=(6 - d.weekday()) % 7, weeks=nth - 1)

    dst = sunday(3, 2) + timedelta(hours=7) <= now_utc < sunday(11, 1) + timedelta(hours=6)
    return now_utc.astimezone(timezone(timedelta(hours=-4 if dst else -5)))


def _us_local(now_utc: datetime) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return _us_fallback(now_utc)


MARKETS = {
    "nse": {"name": "NSE India", "open": (9, 15), "close": (15, 30), "local": lambda now: now.astimezone(IST)},
    "us": {"name": "US stocks", "open": (9, 30), "close": (16, 0), "local": _us_local},
}


def status(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out = {}
    for key, m in MARKETS.items():
        loc = m["local"](now)
        o = loc.replace(hour=m["open"][0], minute=m["open"][1], second=0, microsecond=0)
        c = loc.replace(hour=m["close"][0], minute=m["close"][1], second=0, microsecond=0)
        is_open = loc.weekday() < 5 and o <= loc < c
        if is_open:
            nxt = c
        else:
            nxt = o if loc < o else o + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
        out[key] = {
            "name": m["name"], "open": is_open, "next": "closes" if is_open else "opens",
            "next_ist": nxt.astimezone(IST).strftime("%a %H:%M IST"),
            "minutes": int((nxt - loc).total_seconds() // 60),
        }
    return out


_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
TTL = 180


def _measure(market: str, sym: str) -> dict | None:
    try:
        df = get_candles("yahoo", sym + ".NS" if market == "nse" else sym, "1m", 3000)
    except Exception:
        return None
    last_t = int(df["time"].iloc[-1])
    day = df[df["time"] >= last_t - 8 * 3600]          # the latest session only
    if len(day) < 30:
        return None
    recent = day.tail(60)
    first_open = float(day["open"].iloc[0])
    return {
        "symbol": sym,
        "price": float(df["close"].iloc[-1]),
        "move_1m_pct": round(float(((recent["high"] - recent["low"]) / recent["close"]).mean() * 100), 3),
        "day_range_pct": round(float((day["high"].max() - day["low"].min()) / first_open * 100), 2),
        "change_pct": round(float((df["close"].iloc[-1] / first_open - 1) * 100), 2),
        "last_time": last_t,
    }


def movers(market: str, top: int = 12) -> dict:
    """Stocks of `market` ranked by their average 1-minute candle size over the last hour of trading."""
    if market not in WATCH:
        raise ValueError(f"market must be one of {sorted(WATCH)}")
    with _lock:
        hit = _cache.get(market)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(lambda s: _measure(market, s), WATCH[market]) if r]
    rows.sort(key=lambda r: -r["move_1m_pct"])
    res = {"market": market, "updated": int(time.time()), "rows": rows[:top], "status": status()[market]}
    with _lock:
        _cache[market] = (time.time(), res)
    return res
