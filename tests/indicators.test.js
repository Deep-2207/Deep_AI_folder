// Run: node --test tests/indicators.test.js
const test = require('node:test');
const assert = require('node:assert/strict');

const store = new Map();
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
const createIndicators = require('../static/indicators.js');
const { ema } = createIndicators;
const { sanitize, search, highlight } = createIndicators._t;

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);

test('ema: seeded with the simple average, then alpha = 2/(n+1)', () => {
  const v = ema([1, 2, 3, 4, 5, 6], 3);
  assert.deepEqual(v.slice(0, 2), [null, null]);
  close(v[2], 2);                    // (1+2+3)/3
  close(v[3], 0.5 * 4 + 0.5 * 2);    // alpha = 0.5 -> 3
  close(v[4], 0.5 * 5 + 0.5 * 3);    // 4
  close(v[5], 0.5 * 6 + 0.5 * 4);    // 5
});

test('ema: constant input stays constant, length 1 equals the input', () => {
  ema(Array(50).fill(7), 20).slice(19).forEach(x => close(x, 7));
  assert.deepEqual(ema([3, 1, 4, 1, 5], 1), [3, 1, 4, 1, 5]);
});

test('ema: not enough candles -> all null, bad length -> all null', () => {
  assert.deepEqual(ema([1, 2], 5), [null, null]);
  assert.deepEqual(ema([1, 2], 0), [null, null]);
});

test('ema: no look-ahead (changing later values never changes earlier ones)', () => {
  const a = Array.from({ length: 100 }, (_, i) => 100 + Math.sin(i / 3) * 5);
  const b = a.slice(); for (let i = 60; i < 100; i++) b[i] += 50;
  const ea = ema(a, 20), eb = ema(b, 20);
  for (let i = 0; i < 60; i++) assert.equal(ea[i], eb[i]);
});

test('sanitize: clamps length, rejects unknown source/type/colour', () => {
  assert.equal(sanitize({ type: 'nope' }), null);
  const s = sanitize({ type: 'ema', length: 99999, source: '<script>', color: 'red;x', width: 9 }, 0);
  assert.equal(s.length, 1000);
  assert.equal(s.source, 'close');
  assert.match(s.color, /^#[0-9a-f]{6}$/i);
  assert.equal(s.width, 4);
  assert.equal(sanitize({ type: 'ema', length: 'abc' }).length, 20);
});

test('search: "expo", "ema" and "moving average" all find EMA; junk finds nothing', () => {
  for (const q of ['expo', 'EMA', 'moving average', '', 'exponential ma']) assert.deepEqual(search(q), ['ema'], q);
  assert.deepEqual(search('zzz'), []);
  assert.equal(highlight('Moving Average Exponential', 'expo'), 'Moving Average <mark>Expo</mark>nential');
});

test('createIndicators: add, compute on candles (with tz), update, hide, remove, saved', () => {
  const added = [], removed = [];
  const chart = {
    addLineSeries() { const s = { opts: {}, data: null, applyOptions(o) { Object.assign(this.opts, o); }, setData(d) { this.data = d; } }; added.push(s); return s; },
    removeSeries(s) { removed.push(s); },
  };
  const candles = Array.from({ length: 30 }, (_, i) => ({ time: 1000 + i * 60, open: i, high: i + 1, low: i - 1, close: i }));
  const ind = createIndicators({ chart, storageKey: 'k1' });
  ind.setData(candles, 3600);
  const it = ind.add('ema', { length: 10 });
  const s = added[0];
  assert.equal(s.data.length, 21);                       // first value on candle 10
  assert.equal(s.data[0].time, 1000 + 9 * 60 + 3600);
  close(s.data[0].value, 4.5);                           // average of 0..9
  assert.equal(JSON.parse(store.get('k1'))[0].length, 10);

  ind.update(it.id, { length: '5', source: 'high' });
  assert.equal(s.data.length, 26);
  close(s.data[0].value, 3);                             // average of highs 1..5
  ind.update(it.id, { hidden: true });
  assert.equal(s.opts.visible, false);

  const second = ind.add('ema');
  assert.notEqual(second.color, it.color);               // a different colour per line
  ind.remove(it.id);
  assert.deepEqual(removed, [s]);
  assert.deepEqual(ind.list().map(x => x.id), [second.id]);

  // reload from storage
  const again = createIndicators({ chart, storageKey: 'k1' });
  assert.deepEqual(again.list().map(x => x.length), [20]);
});
