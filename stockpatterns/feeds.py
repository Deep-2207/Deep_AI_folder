"""Free, keyless market-data feeds. Every provider returns the same candle DataFrame:
columns time (unix seconds, candle open), open, high, low, close, volume."""
from __future__ import annotations

import threading
import time

import pandas as pd
import requests

COLUMNS = ["time", "open", "high", "low", "close", "volume"]
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400}

# Public market-data hosts, tried in order (some are geo-blocked in some countries).
BINANCE_HOSTS = [
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api.binance.us",
]
# our interval -> (yahoo interval, yahoo range). 5d on 1m so a closed market still has data.
YAHOO_PARAMS = {
    "1m": ("1m", "7d"),
    "5m": ("5m", "1mo"),
    "15m": ("15m", "1mo"),
    "30m": ("30m", "1mo"),
    "1h": ("60m", "6mo"),
    "1d": ("1d", "10y"),
}

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (StockPatternScanner)"})


class FeedError(RuntimeError):
    """The upstream feed failed or rejected the request."""


def _binance_page(symbol: str, interval: str, limit: int, end_time: int | None) -> list:
    params = {"symbol": symbol.upper(), "interval": interval, "limit": limit}
    if end_time is not None:
        params["endTime"] = end_time
    last_err = None
    for host in BINANCE_HOSTS:
        try:
            r = _session.get(f"{host}/api/v3/klines", params=params, timeout=10)
            if r.status_code == 400:
                raise FeedError(f"Binance rejected '{symbol}' ({r.text.strip()})")
            r.raise_for_status()
            return r.json()
        except FeedError:
            raise
        except requests.RequestException as e:
            last_err = e
    raise FeedError(f"Binance unreachable: {last_err}")


def _binance(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    """Newest `limit` candles; pages backwards 1000 at a time."""
    chunks, end = [], None
    remaining = limit
    while remaining > 0:
        batch = min(1000, remaining)
        rows = _binance_page(symbol, interval, batch, end)
        if not rows:
            break
        chunks.append(pd.DataFrame(rows).iloc[:, :6])
        remaining -= len(rows)
        end = int(rows[0][0]) - 1
        if len(rows) < batch:
            break
    if not chunks:
        raise FeedError(f"No candles returned for {symbol}")
    df = pd.concat(chunks[::-1], ignore_index=True)
    df.columns = COLUMNS
    df["time"] = df["time"].astype("int64") // 1000
    df = df.astype({c: "float64" for c in COLUMNS[1:]})
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def _yahoo(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    yi, rng = YAHOO_PARAMS[interval]
    try:
        r = _session.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": yi, "range": rng},
            timeout=10,
        )
    except requests.RequestException as e:
        raise FeedError(f"Yahoo unreachable: {e}") from e
    if r.status_code == 404:
        raise FeedError(f"Yahoo has no symbol '{symbol}'")
    if r.status_code == 429:
        raise FeedError("Yahoo rate-limited this IP; poll less often")
    r.raise_for_status()
    chart = r.json()["chart"]
    if chart.get("error") or not chart.get("result"):
        raise FeedError(f"Yahoo error for '{symbol}': {chart.get('error')}")
    res = chart["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "time": ts,
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": q["volume"],
        }
    )
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0)
    if df.empty:
        raise FeedError(f"No candles returned for {symbol}")
    df = df.astype({"time": "int64", **{c: "float64" for c in COLUMNS[1:]}}).reset_index(drop=True)
    return _snap_live_point(df, INTERVAL_SECONDS[interval])


def _snap_live_point(df: pd.DataFrame, step: int) -> pd.DataFrame:
    """While the market is open Yahoo ends intraday data with a live price point stamped with the current second
    (e.g. 21:26:55) instead of a candle. Put it on its candle slot, counted from the previous candle (sessions
    don't always start on a round hour), so it becomes the forming candle and the real candle later replaces it."""
    if step >= 86400 or len(df) < 2:
        return df
    prev, last = int(df["time"].iloc[-2]), int(df["time"].iloc[-1])
    if (last - prev) % step == 0:
        return df
    k = (last - prev) // step
    if k == 0:                                     # inside the previous candle: it is that candle's latest price
        i, j = df.index[-2], df.index[-1]
        df.loc[i, "high"] = max(df.loc[i, "high"], df.loc[j, "high"])
        df.loc[i, "low"] = min(df.loc[i, "low"], df.loc[j, "low"])
        df.loc[i, "close"] = df.loc[j, "close"]
        df.loc[i, "volume"] += df.loc[j, "volume"]
        return df.iloc[:-1]
    df.loc[df.index[-1], "time"] = prev + k * step
    return df


PROVIDERS = {"binance": _binance, "yahoo": _yahoo}


def get_candles(provider: str, symbol: str, interval: str = "1m", limit: int = 200) -> pd.DataFrame:
    """Latest `limit` candles, oldest first. The last candle may still be forming."""
    if provider not in PROVIDERS:
        raise ValueError(f"provider must be one of {sorted(PROVIDERS)}")
    if interval not in INTERVAL_SECONDS:
        raise ValueError(f"interval must be one of {sorted(INTERVAL_SECONDS)}")
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    df = PROVIDERS[provider](symbol.strip(), interval, limit)
    return df.tail(limit).reset_index(drop=True)


# ---- cached long history, topped up with the latest candles on each call ----
_history: dict[tuple, tuple[float, pd.DataFrame]] = {}
_lock = threading.Lock()
HISTORY_TTL = 3600  # re-download everything this often


def get_history(provider: str, symbol: str, interval: str = "1m", total: int = 5000) -> pd.DataFrame:
    """Up to `total` candles (oldest first). First call downloads them all; later calls only
    fetch the newest 300 and merge, so polling stays cheap."""
    key = (provider, symbol.strip().upper(), interval)
    now = time.time()
    with _lock:
        cached = _history.get(key)
        if cached and now - cached[0] < HISTORY_TTL:
            recent = get_candles(provider, symbol, interval, 300)
            old = cached[1]
            if recent["time"].iloc[0] <= old["time"].iloc[-1]:        # no gap -> merge
                df = pd.concat([old, recent]).drop_duplicates("time", keep="last")
                df = df.sort_values("time").tail(total).reset_index(drop=True)
                _history[key] = (cached[0], df)
                return df
        df = get_candles(provider, symbol, interval, total)
        _history[key] = (now, df)
        return df
