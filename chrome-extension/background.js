// Every minute: show the trade signal on the toolbar badge and, if alerts are on, notify when a new CALL/PUT
// trade starts or when a trade ends (target, stop or time limit) on the watched symbol.
importScripts('common.js');

const BADGE_COLOR = { call: '#26a69a', put: '#ef5350', wait: '#c99a1f', closed: '#8b95a3' };

const setup = () => {
  chrome.alarms.create('scan', { periodInMinutes: 1 });
  check();
};
chrome.runtime.onInstalled.addListener(setup);
chrome.runtime.onStartup.addListener(setup);
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'scan') check(); });
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === 'check') { check().then(() => reply(true)); return true; }
  return false;
});
chrome.notifications.onClicked.addListener(id => {
  chrome.notifications.clear(id);
  openPage(id.includes('nse_replay|') || id.includes('seeder|') ? '/test' : '/');
});

async function check() {
  const s = await getSettings();
  try {
    const sig = await api('/api/signal', signalParams(s));
    setBadge(s, sig);
    await maybeNotify(s, sig);
  } catch (e) {
    chrome.action.setBadgeText({ text: '!' });
    chrome.action.setBadgeBackgroundColor({ color: '#8b95a3' });
    chrome.action.setTitle({ title: 'Pattern Scanner: server not reachable at 127.0.0.1:5000 (run python app.py)' });
  }
}

function setBadge(s, sig) {
  const h = headline(sig);
  chrome.action.setBadgeText({ text: h.badge });
  chrome.action.setBadgeBackgroundColor({ color: BADGE_COLOR[h.cls] });
  const t = sig.trade;
  chrome.action.setTitle({
    title: `${s.symbol} ${s.interval}: ${h.text}` + (t ? ` | entry ${fmt(t.entry)}, stop ${fmt(t.stop)}, target ${fmt(t.target)}` : ''),
  });
}

async function maybeNotify(s, sig) {
  const prefix = `${s.provider}|${s.symbol}|${s.interval}|`;
  const t = sig.trade, lt = sig.last_trade;
  const tradeKey = t ? `${prefix}${t.side}|${t.entry_time}` : '';
  const exitKey = lt ? `${prefix}${lt.side}|${lt.entry_time}|${lt.exit}` : '';
  const { seen } = await chrome.storage.local.get('seen');
  await chrome.storage.local.set({ seen: { tradeKey, exitKey, prefix } });
  // first check, or the watched symbol just changed: remember the state but don't alert on old news
  if (!s.alerts || sig.stale || !seen || seen.prefix !== prefix) return;

  if (t && tradeKey !== seen.tradeKey) {
    const late = t.candles_held > 0 ? ` (signal was ${t.candles_held} candle${t.candles_held === 1 ? '' : 's'} ago: don't chase if price ran away)` : '';
    chrome.notifications.create(`${tradeKey}|new`, {
      type: 'basic', iconUrl: 'icons/icon128.png', priority: 2,
      title: `${ARROW[t.side]} BUY ${t.side} NOW: ${s.symbol} ${s.interval}`,
      message: `Entry ${fmt(t.entry)}, stop-loss ${fmt(t.stop)}, target ${fmt(t.target)}${late}.`,
    });
  }
  if (lt && exitKey !== seen.exitKey) {
    const how = { target: 'target hit', stop: 'stop-loss hit', timeout: 'time limit reached', close: 'squared off at the market close' }[lt.exit];
    chrome.notifications.create(`${exitKey}|exit`, {
      type: 'basic', iconUrl: 'icons/icon128.png', priority: 1,
      title: `${lt.side} trade closed: ${s.symbol} ${s.interval}`,
      message: `${how}: ${signed(lt.points)} pts. Wait for the next signal.`,
    });
  }
}
