"""Paper trading with Telegram alerts.

Follows the live trade signal (/api/signal of the running dashboard, so the knowledge gate, the rule and the
self-learning model all apply exactly as on the Live page) and, for every new CALL / PUT, takes a PAPER trade and
sends a Telegram message. When the trade ends (target, stop, time limit, market close) it sends the result, and
after the NSE close it sends a daily summary. No real orders are ever placed.

    python app.py                                  # 1. the dashboard must be running
    python paper_telegram.py --find-chat-id        # 2. once: print your chat id (after you message the bot)
    python paper_telegram.py --test                # 3. send a test message
    python paper_telegram.py                       # 4. run (Ctrl+C to stop)
    python paper_telegram.py --dry-run             # same, but print messages instead of sending them

Settings come from `.env` (see `.env.example`) or environment variables:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PAPER_SYMBOLS, PAPER_INTERVAL, PAPER_HORIZON, PAPER_LOGIC, PAPER_POLL,
    PAPER_SUMMARY_AT, PAPER_API

Files: paper_trades/trades.csv (every closed paper trade), paper_trades/state.json (open trades, unsent messages).
Paper trades only. Fees and slippage are not included. Not financial advice.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "paper_trades"
DISCLAIMER = "Paper trade only. Not financial advice."

NAMES = {"^NSEI": "NIFTY 50", "^NSEBANK": "BANK NIFTY", "PAXGUSDT": "24/7 GOLD (PAXG)", "XAUUSD": "24/7 GOLD (XAU/USD)", "GC=F": "GOLD FUTURES"}
EXIT_TEXT = {
    "target": ("✅", "TARGET HIT"),
    "stop": ("❌", "STOP HIT"),
    "timeout": ("⏱", "TIME EXIT"),
    "close": ("🔔", "MARKET CLOSE EXIT"),
    "lost": ("⚠️", "TRADE LOST (data changed)"),
    "replaced": ("♻️", "TRADE REPLACED (settings or data changed, closed at the current price)"),
    "unwatched": ("🔕", "TRADE CLOSED (bot no longer watches this chart, closed at the current price)"),
}
MSG_FIELDS = ["sent_at", "status", "kind", "symbol", "interval", "side", "entry_time", "entry", "stop", "target",
              "exit", "exit_price", "points", "r", "text"]


class Msg(str):
    """A Telegram message text that also knows what it is about (for the sent-messages log)."""
    def __new__(cls, text: str, kind: str, trade: dict | None = None):
        m = super().__new__(cls, text)
        m.kind, m.trade = kind, trade or {}
        return m

    def to_outbox(self, now: float) -> dict:
        t = self.trade
        info = {k: t.get(k) for k in ("symbol", "interval", "side", "entry", "stop", "target", "exit",
                                       "exit_price", "points", "r")}
        info["entry_time"] = ist(t["entry_at"]).strftime("%Y-%m-%d %H:%M") if t.get("entry_at") else None
        return {"text": str(self), "kind": self.kind, "info": info, "created_at": now}


CSV_FIELDS = ["symbol", "provider", "interval", "side", "logic", "entry_time", "entry", "stop", "target",
              "exit", "exit_time", "exit_price", "points", "r", "candles_held", "joined_late"]


# ---------------------------------------------------------------- settings

def load_env(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_symbols(text: str) -> list[tuple[str, str]]:
    """'yahoo:^NSEI, yahoo:^NSEBANK, nse:RELIANCE, binance:BTCUSDT' -> [(provider, symbol), ...]"""
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        provider, _, symbol = part.partition(":") if ":" in part else ("yahoo", "", part)
        out.append((provider.strip().lower(), symbol.strip()))
    return out


def display_name(symbol: str) -> str:
    return NAMES.get(symbol, symbol.removesuffix(".NS"))


def ist(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, IST)


def fmt(x: float) -> str:
    return f"{x:,.2f}"


# ---------------------------------------------------------------- messages

def entry_message(t: dict) -> str:
    arrow = "▲ BUY CALL" if t["side"] == "CALL" else "▼ BUY PUT"
    why = "\n".join(f"• {r}" for r in t.get("reasons", [])[:3]) or "• (no reason given)"
    return (
        "📝 PAPER TRADE TAKEN\n"
        f"{arrow}  |  {display_name(t['symbol'])}  |  {t['interval']}\n\n"
        f"Entry   : {fmt(t['entry'])}\n"
        f"Stop    : {fmt(t['stop'])}  (-{fmt(t['stop_points'])} pts, -1R)\n"
        f"Target  : {fmt(t['target'])}  (+{fmt(t['target_points'])} pts, +{t['rr']:g}R)\n"
        f"Max hold: {t['max_hold']} candles\n\n"
        f"Why:\n{why}\n\n"
        f"Logic: {t['logic'].capitalize()}  |  Mode: {t.get('mode', 'agree').upper()}  |  "
        f"Knowledge gate: {t.get('gate', 'on').upper()}  |  "
        f"{ist(t['entry_at']):%H:%M} IST\n"
        f"{DISCLAIMER}"
    )


def joined_message(t: dict, rec: dict) -> str:
    """A trade that was already running when the bot first saw it (e.g. the bot started late)."""
    trade = rec["trade"]
    pl = float(trade["pl_points"])
    sign = "+" if pl >= 0 else ""
    arrow = "▲ CALL" if t["side"] == "CALL" else "▼ PUT"
    return (
        "📌 RUNNING TRADE (bot joined late)\n"
        f"{arrow}  |  {display_name(t['symbol'])}  |  {t['interval']}\n\n"
        f"Entered : {ist(t['entry_at']):%H:%M} IST at {fmt(t['entry'])}\n"
        f"Stop    : {fmt(t['stop'])}\n"
        f"Target  : {fmt(t['target'])}\n"
        f"Now     : {fmt(float(rec['current_price']))}  ({sign}{fmt(pl)} pts, {sign}{float(trade['pl_r']):.1f}R)\n"
        f"Candles left: {trade['candles_left']}\n\n"
        "Started before the bot, so it is late to enter. Tracked anyway: you will get its exit.\n"
        f"{DISCLAIMER}"
    )


def start_message(cfg) -> str:
    names = ", ".join(display_name(s) for _, s in cfg.symbols)
    return (f"🤖 Paper bot started\nWatching: {names}  |  {cfg.interval}  |  entry {cfg.entry}  |  "
            f"target {cfg.rr:g}x stop  |  knowledge gate {cfg.gate}\nYou will get a message for every paper trade. {DISCLAIMER}")


def exit_message(t: dict) -> str:
    icon, label = EXIT_TEXT.get(t["exit"], ("ℹ️", t["exit"].upper()))
    sign = "+" if t["points"] >= 0 else ""
    return (
        f"{icon} {label}  |  {display_name(t['symbol'])}  {t['side']}\n"
        f"Entry {fmt(t['entry'])} → Exit {fmt(t['exit_price'])}\n"
        f"Result: {sign}{fmt(t['points'])} pts  ({sign}{t['r']:.1f}R)\n"
        f"Held: {t['candles_held']} candles  |  {ist(t['exit_at']):%H:%M} IST"
    )


def summary_message(day: str, trades: list[dict]) -> str:
    if not trades:
        return f"📊 PAPER TRADING SUMMARY  |  {day}\nNo paper trades today.\n{DISCLAIMER}"
    rs = [float(x["r"]) for x in trades]
    wins = sum(r > 0 for r in rs)
    best = max(trades, key=lambda x: float(x["r"]))
    worst = min(trades, key=lambda x: float(x["r"]))
    total = sum(rs)
    return (
        f"📊 PAPER TRADING SUMMARY  |  {day}\n"
        f"Trades: {len(rs)}   Wins: {wins}   Losses: {len(rs) - wins}\n"
        f"Total: {total:+.1f}R   Win rate: {wins / len(rs):.0%}\n"
        f"Best: {display_name(best['symbol'])} {best['side']} {float(best['r']):+.1f}R\n"
        f"Worst: {display_name(worst['symbol'])} {worst['side']} {float(worst['r']):+.1f}R\n"
        f"Fees and slippage not included. {DISCLAIMER}"
    )


# ---------------------------------------------------------------- paper trading logic (no network here)

class PaperTrader:
    """Turns successive /api/signal responses into paper trades and messages.

    A trade is identified by chart + entry candle time, so one signal is never sent twice, even after a restart.
    A fresh signal (state "enter") opens a paper trade. A trade already running when we first see it (bot started
    late) is tracked as well and flagged `joined_late`, with a message saying it is late to enter.
    """

    def __init__(self, state: dict | None = None):
        self.state = state or {}
        self.state.setdefault("open", {})        # key -> paper trade
        self.state.setdefault("seen", [])        # keys of trades already opened (no duplicates)
        self.state.setdefault("outbox", [])      # messages not delivered yet
        self.state.setdefault("last_summary", None)

    @staticmethod
    def key(rec: dict, entry_time: int) -> str:
        return f"{rec['provider']}:{rec['symbol']}:{rec['interval']}:{entry_time}"

    def step(self, rec: dict, now: float) -> tuple[list[str], list[dict]]:
        """Process one signal response. Returns (messages to send, paper trades closed now)."""
        messages, closed = [], []
        chart = f"{rec['provider']}:{rec['symbol']}:{rec['interval']}:"
        trade = rec.get("trade")
        sec = int(rec.get("interval_seconds") or 60)

        # 1. follow the paper trades already open on this chart
        for k, t in list(self.state["open"].items()):
            if not k.startswith(chart):
                continue
            result = self._result(t, rec, trade, now, sec)
            if result:
                t.update(result)
                del self.state["open"][k]
                closed.append(t)
                messages.append(Msg(exit_message(t), "exit", t))

        # 2. a fresh signal -> open a paper trade (never on stale data). A trade that was already running when the
        #    bot first saw it (started late, restarted) is tracked too, but flagged as joined late.
        if trade and rec.get("state") in ("enter", "hold") and not rec.get("stale"):
            k = self.key(rec, trade["entry_time"])
            if k not in self.state["seen"] and k not in self.state["open"]:
                late = rec["state"] == "hold"
                t = {
                    "symbol": rec["symbol"], "provider": rec["provider"], "interval": rec["interval"],
                    "side": trade["side"], "logic": rec.get("logic", "rule"),
                    "entry_time": int(trade["entry_time"]), "entry_at": int(trade["entry_time"]) + sec,
                    "entry": float(trade["entry"]), "stop": float(trade["stop"]), "target": float(trade["target"]),
                    "stop_points": float(trade["stop_points"]), "target_points": float(trade["target_points"]),
                    "rr": float(rec.get("rr", 2.0)), "max_hold": int(trade["max_hold"]),
                    "reasons": list(rec.get("explain") or [])[:3],
                    "gate": (rec.get("knowledge") or {}).get("gate", "on"),
                    "mode": rec.get("entry_mode", "agree"),
                    "joined_late": late,
                }
                self.state["open"][k] = t
                self.state["seen"] = (self.state["seen"] + [k])[-500:]
                messages.append(Msg(joined_message(t, rec), "joined", t) if late else Msg(entry_message(t), "entry", t))
        return messages, closed

    @staticmethod
    def _result(t: dict, rec: dict, trade: dict | None, now: float, sec: int) -> dict | None:
        """How the paper trade `t` ended, or None while it is still running."""
        et = t["entry_time"]
        d = 1 if t["side"] == "CALL" else -1
        # still the running trade: did the live candle touch the stop or the target?
        if trade and int(trade["entry_time"]) == et:
            if trade.get("hit"):
                price = float(trade["stop"] if trade["hit"] == "stop" else trade["target"])
                return _close(t, trade["hit"], price, now, int(trade.get("candles_held", 0)), d)
            return None
        # the engine has finished it on closed candles: take its result
        done = rec.get("last_trade")
        if done and int(done["entry_time"]) == et and done.get("exit_price") is not None:
            held = max(0, round((int(done["exit_time"]) - et) / sec))
            return _close(t, done["exit"], float(done["exit_price"]), int(done["exit_time"]) + sec, held, d)
        for x in rec.get("trades") or []:
            if int(x["entry_time"]) == et:
                price = t["entry"] + d * float(x["points"])
                held = max(0, round((int(x["exit_time"]) - et) / sec))
                return _close(t, x["exit"], price, int(x["exit_time"]) + sec, held, d)
        # the engine now runs a newer trade and this one is not in its history (settings or data changed, e.g.
        # a new target multiple): it no longer exists, close it at the last price
        if trade and int(trade["entry_time"]) > et:
            return _close(t, "replaced", float(rec.get("current_price") or t["entry"]), now,
                          max(0, round((now - t["entry_at"]) / sec)), d)
        # nowhere to be found long after it should have ended (feed history changed): close it at the last price
        if now - t["entry_at"] > 3 * t["max_hold"] * sec:
            return _close(t, "lost", float(rec.get("current_price") or t["entry"]), now, t["max_hold"], d)
        return None

    def orphans(self, watched: set[tuple[str, str, str]]) -> list[str]:
        """Keys of open trades on charts the bot no longer watches (e.g. after changing PAPER_INTERVAL)."""
        return [k for k, t in self.state["open"].items()
                if (t["provider"], t["symbol"], t["interval"]) not in watched]

    def close_orphan(self, k: str, rec: dict, now: float) -> tuple[list[str], list[dict]]:
        """Settle an orphan with one last look at its chart: its real exit if it has one, else the current price."""
        msgs, closed = self.step(rec, now)
        t = self.state["open"].pop(k, None)
        if t:
            d = 1 if t["side"] == "CALL" else -1
            sec = int(rec.get("interval_seconds") or 60)
            t.update(_close(t, "unwatched", float(rec.get("current_price") or t["entry"]), now,
                            max(0, round((now - t["entry_at"]) / sec)), d))
            closed.append(t)
            msgs.append(Msg(exit_message(t), "exit", t))
        return msgs, closed

    def summary_due(self, now: float, at: str) -> str | None:
        """The IST date whose summary should be sent now (once a day, weekdays, after `at` HH:MM), else None."""
        n = ist(now)
        day = n.strftime("%Y-%m-%d")
        if n.weekday() >= 5 or n.strftime("%H:%M") < at or self.state["last_summary"] == day:
            return None
        return day


def _close(t: dict, kind: str, price: float, at: float, held: int, d: int) -> dict:
    pts = (price - t["entry"]) * d
    risk = t["stop_points"] or 1e-9
    return {"exit": kind, "exit_price": float(price), "exit_at": int(at), "points": float(pts),
            "r": float(pts / risk), "candles_held": int(held)}


# ---------------------------------------------------------------- files

def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def append_trades(path: Path, trades: list[dict]) -> None:
    if not trades:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        for t in trades:
            row = {k: t.get(k) for k in CSV_FIELDS}
            row["entry_time"] = ist(t["entry_at"]).strftime("%Y-%m-%d %H:%M")
            row["exit_time"] = ist(t["exit_at"]).strftime("%Y-%m-%d %H:%M")
            for k in ("entry", "stop", "target", "exit_price", "points"):
                row[k] = round(float(row[k]), 2)
            row["r"] = round(float(row["r"]), 2)
            w.writerow(row)


def log_message(path: Path, m: dict, sent_at: float, status: str) -> None:
    """One row per Telegram message delivered: when, what kind, which trade, and the full text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    row = {k: None for k in MSG_FIELDS}
    row.update({k: v for k, v in (m.get("info") or {}).items() if k in MSG_FIELDS})
    for k in ("entry", "stop", "target", "exit_price", "points", "r"):
        if row[k] is not None:
            row[k] = round(float(row[k]), 2)
    row.update(sent_at=ist(sent_at).strftime("%Y-%m-%d %H:%M:%S"), status=status, kind=m.get("kind"),
               text=m.get("text", ""))
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MSG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def report(out_dir: Path = OUT_DIR) -> str:
    """Plain-text track record: every closed paper trade, totals, open trades, messages sent."""
    lines = ["PAPER TRADING RECORD", ""]
    trades = []
    if (out_dir / "trades.csv").exists():
        with (out_dir / "trades.csv").open(encoding="utf-8") as f:
            trades = list(csv.DictReader(f))
    if trades:
        lines.append(f"{'Entry':16} {'Symbol':10} {'Side':4} {'Entry px':>10} {'Exit px':>10} {'Exit':8} "
                     f"{'Pts':>8} {'R':>6}  Late")
        for t in trades:
            lines.append(f"{t['entry_time']:16} {display_name(t['symbol'])[:10]:10} {t['side']:4} "
                         f"{float(t['entry']):>10.2f} {float(t['exit_price']):>10.2f} {t['exit']:8} "
                         f"{float(t['points']):>+8.2f} {float(t['r']):>+6.2f}  "
                         f"{'yes' if t.get('joined_late') == 'True' else ''}")
        rs = [float(t["r"]) for t in trades]
        wins = sum(r > 0 for r in rs)
        own = [float(t["r"]) for t in trades if t.get("joined_late") != "True"]
        lines += ["", f"Closed trades: {len(rs)}   Wins: {wins}   Losses: {len(rs) - wins}   "
                      f"Win rate: {wins / len(rs):.0%}",
                  f"Total: {sum(rs):+.2f}R ({sum(float(t['points']) for t in trades):+.2f} pts)   "
                  f"Average: {sum(rs) / len(rs):+.2f}R per trade",
                  f"Without joined-late trades: {len(own)} trades, {sum(own):+.2f}R"]
    else:
        lines.append("No closed paper trades yet.")
    state = load_state(out_dir / "state.json")
    for t in (state.get("open") or {}).values():
        lines.append(f"OPEN: {display_name(t['symbol'])} {t['side']} since {ist(t['entry_at']):%Y-%m-%d %H:%M} "
                     f"at {t['entry']:.2f} (stop {t['stop']:.2f}, target {t['target']:.2f})")
    if (out_dir / "messages.csv").exists():
        with (out_dir / "messages.csv").open(encoding="utf-8") as f:
            msgs = list(csv.DictReader(f))
        kinds = {}
        for m in msgs:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
        lines.append(f"Messages sent: {len(msgs)} ({', '.join(f'{k} {v}' for k, v in kinds.items())}); "
                     f"last at {msgs[-1]['sent_at'] if msgs else '-'}")
    if state.get("outbox"):
        lines.append(f"Waiting to be sent: {len(state['outbox'])}")
    lines += ["", "Fees and slippage not included. " + DISCLAIMER]
    return "\n".join(lines)


def trades_on(path: Path, day: str) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("exit_time") or "").startswith(day)]


# ---------------------------------------------------------------- Telegram

class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False):
        self.token, self.chat_id, self.dry_run = token, chat_id, dry_run

    def send(self, text: str) -> bool:
        if self.dry_run:
            print("\n----- TELEGRAM (dry run) -----\n" + text + "\n------------------------------")
            return True
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                              json={"chat_id": self.chat_id, "text": text}, timeout=15)
            if r.ok:
                return True
            print(f"[telegram] failed: HTTP {r.status_code} {r.text[:200]}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"[telegram] failed: {e}", file=sys.stderr)
        return False


def find_chat_id(token: str) -> None:
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
    data = r.json()
    if not data.get("ok"):
        sys.exit(f"Telegram says: {data.get('description', r.text[:200])}. Check TELEGRAM_BOT_TOKEN.")
    chats = {}
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = msg.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username") or ""
    if not chats:
        print("No messages found. Open your bot in Telegram, press Start (or send 'hi'), then run this again.")
        return
    for cid, name in chats.items():
        print(f"TELEGRAM_CHAT_ID={cid}    ({name})")


# ---------------------------------------------------------------- main loop

def fetch_signal(api: str, provider: str, symbol: str, interval: str, horizon: int, logic: str,
                 gate: str = "off", entry: str = "always", rr: float = 1.5) -> dict:
    r = requests.get(f"{api}/api/signal", timeout=120, params={
        "provider": provider, "symbol": symbol, "interval": interval, "horizon": horizon, "logic": logic,
        "gate": gate, "entry": entry, "rr": rr})
    rec = r.json()
    if not r.ok:
        raise RuntimeError(rec.get("error", f"HTTP {r.status_code}"))
    return rec


def run(cfg: argparse.Namespace) -> None:
    tg = Telegram(cfg.token, cfg.chat_id, cfg.dry_run)
    state_path, csv_path, msg_path = OUT_DIR / "state.json", OUT_DIR / "trades.csv", OUT_DIR / "messages.csv"
    pt = PaperTrader(load_state(state_path))
    pt.state["outbox"] = [m if isinstance(m, dict) else Msg(m, "other").to_outbox(time.time())
                          for m in pt.state["outbox"]]                    # older state files stored plain text
    pt.state["outbox"].append(Msg(start_message(cfg), "start").to_outbox(time.time()))
    watched = {(p, s, cfg.interval) for p, s in cfg.symbols}
    for k in pt.orphans(watched):                     # trades left open on a chart we no longer watch
        t = pt.state["open"][k]
        try:
            rec = fetch_signal(cfg.api, t["provider"], t["symbol"], t["interval"], cfg.horizon, cfg.logic,
                               cfg.gate, cfg.entry, cfg.rr)
        except Exception as e:                        # noqa: BLE001 - retried at the next start
            print(f"Could not close the old {t['side']} on {display_name(t['symbol'])} {t['interval']}: {e}")
            continue
        msgs, closed = pt.close_orphan(k, rec, time.time())
        append_trades(csv_path, closed)
        pt.state["outbox"].extend(m.to_outbox(time.time()) for m in msgs)
    names = ", ".join(f"{display_name(s)} ({p})" for p, s in cfg.symbols)
    print(f"Paper trading {names} | {cfg.interval} | look-ahead {cfg.horizon} | logic {cfg.logic} | "
          f"knowledge gate {cfg.gate} | entry {cfg.entry} | target {cfg.rr:g}x stop | poll {cfg.poll}s | {'DRY RUN' if cfg.dry_run else 'sending to Telegram'}. Ctrl+C to stop.")
    last_wait = {}
    while True:
        for provider, symbol in cfg.symbols:
            try:
                rec = fetch_signal(cfg.api, provider, symbol, cfg.interval, cfg.horizon, cfg.logic, cfg.gate,
                                   cfg.entry, cfg.rr)
            except requests.ConnectionError:
                print(f"[{ist(time.time()):%H:%M:%S}] dashboard not reachable at {cfg.api}. Is `python app.py` running?")
                break
            except Exception as e:                           # noqa: BLE001 - keep the loop alive
                print(f"[{ist(time.time()):%H:%M:%S}] {display_name(symbol)}: {e}")
                continue
            msgs, closed = pt.step(rec, time.time())
            append_trades(csv_path, closed)
            pt.state["outbox"].extend(m.to_outbox(time.time()) for m in msgs)
            status = rec.get("action") if rec.get("trade") else f"WAIT: {rec.get('wait_reason') or ''}"
            if rec.get("stale"):
                status = "MARKET CLOSED / feed stale"
            if msgs or last_wait.get(symbol) != status:
                print(f"[{ist(time.time()):%H:%M:%S}] {display_name(symbol)}: {status}")
                last_wait[symbol] = status
        day = pt.summary_due(time.time(), cfg.summary_at)
        if day:
            pt.state["outbox"].append(Msg(summary_message(day, trades_on(csv_path, day)), "summary").to_outbox(time.time()))
            pt.state["last_summary"] = day
        while pt.state["outbox"] and tg.send(pt.state["outbox"][0]["text"]):   # unsent ones are retried next loop
            log_message(msg_path, pt.state["outbox"].pop(0), time.time(), "dry-run" if cfg.dry_run else "sent")
        save_state(state_path, pt.state)
        time.sleep(cfg.poll)


_bot_thread: threading.Thread | None = None
_bot_running: bool = False


def bot_status() -> dict:
    """Return status dictionary of the background bot for APIs and monitoring."""
    load_env()
    token_set = bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip())
    chat_set = bool(os.environ.get("TELEGRAM_CHAT_ID", "").strip())
    return {
        "running": _bot_running,
        "configured": token_set and chat_set,
        "symbols": os.environ.get("PAPER_SYMBOLS", "binance:XAUUSD"),
        "interval": os.environ.get("PAPER_INTERVAL", "1m"),
        "logic": os.environ.get("PAPER_LOGIC", "auto"),
    }


def start_bot_thread(api_url: str = "http://127.0.0.1:5000", dry_run: bool = False) -> threading.Thread | None:
    """Run paper trading Telegram bot in a daemon thread alongside the Flask server."""
    global _bot_thread, _bot_running
    if _bot_running:
        return _bot_thread
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[Telegram Bot] Skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env")
        return None

    def worker():
        global _bot_running
        _bot_running = True
        time.sleep(2)
        cfg = argparse.Namespace(
            symbols=parse_symbols(os.environ.get("PAPER_SYMBOLS", "binance:XAUUSD")),
            interval=os.environ.get("PAPER_INTERVAL", "1m"),
            horizon=int(os.environ.get("PAPER_HORIZON", "5")),
            logic=os.environ.get("PAPER_LOGIC", "auto"),
            gate=os.environ.get("PAPER_GATE", "off"),
            entry=os.environ.get("PAPER_ENTRY", "always"),
            rr=float(os.environ.get("PAPER_RR", "1.5")),
            poll=int(os.environ.get("PAPER_POLL", "15")),
            summary_at=os.environ.get("PAPER_SUMMARY_AT", "15:35"),
            api=api_url,
            dry_run=dry_run,
            token=token,
            chat_id=chat_id,
        )
        try:
            run(cfg)
        except Exception as e:
            print(f"[Telegram Bot] Stopped: {e}")
        finally:
            _bot_running = False

    t = threading.Thread(target=worker, daemon=True, name="TelegramPaperBot")
    t.start()
    _bot_thread = t
    print(f"[Telegram Bot] Started in background daemon thread (symbols={os.environ.get('PAPER_SYMBOLS', 'binance:XAUUSD')}, interval={os.environ.get('PAPER_INTERVAL', '1m')})")
    return t


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):              # Windows consoles default to cp1252: emojis would crash
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    load_env()
    e = os.environ.get
    p = argparse.ArgumentParser(description="Paper trading with Telegram alerts (no real orders).")
    p.add_argument("--symbols", default=e("PAPER_SYMBOLS", "yahoo:^NSEI"),
                   help="comma list of provider:symbol, e.g. yahoo:^NSEI,nse:RELIANCE,binance:BTCUSDT")
    p.add_argument("--interval", default=e("PAPER_INTERVAL", "5m"))
    p.add_argument("--horizon", type=int, default=int(e("PAPER_HORIZON", "5")))
    p.add_argument("--logic", default=e("PAPER_LOGIC", "auto"), choices=["auto", "rule", "model"])
    p.add_argument("--gate", default=e("PAPER_GATE", "off"), choices=["off", "on"],
                   help="off = use every coded pattern (Hammer, Inverted Hammer...), on = only approved knowledge")
    p.add_argument("--entry", default=e("PAPER_ENTRY", "always"), choices=["always", "agree"],
                   help="always = never WAIT, CALL or PUT by the blended score; agree = trend and patterns must agree")
    p.add_argument("--rr", type=float, default=float(e("PAPER_RR", "1.5")),
                   help="target as a multiple of the stop distance (Live page default is 2)")
    p.add_argument("--poll", type=int, default=int(e("PAPER_POLL", "15")), help="seconds between checks")
    p.add_argument("--summary-at", default=e("PAPER_SUMMARY_AT", "15:35"), help="daily summary time, HH:MM IST")
    p.add_argument("--api", default=e("PAPER_API", "http://127.0.0.1:5000"))
    p.add_argument("--dry-run", action="store_true", help="print messages instead of sending them")
    p.add_argument("--test", action="store_true", help="send one test message and exit")
    p.add_argument("--report", action="store_true", help="print the record of paper trades and messages, then exit")
    p.add_argument("--find-chat-id", action="store_true", help="print the chat id of whoever messaged the bot")
    cfg = p.parse_args(argv)
    cfg.token, cfg.chat_id = e("TELEGRAM_BOT_TOKEN", ""), e("TELEGRAM_CHAT_ID", "")
    cfg.symbols = parse_symbols(cfg.symbols)
    if cfg.report:
        return print(report())

    if not cfg.dry_run and not cfg.token:
        sys.exit("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and fill it in (or use --dry-run).")
    if cfg.find_chat_id:
        return find_chat_id(cfg.token)
    if not cfg.dry_run and not cfg.chat_id:
        sys.exit("TELEGRAM_CHAT_ID is missing. Run: python paper_telegram.py --find-chat-id")
    if cfg.test:
        ok = Telegram(cfg.token, cfg.chat_id, cfg.dry_run).send(
            "✅ Paper trading bot is connected.\nYou will get a message for every paper trade. " + DISCLAIMER)
        sys.exit(0 if ok else 1)
    try:
        run(cfg)
    except KeyboardInterrupt:
        print("\nStopped. Open paper trades are kept in paper_trades/state.json and resume next time.")


if __name__ == "__main__":
    main()
