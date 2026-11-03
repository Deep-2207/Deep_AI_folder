// Run: node --test tests/extension_background.test.js
// Loads chrome-extension/background.js with a fake chrome API and fake /api/signal replies.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dir = path.join(__dirname, '..', 'chrome-extension');

function load() {
  const store = {}, calls = { badge: [], notes: [], titles: [] };
  const ev = () => ({ addListener() {} });
  const chrome = {
    storage: { local: { get: async k => ({ [k]: store[k] }), set: async o => Object.assign(store, o) } },
    alarms: { create() {}, onAlarm: ev() },
    runtime: { onInstalled: ev(), onStartup: ev(), onMessage: ev() },
    notifications: { create: (id, o) => calls.notes.push({ id, ...o }), onClicked: ev(), clear() {} },
    action: { setBadgeText: o => calls.badge.push(o.text), setBadgeBackgroundColor() {}, setTitle: o => calls.titles.push(o.title) },
    tabs: {}, windows: {},
  };
  const ctx = { chrome, console, URLSearchParams, reply: null };
  ctx.fetch = async () => {
    if (ctx.reply instanceof Error) throw ctx.reply;
    return { ok: true, json: async () => ctx.reply };
  };
  ctx.importScripts = f => vm.runInContext(fs.readFileSync(path.join(dir, f), 'utf8'), ctx);
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(dir, 'background.js'), 'utf8') + '\n;globalThis.check = check;', ctx);
  return { ctx, store, calls };
}

const trade = (side, t, extra = {}) => ({ side, entry_time: t, entry: 100, stop: side === 'CALL' ? 99 : 101,
  target: side === 'CALL' ? 102 : 98, candles_held: 0, candles_left: 20, ...extra });
const sig = (state, t = null, last = null, stale = false) => ({ state, trade: t, last_trade: last, stale });

test('badge follows the trade state', async () => {
  const { ctx, store, calls } = load();
  store.settings = { provider: 'yahoo', symbol: 'PLTR', interval: '1m', horizon: 5, alerts: false };
  for (const [reply, badge] of [
    [sig('wait'), 'WAIT'],
    [sig('enter', trade('CALL', 1)), 'CALL'],
    [sig('hold', trade('PUT', 1, { candles_held: 2 })), 'PUT'],
    [sig('exit', trade('CALL', 1, { hit: 'target' })), '✓'],
    [sig('exit', trade('CALL', 1, { hit: 'stop' })), '✗'],
    [sig('wait', null, null, true), 'OFF'],
  ]) {
    ctx.reply = reply;
    await ctx.check();
    assert.equal(calls.badge.at(-1), badge);
  }
  ctx.reply = new Error('Failed to fetch');
  await ctx.check();
  assert.equal(calls.badge.at(-1), '!');
  assert.match(calls.titles.at(-1), /not reachable/);
});

test('alerts for a new trade and for its exit, never for old news', async () => {
  const { ctx, store, calls } = load();
  store.settings = { provider: 'yahoo', symbol: 'PLTR', interval: '1m', horizon: 5, alerts: true };
  ctx.reply = sig('hold', trade('CALL', 1));
  await ctx.check();
  assert.equal(calls.notes.length, 0, 'first check only remembers');

  ctx.reply = sig('hold', trade('CALL', 1));
  await ctx.check();
  assert.equal(calls.notes.length, 0, 'same trade: no alert');

  const last = { side: 'CALL', entry_time: 1, exit: 'target', points: 2 };
  ctx.reply = sig('enter', trade('PUT', 5), last);
  await ctx.check();
  assert.equal(calls.notes.length, 2, 'new PUT trade + the CALL exit');
  assert.match(calls.notes[0].title, /BUY PUT NOW: PLTR 1m/);
  assert.match(calls.notes[0].message, /Entry 100, stop-loss 101, target 98/);
  assert.match(calls.notes[1].message, /target hit: \+2 pts/);

  ctx.reply = sig('hold', trade('PUT', 5, { candles_held: 1 }), last);
  await ctx.check();
  assert.equal(calls.notes.length, 2, 'nothing new');

  store.settings = { ...store.settings, symbol: 'AMD' };
  ctx.reply = sig('enter', trade('CALL', 9));
  await ctx.check();
  assert.equal(calls.notes.length, 2, 'symbol switch: no alert on old news');

  ctx.reply = sig('enter', trade('CALL', 12), null, true);
  await ctx.check();
  assert.equal(calls.notes.length, 2, 'market closed: no alert');

  store.settings = { ...store.settings, alerts: false };
  ctx.reply = sig('enter', trade('PUT', 20));
  await ctx.check();
  assert.equal(calls.notes.length, 2, 'alerts off');
});

test('a signal found late says so', async () => {
  const { ctx, store, calls } = load();
  store.settings = { provider: 'nse', symbol: 'SBIN', interval: '1m', horizon: 5, alerts: true };
  ctx.reply = sig('wait');
  await ctx.check();
  ctx.reply = sig('hold', trade('CALL', 7, { candles_held: 2 }));
  await ctx.check();
  assert.equal(calls.notes.length, 1);
  assert.match(calls.notes[0].message, /2 candles ago: don't chase/);
});
