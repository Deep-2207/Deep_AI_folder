// Run: node --test tests/drawings.test.js
const test = require('node:test');
const assert = require('node:assert/strict');

// ---- minimal browser stubs ----
const handlers = { box: {}, win: {} };
const store = new Map();
globalThis.localStorage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) };
globalThis.addEventListener = (t, f) => { handlers.win[t] = f; };
globalThis.requestAnimationFrame = () => 0;
globalThis.devicePixelRatio = 1;
globalThis.confirm = () => true;
const createDrawings = require('../static/drawings.js');

// logical index L -> x = 100 + 10L ; price p -> y = 1000 - 5p
const ts = {
  logicalToCoordinate: L => 100 + L * 10,
  coordinateToLogical: x => (x - 100) / 10,
  height: () => 28,
};
const series = { priceToCoordinate: p => 1000 - p * 5, coordinateToPrice: y => (1000 - y) / 5 };
const chart = { timeScale: () => ts, priceScale: () => ({ width: () => 60 }) };
const ctxStub = new Proxy({}, { get: (_, k) => (k === 'measureText' ? () => ({ width: 50 }) : () => {}), set: () => true });

const STEP = 60, T0 = 1_700_000_000;
const candle = (i, o, h, l, c) => ({ time: T0 + i * STEP, open: o, high: h, low: l, close: c, volume: 1 });
const flat = n => Array.from({ length: n }, (_, i) => candle(i, 100, 100.5, 99.5, 100));

let keyN = 0;
function setup(candles = flat(50), key = `test|${keyN++}`) {
  Object.keys(handlers.box).forEach(k => delete handlers.box[k]);
  const box = {
    dataset: {}, clientWidth: 1000, clientHeight: 800,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 1000, bottom: 800, width: 1000, height: 800 }),
    addEventListener: (t, f) => { handlers.box[t] = f; },
  };
  const canvas = { width: 0, height: 0, getContext: () => ctxStub };
  const events = { change: 0, tool: [] };
  const dr = createDrawings({ chart, series, box, canvas, onChange: () => events.change++, onTool: t => events.tool.push(t) });
  dr.setData(candles, STEP, key);
  return { dr, box, events };
}
const ev = (x, y) => ({ button: 0, clientX: x, clientY: y, stopPropagation() {}, preventDefault() {} });
const xy = (L, price) => [100 + L * 10, 1000 - price * 5];
const click = (L, price) => { const [x, y] = xy(L, price); handlers.box.mousedown(ev(x, y)); handlers.win.mouseup(ev(x, y)); };

test('time <-> logical mapping, including the future', () => {
  const { dr } = setup();
  const { toL, toT } = dr._t;
  assert.equal(toL(T0), 0);
  assert.equal(toL(T0 + 30), 0.5);
  assert.equal(toL(T0 + 49 * STEP + 5 * STEP), 54);       // 5 candles after the last one
  assert.equal(toT(54), T0 + 54 * STEP);
  assert.equal(toT(toL(T0 + 1234)), T0 + 1234);
});

test('long box: target, stop, open P/L, pending', () => {
  const mk = (type, extra) => ({ id: 'a', type, t0: T0 + 10 * STEP + 1, w: 20 * STEP, entry: 100, stop: type === 'long' ? 98 : 102, target: type === 'long' ? 104 : 96, ...extra });
  const base = flat(30);

  let { dr } = setup(base.map((c, i) => (i === 15 ? candle(i, 100, 104.2, 99.8, 103) : c)));
  assert.equal(dr._t.evalPos(mk('long')).state, 'target');
  assert.equal(dr._t.evalPos(mk('long')).pl, 4);

  ({ dr } = setup(base.map((c, i) => (i === 15 ? candle(i, 100, 100.4, 97.5, 98) : c))));
  assert.deepEqual([dr._t.evalPos(mk('long')).state, dr._t.evalPos(mk('long')).pl], ['stop', -2]);

  // stop and target both inside one candle -> conservative: stopped out
  ({ dr } = setup(base.map((c, i) => (i === 15 ? candle(i, 100, 105, 97, 100) : c))));
  assert.equal(dr._t.evalPos(mk('long')).state, 'stop');

  // short mirrors it
  ({ dr } = setup(base.map((c, i) => (i === 15 ? candle(i, 100, 100.2, 95.5, 96.5) : c))));
  assert.equal(dr._t.evalPos(mk('short')).state, 'target');

  // still open: P/L is last close vs entry, sign flips for short
  ({ dr } = setup(base.map((c, i) => (i === 29 ? candle(i, 100, 101.5, 99.9, 101) : c))));
  assert.equal(dr._t.evalPos(mk('long')).pl, 1);
  assert.equal(dr._t.evalPos(mk('short')).pl, -1);

  // entry in the future -> pending, and candles at/before entry never count
  assert.equal(dr._t.evalPos(mk('long', { t0: T0 + 40 * STEP })).state, 'pending');
  ({ dr } = setup(base.map((c, i) => (i === 10 ? candle(i, 100, 110, 90, 100) : c))));
  assert.equal(dr._t.evalPos(mk('long', { t0: T0 + 10 * STEP })).state, 'open');
});

test('CALL tool: one click creates entry / stop below / target above, then returns to cursor', () => {
  const { dr, events } = setup();
  dr.setTool('long');
  click(20, 100);
  const [it] = dr._t.items();
  assert.equal(it.type, 'long');
  assert.ok(Math.abs(it.entry - 100) < 1e-9);
  assert.ok(it.stop < it.entry && it.target > it.entry);
  assert.ok(Math.abs((it.target - it.entry) - 2 * (it.entry - it.stop)) < 1e-9, 'default R:R is 2');
  assert.equal(dr.getTool(), 'cursor');
  assert.equal(dr.summary()[0].selected, true);
  assert.ok(events.change > 0);
});

test('PUT tool mirrors: stop above, target below', () => {
  const { dr } = setup();
  dr.setTool('short');
  click(20, 100);
  const [it] = dr._t.items();
  assert.ok(it.stop > it.entry && it.target < it.entry);
});

test('dragging handles edits the box; target/stop cannot cross the entry', () => {
  const { dr } = setup();
  dr.setTool('long');
  click(20, 100);
  const it = dr._t.items()[0];
  const x0 = 100 + 20 * 10, x1 = 100 + (20 + it.w / STEP) * 10, xm = (x0 + x1) / 2;

  // drag the target handle up to price 110
  handlers.box.mousedown(ev(xm, 1000 - it.target * 5));
  handlers.win.mousemove(ev(xm, 1000 - 110 * 5));
  handlers.win.mouseup(ev(xm, 1000 - 110 * 5));
  assert.ok(Math.abs(it.target - 110) < 1e-9);

  // drag the stop handle ABOVE the entry -> clamped just below it
  const stopY = 1000 - it.stop * 5;
  handlers.box.mousedown(ev(xm, stopY));
  handlers.win.mousemove(ev(xm, 1000 - 105 * 5));
  handlers.win.mouseup(ev(xm, 1000 - 105 * 5));
  assert.ok(it.stop < it.entry);

  // drag right edge: widen to 40 candles
  handlers.box.mousedown(ev(x1, 1000 - it.entry * 5));
  handlers.win.mousemove(ev(100 + 60 * 10, 1000 - it.entry * 5));
  handlers.win.mouseup(ev(100 + 60 * 10, 1000 - it.entry * 5));
  assert.ok(Math.abs(it.w / STEP - 40) < 1e-6);
});

test('dragging the body moves the whole box by the same time and price', () => {
  const { dr } = setup();
  dr.setTool('long');
  click(20, 100);
  const it = dr._t.items()[0];
  const before = { ...it };
  const mid = [100 + 25 * 10, 1000 - (before.entry + 1) * 5];
  handlers.box.mousedown(ev(...mid));
  handlers.win.mousemove(ev(mid[0] + 50, mid[1] - 25));      // +5 candles, +5 price
  handlers.win.mouseup(ev(mid[0] + 50, mid[1] - 25));
  assert.ok(Math.abs(it.entry - (before.entry + 5)) < 1e-9);
  assert.ok(Math.abs(it.target - (before.target + 5)) < 1e-9);
  assert.ok(Math.abs(it.stop - (before.stop + 5)) < 1e-9);
  assert.ok(Math.abs(it.t0 - (before.t0 + 5 * STEP)) < 1e-6);
  assert.equal(it.w, before.w);
});

test('lock prevents dragging', () => {
  const { dr } = setup();
  dr.setTool('long'); click(20, 100);
  const it = dr._t.items()[0], before = { ...it };
  dr.toggleLock();
  const mid = [100 + 25 * 10, 1000 - (before.entry + 1) * 5];
  handlers.box.mousedown(ev(...mid));
  handlers.win.mousemove(ev(mid[0] + 50, mid[1] - 25));
  handlers.win.mouseup(ev(mid[0] + 50, mid[1] - 25));
  assert.equal(it.entry, before.entry);
});

test('trend line: click-click and press-drag both work; ruler is not saved', () => {
  const { dr } = setup();
  dr.setTool('trend');
  click(5, 99);                                  // first click
  const [x, y] = xy(15, 101);
  handlers.win.mousemove(ev(x, y));
  handlers.box.mousedown(ev(x, y));              // second click finishes
  handlers.win.mouseup(ev(x, y));
  assert.equal(dr._t.items().length, 1);

  dr.setTool('trend');
  const [ax, ay] = xy(5, 98), [bx, by] = xy(30, 103);
  handlers.box.mousedown(ev(ax, ay));            // press-drag-release
  handlers.win.mousemove(ev(bx, by));
  handlers.win.mouseup(ev(bx, by));
  assert.equal(dr._t.items().length, 2);

  dr.setTool('measure');
  click(5, 99); click(15, 101);
  assert.equal(dr._t.items().length, 2);
});

test('horizontal line, hide/delete, delete-selected-or-all', () => {
  const { dr } = setup();
  dr.setTool('hline'); click(10, 101);
  assert.equal(dr._t.items()[0].type, 'hline');
  dr.setTool('long'); click(20, 100);
  assert.equal(dr.summary().length, 1);
  dr.deleteSelectedOrAll();                      // box is selected -> removes only it
  assert.equal(dr._t.items().length, 1);
  dr.select(null);
  dr.deleteSelectedOrAll();                      // nothing selected -> clears all
  assert.equal(dr._t.items().length, 0);
});

test('box from prediction and persistence per symbol', () => {
  let { dr } = setup(flat(50), 'persist|A');
  const it = dr.addFromPrediction({ direction: 'DOWN', pattern_time: T0 + 40 * STEP, entry_price: 100, target_price: 96, horizon: 5 });
  assert.equal(it.type, 'short');
  assert.equal(it.target, 96);
  assert.equal(it.stop, 102);                    // risk = half the reward
  assert.equal(it.w, 5 * STEP);
  assert.equal(dr.addFromPrediction({ direction: 'SIDEWAYS' }), null);

  ({ dr } = setup(flat(50), 'persist|A'));       // fresh page load, same symbol
  assert.equal(dr._t.items().length, 1);
  dr.setData(flat(50), STEP, 'persist|B');       // other symbol starts empty
  assert.equal(dr._t.items().length, 0);
});

test('box stops at its right edge: TIME UP with P/L at the last candle inside', () => {
  const candles = flat(40).map((c, i) => (i === 35 ? candle(i, 100, 110, 90, 100) : i === 30 ? candle(i, 100, 101.2, 99.8, 101) : c));
  const { dr } = setup(candles);
  const box = { id: 'b', type: 'long', t0: T0 + 10 * STEP, w: 20 * STEP, entry: 100, stop: 98, target: 104 };
  const ev = dr._t.evalPos(box);
  assert.equal(ev.state, 'timeout');            // the wild candle (index 35) comes after the box ends (index 30)
  assert.equal(ev.idx, 30);
  assert.equal(ev.pl, 1);
});

test('signal boxes are replaced, the user\'s own boxes are kept', () => {
  const { dr } = setup();
  dr.setTool('long'); click(20, 100);
  dr.addTrade({ type: 'short', t0: T0 + 30 * STEP, entry: 100, stop: 101, target: 98, w: 10 * STEP, auto: true });
  assert.equal(dr._t.items().length, 2);
  dr.removeAuto();
  assert.deepEqual(dr._t.items().map(i => i.type), ['long']);
});

test('fractional bar positions are interpolated (the real chart returns 0 for them)', () => {
  const real = ts.logicalToCoordinate;
  ts.logicalToCoordinate = L => (Number.isInteger(L) ? 100 + L * 10 : 0);
  try {
    const { dr } = setup();
    dr.addTrade({ type: 'long', t0: T0 + 20.5 * STEP, entry: 100, stop: 99, target: 102, w: 10 * STEP });
    const y = 1000 - 100.5 * 5;                     // inside the box vertically
    assert.equal(dr._t.hitTest(150, y), null);      // left of the box (x would wrongly start at 0)
    assert.equal(dr._t.hitTest(350, y).part, 'body'); // box spans x = 305..405
  } finally {
    ts.logicalToCoordinate = real;
  }
});
