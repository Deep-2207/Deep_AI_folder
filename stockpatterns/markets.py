"""Market hours (NSE, US) and a live ranking of stocks that are actually moving, so tests use a lively chart.

Holidays are not included: on an exchange holiday the market shows as 'open' but the data will look stale.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .feeds import _session, get_candles

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


UNIVERSES = {
    "nifty50": {
        "name": "NIFTY 50 Bluechips",
        "market": "nse",
        "symbols": [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT",
            "HINDUNILVR", "ADANIENT", "AXISBANK", "MARUTI", "SUNPHARMA", "BAJFINANCE", "TATAMOTORS",
            "KOTAKBANK", "M&M", "NTPC", "POWERGRID", "ONGC", "TITAN", "ULTRACEMCO", "COALINDIA",
            "TATASTEEL", "JSWSTEEL", "ADANIPORTS", "BAJAJFINSV", "ASIANPAINT", "HINDALCO", "TECHM",
            "WIPRO", "GRASIM", "HEROMOTOCO", "EICHERMOT", "NESTLEIND", "DRREDDY", "CIPLA", "DIVISLAB",
            "APOLLOHOSP", "SHRIRAMFIN", "TRENT", "BEL", "HAL", "VEDL", "BPCL", "PIDILITIND", "SIEMENS",
            "ZOMATO", "JIOFIN",
        ],
    },
    "nse_banking": {
        "name": "NSE Banks & Financials",
        "market": "nse",
        "symbols": [
            "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BANKBARODA", "PNB", "CANBK",
            "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB", "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN",
            "SHRIRAMFIN", "MUTHOOTFIN", "JIOFIN",
        ],
    },
    "nse_it": {
        "name": "NSE IT & Tech",
        "market": "nse",
        "symbols": [
            "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE",
            "MPHASIS", "OFSS", "TATAELXSI", "LTTS",
        ],
    },
    "nse_auto": {
        "name": "NSE Auto & Metals",
        "market": "nse",
        "symbols": [
            "TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR",
            "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC",
        ],
    },
    "us_megacap": {
        "name": "US Mega Caps & Tech",
        "market": "us",
        "symbols": [
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK-B", "LLY", "JPM",
            "AVGO", "V", "UNH", "WMT", "XOM", "MA", "PG", "COST", "JNJ", "HD",
            "NFLX", "AMD", "CRM", "ORCL", "BAC",
        ],
    },
    "us_growth": {
        "name": "US High Beta & Growth",
        "market": "us",
        "symbols": [
            "SOXL", "RIOT", "MARA", "PLTR", "COIN", "AMD", "MSTR", "AFRM", "SOFI", "HOOD",
            "SMCI", "IONQ", "RGTI", "RIVN", "UBER", "SNOW", "UPST", "TQQQ",
        ],
    },
}

_radar_cache: dict[str, tuple[float, dict]] = {}
RADAR_TTL = 60


def _fetch_quote_meta(sym: str, market: str) -> dict | None:
    sym = sym.strip().upper()
    if not sym:
        return None
    yahoo_sym = sym + ".NS" if market == "nse" and not sym.endswith(".NS") and not sym.startswith("^") else sym
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}",
            params={"interval": "1d", "range": "1d"},
            timeout=8,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("chart", {}).get("result")
        if not data:
            return None
        meta = data[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            return None
        price = float(price)
        change_pct = meta.get("regularMarketChangePercent")
        change_pct = round(float(change_pct), 2) if change_pct is not None else 0.0
        prev_close = meta.get("chartPreviousClose")
        change_pts = round(price - float(prev_close), 2) if prev_close else round(price * change_pct / 100, 2)

        low_52 = meta.get("fiftyTwoWeekLow")
        high_52 = meta.get("fiftyTwoWeekHigh")
        low_52 = float(low_52) if low_52 is not None else None
        high_52 = float(high_52) if high_52 is not None else None

        dist_52w_low_pct = None
        if low_52 is not None and low_52 > 0:
            dist_52w_low_pct = round(((price - low_52) / low_52) * 100, 2)

        dist_52w_high_pct = None
        if high_52 is not None and high_52 > 0:
            dist_52w_high_pct = round(((price - high_52) / high_52) * 100, 2)

        range_52w_pos_pct = None
        if low_52 is not None and high_52 is not None and high_52 > low_52:
            range_52w_pos_pct = round(max(0.0, min(100.0, ((price - low_52) / (high_52 - low_52)) * 100)), 1)

        name = meta.get("shortName") or meta.get("longName") or sym
        return {
            "symbol": sym,
            "full_symbol": yahoo_sym,
            "name": name,
            "market": market,
            "price": price,
            "change": change_pts,
            "change_pct": change_pct,
            "day_low": float(meta.get("regularMarketDayLow")) if meta.get("regularMarketDayLow") else None,
            "day_high": float(meta.get("regularMarketDayHigh")) if meta.get("regularMarketDayHigh") else None,
            "volume": int(meta.get("regularMarketVolume") or 0),
            "fifty_two_week_low": low_52,
            "fifty_two_week_high": high_52,
            "dist_52w_low_pct": dist_52w_low_pct,
            "dist_52w_high_pct": dist_52w_high_pct,
            "range_52w_pos_pct": range_52w_pos_pct,
            "currency": meta.get("currency", "INR" if market == "nse" else "USD"),
        }
    except Exception:
        return None


def radar(universe_key: str = "nifty50", custom_symbols: list[str] | None = None, force: bool = False) -> dict:
    """Returns today's gainers, losers, and stocks near 52-week low for the chosen universe or custom symbols."""
    is_custom = bool(custom_symbols)
    if is_custom:
        symbols = [s.strip().upper() for s in custom_symbols if s.strip()]
        if not symbols:
            raise ValueError("custom symbols list cannot be empty")
        market = "nse" if any(s.endswith(".NS") for s in symbols) else "us"
        u_name = "Custom Watchlist"
        cache_key = "custom:" + ",".join(sorted(symbols))
    else:
        if universe_key not in UNIVERSES:
            raise ValueError(f"universe must be one of {sorted(UNIVERSES)}")
        u_info = UNIVERSES[universe_key]
        symbols = u_info["symbols"]
        market = u_info["market"]
        u_name = u_info["name"]
        cache_key = universe_key

    with _lock:
        hit = _radar_cache.get(cache_key)
        if not force and hit and time.time() - hit[0] < RADAR_TTL:
            return hit[1]

    with ThreadPoolExecutor(10) as ex:
        rows = [r for r in ex.map(lambda s: _fetch_quote_meta(s, market), symbols) if r]

    # Categorize and sort
    gainers = sorted([r for r in rows if r["change_pct"] > 0], key=lambda r: -r["change_pct"])
    losers = sorted([r for r in rows if r["change_pct"] < 0], key=lambda r: r["change_pct"])

    # Sort by proximity to 52-week low (lowest dist_52w_low_pct first)
    with_low = [r for r in rows if r["dist_52w_low_pct"] is not None]
    lowest = sorted(with_low, key=lambda r: r["dist_52w_low_pct"])

    # Sort by proximity to 52-week high
    with_high = [r for r in rows if r["dist_52w_high_pct"] is not None]
    highest = sorted(with_high, key=lambda r: -r["dist_52w_high_pct"])

    res = {
        "universe": universe_key if not is_custom else "custom",
        "universe_name": u_name,
        "market": market,
        "updated": int(time.time()),
        "status": status()[market] if market in status() else None,
        "total": len(rows),
        "rows": rows,
        "gainers": gainers,
        "losers": losers,
        "lowest": lowest,
        "highest": highest,
    }

    with _lock:
        _radar_cache[cache_key] = (time.time(), res)
    return res

