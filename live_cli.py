"""Terminal live scanner: latest pattern + predicted move in points, from how it played out before.

  python -u live_cli.py                                   # BTCUSDT 1m from Binance
  python -u live_cli.py --provider yahoo --symbol AAPL
  python -u live_cli.py --provider yahoo --symbol RELIANCE.NS --poll 15 --horizon 10
"""
import argparse
import time
from datetime import datetime

from stockpatterns.feeds import INTERVAL_SECONDS, FeedError, get_history
from stockpatterns.patterns import detect, predict

HISTORY_CANDLES = 5000


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--provider", default="binance", choices=["binance", "yahoo"])
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="1m", choices=sorted(INTERVAL_SECONDS))
    ap.add_argument("--poll", type=float, default=5.0, help="seconds between feed requests")
    ap.add_argument("--horizon", type=int, default=5, help="candles to look ahead")
    ap.add_argument("--forming", action="store_true", help="also use the still-open candle (may disappear)")
    a = ap.parse_args()

    sec = INTERVAL_SECONDS[a.interval]
    shown = None
    print(f"Watching {a.symbol} {a.interval} via {a.provider} (Ctrl+C to stop)")
    while True:
        try:
            df = get_history(a.provider, a.symbol, a.interval, HISTORY_CANDLES)
        except FeedError as e:
            print(f"feed error: {e}")
            time.sleep(max(a.poll, 5))
            continue
        except ValueError as e:
            raise SystemExit(str(e))

        forming = time.time() < int(df["time"].iloc[-1]) + sec
        data = df.iloc[:-1] if forming and not a.forming else df
        pred = predict(data, detect(data), a.horizon)
        if pred and (pred["pattern_time"], pred["pattern"]) != shown:
            shown = (pred["pattern_time"], pred["pattern"])
            ts = datetime.fromtimestamp(pred["pattern_time"]).strftime("%H:%M")
            e = pred["entry_price"]
            if pred["samples"]:
                hist = (f"{pred['up_pct']:.0%} rose / {pred['down_pct']:.0%} fell in {pred['samples']} past cases "
                        f"(market overall {pred['baseline_up_pct']:.0%} rose), edge: {pred['edge']}")
            else:
                hist = "no earlier cases"
            print(f"{ts}  {pred['pattern']}  ->  {pred['direction']} {pred['expected_move']:+.2f} pts in "
                  f"{pred['horizon']} candles (range {pred['range_low_price'] - e:+.2f} to {pred['range_high_price'] - e:+.2f})")
            print(f"         {hist} [{pred['basis']}]")
        time.sleep(a.poll)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
