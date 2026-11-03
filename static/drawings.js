/* TradingView-style drawing layer for lightweight-charts: CALL/PUT (long/short) boxes with
   entry / stop-loss / target, trend lines, horizontal lines and a ruler.

   Everything is drawn on a <canvas> laid over the chart. Drawings are anchored on (time, price), so they
   survive zoom/pan/live updates and work on any timeframe. X positions go through "logical" bar indexes,
   which (unlike timeToCoordinate) also work for times in the future. */
(function (root) {
  'use strict';

  const COL = { up: '#26a69a', down: '#ef5350', accent: '#4c8dff', grey: '#9aa4b2', text: '#e6edf3', bg: 'rgba(14,17,22,.92)' };
  const rgba = (hex, a) => {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const num = (v, d) => v.toLocaleString(undefined, { maximumFractionDigits: d == null ? (Math.abs(v) >= 1 ? 2 : 4) : d });
  const sgn = v => (v >= 0 ? '+' : '-') + num(Math.abs(v));
  const sgnPct = v => (v >= 0 ? '+' : '-') + Math.abs(v).toFixed(2);
  const dist = (x1, y1, x2, y2) => Math.hypot(x1 - x2, y1 - y2);
  const uid = () => Math.random().toString(36).slice(2, 10);

  function segDist(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
    const t = l2 ? Math.max(0, Math.min(1, ((px - a.x) * dx + (py - a.y) * dy) / l2)) : 0;
    return dist(px, py, a.x + t * dx, a.y + t * dy);
  }

  function createDrawings(opts) {
    const { chart, series, box, canvas } = opts;
    const ctx = canvas.getContext('2d');
    const ts = chart.timeScale();

    let T = [], C = [], step = 60, storeKey = '';
    let items = [];                       // saved drawings
    let tool = 'cursor', magnet = false, locked = false, hidden = false;
    let selected = null;
    let draft = null;                     // trend line / ruler being drawn
    let ruler = null;                     // finished measurement (until next click)
    let drag = null;
    let dirty = true, lastSig = '';
    let clipW = Infinity;                 // visible plot width, set while drawing

    // ---------- time <-> logical index <-> pixels ----------
    const toL = t => {
      const n = T.length;
      if (!n) return 0;
      if (t <= T[0]) return (t - T[0]) / step;
      if (t >= T[n - 1]) return n - 1 + (t - T[n - 1]) / step;
      let lo = 0, hi = n - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; }
      return lo + (t - T[lo]) / (T[hi] - T[lo]);
    };
    const toT = L => {
      const n = T.length;
      if (!n) return 0;
      if (L <= 0) return T[0] + L * step;
      if (L >= n - 1) return T[n - 1] + (L - (n - 1)) * step;
      const i = Math.floor(L);
      return T[i] + (L - i) * (T[i + 1] - T[i]);
    };
    // lightweight-charts only maps whole bar indexes (a fractional one comes back as 0), so interpolate
    const L2X = L => {
      const a = Math.floor(L), f = L - a;
      const xa = ts.logicalToCoordinate(a);
      if (!f || xa == null) return xa;
      const xb = ts.logicalToCoordinate(a + 1);
      return xb == null ? xa : xa + (xb - xa) * f;
    };
    const X = t => L2X(toL(t));
    const Y = p => series.priceToCoordinate(p);
    const pt = p => { const x = X(p.t), y = Y(p.price); return x == null || y == null ? null : { x, y }; };

    function plotSize() {
      const r = box.getBoundingClientRect();
      let pw = 60, th = 28;
      try { pw = chart.priceScale('right').width() || pw; } catch (e) { /* older API */ }
      try { th = ts.height() || th; } catch (e) { /* older API */ }
      return { w: r.width, h: r.height, pw, th };
    }

    function pointer(e) {
      const r = box.getBoundingClientRect();
      const x0 = e.clientX - r.left, y0 = e.clientY - r.top;
      let L = ts.coordinateToLogical(x0);
      let price = series.coordinateToPrice(y0);
      if (L == null || price == null) return null;
      if (magnet && C.length) {
        L = Math.min(C.length - 1, Math.max(0, Math.round(L)));
        const c = C[L];
        let best = null;
        for (const v of [c.open, c.high, c.low, c.close]) {
          const yy = Y(v);
          if (yy != null && Math.abs(yy - y0) < 15 && (!best || Math.abs(yy - y0) < best.d)) best = { v, d: Math.abs(yy - y0) };
        }
        if (best) price = best.v;
      }
      const x = L2X(L), y = Y(price);
      return { x: x == null ? x0 : x, y: y == null ? y0 : y, L, t: toT(L), price, rawX: x0, rawY: y0 };
    }

    // ---------- trade boxes ----------
    const isPos = it => it.type === 'long' || it.type === 'short';

    function atr() {
      const n = Math.min(14, C.length);
      let s = 0;
      for (let i = C.length - n; i < C.length; i++) s += C[i].high - C[i].low;
      return n ? s / n : 1;
    }

    function makePosition(type, t0, entry, o = {}) {
      const dir = type === 'long' ? 1 : -1;
      const risk = o.risk != null ? o.risk : Math.max(2 * atr(), entry * 0.0005);
      return {
        id: uid(), type, t0, w: o.w != null ? o.w : 20 * step, entry,
        stop: o.stop != null ? o.stop : entry - dir * risk,
        target: o.target != null ? o.target : entry + dir * risk * (o.rr || 2),
      };
    }

    /** Where did price go after entry, until the box's right edge (its time limit)?
        Stop is checked first inside a candle (conservative), like the server's backtest. */
    function evalPos(it) {
      const long = it.type === 'long', dir = long ? 1 : -1;
      const risk = Math.abs(it.entry - it.stop), reward = Math.abs(it.target - it.entry);
      const end = it.t0 + it.w;
      let first = 0;
      while (first < T.length && T[first] <= it.t0) first++;       // candles strictly after the entry time
      if (first >= C.length) return { state: 'pending', pl: 0, risk, reward };
      let lastIn = -1;
      for (let i = first; i < C.length && T[i] <= end; i++) {
        const c = C[i];
        lastIn = i;
        if (long ? c.low <= it.stop : c.high >= it.stop) return { state: 'stop', idx: i, pl: -risk, risk, reward };
        if (long ? c.high >= it.target : c.low <= it.target) return { state: 'target', idx: i, pl: reward, risk, reward };
      }
      const after = lastIn < 0 ? first : lastIn + 1;
      if (after < C.length && T[after] > end) {                   // a candle exists past the box: time is up
        return { state: 'timeout', idx: lastIn < 0 ? null : lastIn,
                 pl: lastIn < 0 ? 0 : (C[lastIn].close - it.entry) * dir, risk, reward };
      }
      return { state: 'open', pl: (C[C.length - 1].close - it.entry) * dir, risk, reward };
    }

    function geom(it) {
      const x0 = X(it.t0), x1 = X(it.t0 + it.w), yE = Y(it.entry), yS = Y(it.stop), yT = Y(it.target);
      if ([x0, x1, yE, yS, yT].some(v => v == null)) return null;
      return { x0, x1, xm: (x0 + x1) / 2, yE, yS, yT };
    }
    const handlesOf = g => [
      { part: 'target', x: g.xm, y: g.yT }, { part: 'stop', x: g.xm, y: g.yS }, { part: 'right', x: g.x1, y: g.yE },
    ];

    // ---------- drawing ----------
    function resize() {
      const r = box.getBoundingClientRect();
      const dpr = root.devicePixelRatio || 1;
      const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return r;
    }

    function pill(text, cx, cy, color) {
      ctx.font = '600 12px system-ui, Segoe UI, sans-serif';
      const w = ctx.measureText(text).width + 16, h = 20;
      cx = Math.max(w / 2 + 4, Math.min(cx, clipW - w / 2 - 4));
      const x = cx - w / 2, y = cy - h / 2;
      ctx.fillStyle = COL.bg;
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x, y, w, h, 6); else ctx.rect(x, y, w, h);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = COL.text;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, cx, cy + 0.5);
    }

    function handle(x, y) {
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = COL.accent;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.rect(x - 4, y - 4, 8, 8);
      ctx.fill();
      ctx.stroke();
    }

    function axisTag(price, color, plot) {
      const y = Y(price);
      if (y == null || y < 0 || y > plot.h - plot.th) return;
      ctx.fillStyle = color;
      ctx.fillRect(plot.w - plot.pw, y - 9, plot.pw, 18);
      ctx.fillStyle = '#fff';
      ctx.font = '600 11px system-ui, Segoe UI, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(num(price), plot.w - plot.pw / 2, y + 0.5);
    }

    function drawPosition(it, sel) {
      const g = geom(it);
      if (!g) return;
      const long = it.type === 'long', ev = evalPos(it);
      const hitT = ev.state === 'target', hitS = ev.state === 'stop';
      const x = Math.min(g.x0, g.x1), w = Math.abs(g.x1 - g.x0);

      ctx.fillStyle = rgba(COL.up, hitT ? 0.34 : 0.2);
      ctx.fillRect(x, Math.min(g.yE, g.yT), w, Math.abs(g.yT - g.yE));
      ctx.fillStyle = rgba(COL.down, hitS ? 0.34 : 0.2);
      ctx.fillRect(x, Math.min(g.yE, g.yS), w, Math.abs(g.yS - g.yE));

      const hline = (y, color, lw) => {
        ctx.strokeStyle = color; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.moveTo(g.x0, y); ctx.lineTo(g.x1, y); ctx.stroke();
      };
      hline(g.yT, COL.up, 1.5);
      hline(g.yS, COL.down, 1.5);
      hline(g.yE, COL.grey, 1.5);
      if (sel) {
        ctx.strokeStyle = COL.accent; ctx.lineWidth = 1; ctx.setLineDash([4, 3]);
        ctx.strokeRect(x, Math.min(g.yT, g.yS, g.yE), w, Math.abs(Math.max(g.yT, g.yS, g.yE) - Math.min(g.yT, g.yS, g.yE)));
        ctx.setLineDash([]);
      }

      const tgtMove = it.target - it.entry, stopMove = it.stop - it.entry;
      ctx.font = '600 12px system-ui, Segoe UI, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = COL.text;
      ctx.textBaseline = 'alphabetic';
      const tgtUp = g.yT < g.yE, stopUp = g.yS < g.yE;
      const say = (text, y) => {
        const hw = ctx.measureText(text).width / 2;
        ctx.fillText(text, Math.max(hw + 4, Math.min(g.xm, clipW - hw - 4)), y);
      };
      say(`Target ${sgn(tgtMove)} (${sgnPct(tgtMove / it.entry * 100)}%)`, tgtUp ? g.yT + 16 : g.yT - 6);
      say(`Stop ${sgn(stopMove)} (${sgnPct(stopMove / it.entry * 100)}%)`, stopUp ? g.yS + 16 : g.yS - 6);

      const rr = ev.risk ? ev.reward / ev.risk : 0;
      const status = ev.state === 'target' ? `TARGET HIT ${sgn(ev.pl)}`
        : ev.state === 'stop' ? `STOPPED OUT ${sgn(ev.pl)}`
        : ev.state === 'timeout' ? `TIME UP ${sgn(ev.pl)}`
        : ev.state === 'pending' ? 'waiting for next candle' : `P/L ${sgn(ev.pl)}`;
      const col = ev.state === 'target' ? COL.up : ev.state === 'stop' ? COL.down : ev.pl >= 0 ? COL.up : COL.down;
      pill(`${long ? 'CALL' : 'PUT'}  R:R ${rr.toFixed(2)}  |  ${status}`, g.xm, g.yE, ev.state === 'pending' ? COL.grey : col);

      if (ev.idx != null && (hitT || hitS)) {     // where the box was resolved
        const hx = L2X(ev.idx), hy = Y(hitT ? it.target : it.stop);
        if (hx != null && hy != null) {
          ctx.fillStyle = hitT ? COL.up : COL.down;
          ctx.beginPath(); ctx.arc(hx, hy, 5, 0, Math.PI * 2); ctx.fill();
        }
      }
      if (sel) handlesOf(g).forEach(h => handle(h.x, h.y));
    }

    function drawItem(it, sel) {
      if (isPos(it)) return drawPosition(it, sel);
      if (it.type === 'hline') {
        const y = Y(it.price);
        if (y == null) return;
        ctx.strokeStyle = COL.accent; ctx.lineWidth = sel ? 2 : 1.5;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
        return;
      }
      const a = pt(it.p1), b = pt(it.p2);
      if (!a || !b) return;
      ctx.strokeStyle = COL.accent; ctx.lineWidth = sel ? 2.5 : 2;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      if (sel) { handle(a.x, a.y); handle(b.x, b.y); }
    }

    function drawRuler(m) {
      const a = pt(m.p1), b = pt(m.p2);
      if (!a || !b) return;
      const d = m.p2.price - m.p1.price, up = d >= 0, col = up ? COL.up : COL.down;
      ctx.fillStyle = rgba(col, 0.15); ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.setLineDash([5, 4]);
      ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
      ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
      ctx.setLineDash([]);
      const bars = Math.round(toL(m.p2.t) - toL(m.p1.t)), secs = Math.abs(m.p2.t - m.p1.t);
      const dur = secs >= 86400 ? `${(secs / 86400).toFixed(1)}d` : secs >= 3600 ? `${(secs / 3600).toFixed(1)}h` : `${Math.round(secs / 60)}m`;
      pill(`${sgn(d)} pts (${sgnPct(d / m.p1.price * 100)}%)  |  ${Math.abs(bars)} candles, ${dur}`, (a.x + b.x) / 2, b.y + (up ? -16 : 16), col);
    }

    function draw() {
      const r = resize();
      ctx.clearRect(0, 0, r.width, r.height);
      if (hidden) return;
      const plot = plotSize();
      clipW = plot.w - plot.pw;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, plot.w - plot.pw, plot.h - plot.th); ctx.clip();
      items.forEach(it => drawItem(it, it.id === selected));
      if (draft && draft.type === 'trend') drawItem(draft, true);
      const m = draft && draft.type === 'measure' ? draft : ruler;
      if (m) drawRuler(m);
      ctx.restore();
      items.forEach(it => {                        // price tags on the axis
        if (it.type === 'hline') axisTag(it.price, COL.accent, plot);
        else if (isPos(it) && it.id === selected) {
          axisTag(it.entry, COL.grey, plot); axisTag(it.target, COL.up, plot); axisTag(it.stop, COL.down, plot);
        }
      });
    }

    function frame() {
      const sig = [ts.logicalToCoordinate(0), ts.logicalToCoordinate(100), series.priceToCoordinate(0),
        series.priceToCoordinate(1000), box.clientWidth, box.clientHeight, T.length, T[T.length - 1],
        C.length ? C[C.length - 1].close : 0].join('|');
      if (dirty || sig !== lastSig) { lastSig = sig; dirty = false; draw(); }
      root.requestAnimationFrame(frame);
    }

    // ---------- hit testing ----------
    function hitTest(mx, my) {
      const sel = items.find(i => i.id === selected);
      if (sel && isPos(sel)) {
        const g = geom(sel);
        if (g) for (const h of handlesOf(g)) if (dist(mx, my, h.x, h.y) <= 9) return { id: sel.id, part: h.part };
      }
      if (sel && sel.type === 'trend') {
        const a = pt(sel.p1), b = pt(sel.p2);
        if (a && dist(mx, my, a.x, a.y) <= 9) return { id: sel.id, part: 'p1' };
        if (b && dist(mx, my, b.x, b.y) <= 9) return { id: sel.id, part: 'p2' };
      }
      for (let k = items.length - 1; k >= 0; k--) {
        const it = items[k];
        if (it.type === 'hline') {
          const y = Y(it.price);
          if (y != null && Math.abs(y - my) <= 6) return { id: it.id, part: 'body' };
        } else if (it.type === 'trend') {
          const a = pt(it.p1), b = pt(it.p2);
          if (a && b && segDist(mx, my, a, b) <= 6) return { id: it.id, part: 'body' };
        } else {
          const g = geom(it);
          if (!g) continue;
          const top = Math.min(g.yE, g.yS, g.yT), bot = Math.max(g.yE, g.yS, g.yT);
          if (mx >= Math.min(g.x0, g.x1) && mx <= Math.max(g.x0, g.x1) && my >= top && my <= bot) return { id: it.id, part: 'body' };
        }
      }
      return null;
    }

    // ---------- state changes ----------
    const changed = () => { dirty = true; if (opts.onChange) opts.onChange(); };
    function save() {
      try { localStorage.setItem('drawings|' + storeKey, JSON.stringify(items)); } catch (e) { /* storage blocked */ }
    }
    function load() {
      try { return JSON.parse(localStorage.getItem('drawings|' + storeKey)) || []; } catch (e) { return []; }
    }
    function setTool(t) {
      tool = t; draft = null;
      box.dataset.cursor = t === 'cursor' ? '' : 'crosshair';
      if (opts.onTool) opts.onTool(tool);
      dirty = true;
    }
    function select(id) { if (selected !== id) { selected = id; changed(); } }
    function remove(id) {
      items = items.filter(i => i.id !== id);
      if (selected === id) selected = null;
      save(); changed();
    }
    function deleteSelectedOrAll() {
      if (selected) return remove(selected);
      if (items.length && (!root.confirm || root.confirm('Delete all drawings on this symbol?'))) {
        items = []; ruler = null; save(); changed();
      }
    }
    function finishDraft() {
      if (draft.type === 'trend') { items.push({ id: uid(), type: 'trend', p1: draft.p1, p2: draft.p2 }); save(); }
      else ruler = { p1: draft.p1, p2: draft.p2 };
      draft = null;
      setTool('cursor');
      changed();
    }

    function onDown(e) {
      if (e.button !== 0) return;
      const p = pointer(e);
      const plot = plotSize();
      if (!p || p.rawX > plot.w - plot.pw || p.rawY > plot.h - plot.th) return;      // axes: let the chart handle it
      if (tool !== 'cursor') {
        e.stopPropagation(); e.preventDefault();
        ruler = null;
        if (tool === 'hline') { items.push({ id: uid(), type: 'hline', price: p.price }); save(); setTool('cursor'); changed(); }
        else if (tool === 'long' || tool === 'short') {
          const it = makePosition(tool, p.t, p.price);
          items.push(it); selected = it.id; save(); setTool('cursor'); changed();
        } else if (draft) { draft.p2 = { t: p.t, price: p.price }; finishDraft(); }
        else draft = { type: tool, p1: { t: p.t, price: p.price }, p2: { t: p.t, price: p.price }, downAt: { x: p.rawX, y: p.rawY }, fresh: true };
        return;
      }
      ruler = null; dirty = true;
      if (hidden) return;
      const h = hitTest(p.rawX, p.rawY);
      if (!h) { select(null); return; }
      e.stopPropagation(); e.preventDefault();
      select(h.id);
      if (!locked) drag = { id: h.id, part: h.part, L: p.L, price: p.price, orig: JSON.parse(JSON.stringify(items.find(i => i.id === h.id))) };
    }

    function applyDrag(p) {
      const it = items.find(i => i.id === drag.id), o = drag.orig;
      if (!it) return;
      const dL = p.L - drag.L, dP = p.price - drag.price, shiftT = t => toT(toL(t) + dL);
      if (it.type === 'hline') it.price = o.price + dP;
      else if (it.type === 'trend') {
        if (drag.part === 'p1') it.p1 = { t: p.t, price: p.price };
        else if (drag.part === 'p2') it.p2 = { t: p.t, price: p.price };
        else { it.p1 = { t: shiftT(o.p1.t), price: o.p1.price + dP }; it.p2 = { t: shiftT(o.p2.t), price: o.p2.price + dP }; }
      } else {
        const long = it.type === 'long', tiny = Math.max(o.entry * 1e-6, 1e-9);
        if (drag.part === 'body') { it.t0 = shiftT(o.t0); it.entry = o.entry + dP; it.stop = o.stop + dP; it.target = o.target + dP; }
        else if (drag.part === 'target') it.target = long ? Math.max(it.entry + tiny, p.price) : Math.min(it.entry - tiny, p.price);
        else if (drag.part === 'stop') it.stop = long ? Math.min(it.entry - tiny, p.price) : Math.max(it.entry + tiny, p.price);
        else if (drag.part === 'right') it.w = Math.max(2 * step, toT(p.L) - it.t0);
      }
    }

    const CURSORS = { target: 'ns-resize', stop: 'ns-resize', right: 'ew-resize', p1: 'pointer', p2: 'pointer', body: 'move' };
    function onMove(e) {
      const p = pointer(e);
      if (!p) return;
      if (draft) { draft.p2 = { t: p.t, price: p.price }; dirty = true; return; }
      if (drag) { applyDrag(p); dirty = true; return; }
      if (tool === 'cursor') {
        const r = box.getBoundingClientRect();
        const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
        const h = inside && !hidden ? hitTest(p.rawX, p.rawY) : null;
        box.dataset.cursor = h && !locked ? CURSORS[h.part] : h ? 'pointer' : '';
      }
    }

    function onUp(e) {
      if (draft && draft.fresh) {
        const p = pointer(e);
        if (p && dist(p.rawX, p.rawY, draft.downAt.x, draft.downAt.y) > 6) { draft.p2 = { t: p.t, price: p.price }; finishDraft(); }
        else draft.fresh = false;
      }
      if (drag) { drag = null; save(); changed(); }
    }

    function onKey(e) {
      const tag = (e.target && e.target.tagName) || '';
      if (/INPUT|SELECT|TEXTAREA/.test(tag)) return;
      if (e.key === 'Escape') { ruler = null; draft = null; drag = null; setTool('cursor'); select(null); }
      else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) remove(selected);
    }

    box.addEventListener('mousedown', onDown, true);
    root.addEventListener('mousemove', onMove);
    root.addEventListener('mouseup', onUp);
    root.addEventListener('keydown', onKey);
    root.requestAnimationFrame(frame);

    return {
      /** Feed the latest candles; drawings are stored per `key` (symbol), shared across timeframes. */
      setData(candles, intervalSec, key) {
        C = candles; T = candles.map(c => c.time); step = intervalSec;
        if (key !== storeKey) { storeKey = key; items = load(); selected = null; draft = null; ruler = null; }
        dirty = true;
      },
      setTool,
      getTool: () => tool,
      toggleMagnet() { magnet = !magnet; return magnet; },
      toggleLock() { locked = !locked; return locked; },
      toggleHidden() { hidden = !hidden; dirty = true; return hidden; },
      deleteSelectedOrAll,
      remove, select,
      addFromPrediction(p) {
        if (p.direction === 'SIDEWAYS') return null;
        const type = p.direction === 'UP' ? 'long' : 'short';
        const reward = Math.abs(p.target_price - p.entry_price);
        const dir = type === 'long' ? 1 : -1;
        const it = makePosition(type, p.pattern_time, p.entry_price,
          { target: p.target_price, stop: p.entry_price - dir * reward / 2, w: p.horizon * step });
        items.push(it); selected = it.id; save(); changed();
        return it;
      },
      /** Place a ready-made CALL/PUT box (e.g. from the signal button). */
      addTrade({ type, t0, entry, stop, target, w, auto = false }) {
        const it = makePosition(type, t0, entry, { stop, target, w });
        if (auto) it.auto = true;                  // drawn by the trade signal; replaced when the signal changes
        items.push(it); selected = it.id; save(); changed();
        return it;
      },
      removeAuto() {
        const before = items.length;
        items = items.filter(i => !i.auto);
        if (selected && !items.some(i => i.id === selected)) selected = null;
        if (items.length !== before) { save(); changed(); }
      },
      summary() {
        return items.filter(isPos).map(it => ({ ...it, ...evalPos(it), selected: it.id === selected }));
      },
      // exposed for tests
      _t: { evalPos, hitTest, toL, toT, items: () => items, onDown, onMove, onUp, makePosition },
    };
  }

  root.createDrawings = createDrawings;
  if (typeof module !== 'undefined') module.exports = createDrawings;
})(typeof window !== 'undefined' ? window : globalThis);
