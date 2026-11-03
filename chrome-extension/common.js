// Shared by popup.js and background.js: settings, calls to the local Flask server, and the signal wording.
const SERVER = 'http://127.0.0.1:5000';
const DEFAULTS = { provider: 'yahoo', symbol: 'PLTR', interval: '1m', horizon: 5, alerts: false, logic: 'auto' };
const DEFAULT_SYMBOL = { yahoo: 'PLTR', nse: 'SBIN', binance: 'BTCUSDT', nse_replay: 'RELIANCE', seeder: 'SEEDED' };
const ARROW = { UP: '▲', DOWN: '▼', SIDEWAYS: '–', CALL: '▲', PUT: '▼' };

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULTS, ...(settings || {}) };
}

async function saveSettings(s) {
  await chrome.storage.local.set({ settings: s });
}

async function api(path, params) {
  const r = await fetch(`${SERVER}${path}?${new URLSearchParams(params)}`);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

// logic: auto = the fixed rule until the self-learning model has proven itself, then the model
const signalParams = s => ({ provider: s.provider, symbol: s.symbol, interval: s.interval, horizon: s.horizon,
  logic: s.logic || 'auto' });

const fmt = v => v == null ? '-' : v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) >= 1 ? 2 : 4 });
const signed = v => v == null ? '-' : (v >= 0 ? '+' : '') + fmt(v);

/** One line that says what to do, same wording as the web page. */
function headline(sig) {
  const t = sig.trade;
  if (sig.stale) return { cls: 'closed', text: 'MARKET CLOSED', badge: 'OFF' };
  if (!t) return { cls: 'wait', text: 'WAIT: NO TRADE', badge: 'WAIT' };
  if (sig.state === 'exit') {
    return t.hit === 'target'
      ? { cls: 'call', text: `✓ EXIT ${t.side}: TARGET HIT`, badge: '✓' }
      : { cls: 'put', text: `✗ EXIT ${t.side}: STOP HIT`, badge: '✗' };
  }
  const cls = t.side === 'CALL' ? 'call' : 'put';
  if (sig.state === 'enter') return { cls, text: `${ARROW[t.side]} BUY ${t.side} NOW`, badge: t.side };
  return { cls, text: `${ARROW[t.side]} IN ${t.side}: HOLD`, badge: t.side };
}

/** Focus an open tab of the local app (any page) or open `path`. */
async function openPage(path) {
  const url = SERVER + path;
  const [tab] = await chrome.tabs.query({ url: url.split('?')[0] });
  if (tab) {
    await chrome.tabs.update(tab.id, { active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
  } else {
    await chrome.tabs.create({ url });
  }
}
