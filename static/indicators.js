/* Chart indicators for lightweight-charts (TradingView-style "Indicators" dialog + legend).

   - Indicators button opens a searchable list; click one to add it to the chart (you can add the same one
     several times, e.g. EMA 9 and EMA 21).
   - Each indicator gets a legend row on the top-left of the chart: name, settings, value under the crosshair,
     and buttons to hide, edit (gear) or remove it.
   - Settings are saved in the browser, so they stay across refresh, symbols and timeframes.

   To add a new indicator, add an entry to TYPES (name, keywords, defaults, fields, compute, label). */
(function (root) {
  'use strict';

  const SOURCES = {
    close: c => c.close, open: c => c.open, high: c => c.high, low: c => c.low,
    hl2: c => (c.high + c.low) / 2, hlc3: c => (c.high + c.low + c.close) / 3,
    ohlc4: c => (c.open + c.high + c.low + c.close) / 4,
  };
  const PALETTE = ['#f0b429', '#4c8dff', '#e040fb', '#26c6da', '#ff7043', '#9ccc65'];

  /* Exponential moving average, same as TradingView's ta.ema: alpha = 2 / (length + 1), seeded with the
     simple average of the first `length` values. Values before that are null (not enough data yet). */
  function ema(values, length) {
    const out = new Array(values.length).fill(null);
    length = Math.floor(length);
    if (!(length >= 1) || values.length < length) return out;
    const a = 2 / (length + 1);
    let prev = 0;
    for (let i = 0; i < length; i++) prev += values[i];
    prev /= length;
    out[length - 1] = prev;
    for (let i = length; i < values.length; i++) {
      prev = a * values[i] + (1 - a) * prev;
      out[i] = prev;
    }
    return out;
  }

  const TYPES = {
    ema: {
      name: 'Moving Average Exponential',
      keywords: 'ema exponential moving average ma trend',
      defaults: { length: 20, source: 'close', width: 2 },
      fields: [
        { key: 'length', label: 'Length', type: 'int', min: 1, max: 1000 },
        { key: 'source', label: 'Source', type: 'select', options: Object.keys(SOURCES) },
      ],
      compute: (candles, p) => ema(candles.map(SOURCES[p.source] || SOURCES.close), p.length),
      label: p => `EMA ${p.length} ${p.source}`,
    },
  };

  const esc = s => String(s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const uid = () => Math.random().toString(36).slice(2, 10);
  const isColor = c => typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c);

  /* Make a saved/edited indicator safe: known type, numbers in range, source from the list. */
  function sanitize(it, i) {
    const T = it && TYPES[it.type];
    if (!T) return null;
    const out = { id: typeof it.id === 'string' ? it.id.slice(0, 20) : uid(), type: it.type, hidden: !!it.hidden };
    for (const f of T.fields) {
      let v = it[f.key];
      if (f.type === 'int') {
        v = Math.round(Number(v));
        if (!Number.isFinite(v)) v = T.defaults[f.key];
        v = Math.min(f.max, Math.max(f.min, v));
      } else if (f.type === 'select' && !f.options.includes(v)) v = T.defaults[f.key];
      out[f.key] = v;
    }
    out.width = Math.min(4, Math.max(1, Math.round(Number(it.width)) || T.defaults.width));
    out.color = isColor(it.color) ? it.color : PALETTE[(i || 0) % PALETTE.length];
    return out;
  }

  /* Search the indicator list: every word typed must appear in the name or keywords. */
  function search(q) {
    const words = String(q || '').toLowerCase().split(/\s+/).filter(Boolean);
    return Object.entries(TYPES)
      .filter(([k, T]) => words.every(w => `${k} ${T.name} ${T.keywords}`.toLowerCase().includes(w)))
      .map(([k]) => k);
  }

  function highlight(name, q) {
    const w = String(q || '').trim().split(/\s+/)[0];
    const i = w ? name.toLowerCase().indexOf(w.toLowerCase()) : -1;
    if (i < 0) return esc(name);
    return esc(name.slice(0, i)) + '<mark>' + esc(name.slice(i, i + w.length)) + '</mark>' + esc(name.slice(i + w.length));
  }

  function createIndicators(opts) {
    const { chart, legend, button, storageKey = 'indicators-v1' } = opts;
    const fmt = opts.format || (v => v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) >= 1 ? 2 : 4 }));
    const store = {
      get() { try { return JSON.parse(root.localStorage.getItem(storageKey)) || []; } catch (e) { return []; } },
      set(v) { try { root.localStorage.setItem(storageKey, JSON.stringify(v)); } catch (e) { /* storage blocked */ } },
    };

    let items = store.get().map(sanitize).filter(Boolean);
    const lines = new Map();          // id -> line series
    const values = new Map();         // id -> Map(time -> value), for the crosshair legend
    let candles = [], tzShift = 0, editing = null, hoverTime = null, modal = null;

    const save = () => store.set(items);

    function seriesFor(it) {
      let s = lines.get(it.id);
      if (!s) {
        s = chart.addLineSeries({ priceLineVisible: false, crosshairMarkerVisible: false, lastValueVisible: true });
        lines.set(it.id, s);
      }
      s.applyOptions({ color: it.color, lineWidth: it.width, visible: !it.hidden });
      return s;
    }

    function computeOne(it) {
      const s = seriesFor(it);
      const v = TYPES[it.type].compute(candles, it);
      const data = [], byTime = new Map();
      candles.forEach((c, i) => {
        if (v[i] == null || !Number.isFinite(v[i])) return;
        const t = c.time + tzShift;
        data.push({ time: t, value: v[i] });
        byTime.set(t, v[i]);
      });
      s.setData(data);
      values.set(it.id, byTime);
    }

    function recomputeAll() { items.forEach(computeOne); renderLegend(); }

    function valueText(it) {
      const m = values.get(it.id);
      if (!m || !m.size) return '<span class="ind-na">needs more candles</span>';
      let v = hoverTime != null ? m.get(hoverTime) : undefined;
      if (v === undefined) v = hoverTime != null ? null : [...m.values()].pop();
      return v == null ? '-' : esc(fmt(v));
    }

    function renderLegend() {
      if (!legend) return;
      legend.innerHTML = items.map(it => {
        const T = TYPES[it.type];
        const row = `<div class="ind-row${it.hidden ? ' off' : ''}" data-id="${esc(it.id)}">
          <i style="background:${it.color}"></i>
          <span class="ind-name">${esc(T.label(it))}</span>
          <b class="ind-val" style="color:${it.color}">${valueText(it)}</b>
          <span class="ind-btns">
            <button data-act="hide" title="${it.hidden ? 'Show' : 'Hide'}">${it.hidden ? '&#9711;' : '&#9673;'}</button>
            <button data-act="edit" title="Settings">&#9881;</button>
            <button data-act="del" title="Remove">&times;</button>
          </span></div>`;
        return editing === it.id ? row + settingsForm(it) : row;
      }).join('');
      legend.style.display = items.length ? '' : 'none';
    }

    function settingsForm(it) {
      const T = TYPES[it.type];
      const fields = T.fields.map(f => f.type === 'select'
        ? `<label>${esc(f.label)} <select data-f="${f.key}">${f.options.map(o => `<option${o === it[f.key] ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select></label>`
        : `<label>${esc(f.label)} <input data-f="${f.key}" type="number" min="${f.min}" max="${f.max}" step="1" value="${it[f.key]}"></label>`).join('');
      return `<div class="ind-form" data-id="${esc(it.id)}">${fields}
        <label>Color <input data-f="color" type="color" value="${it.color}"></label>
        <label>Width <select data-f="width">${[1, 2, 3, 4].map(w => `<option${w === it.width ? ' selected' : ''}>${w}</option>`).join('')}</select></label>
        <button data-act="done">Done</button></div>`;
    }

    function update(id, patch) {
      const i = items.findIndex(x => x.id === id);
      if (i < 0) return;
      const it = sanitize({ ...items[i], ...patch }, i);
      items[i] = it; save(); computeOne(it);
    }

    function add(type, params) {
      if (!TYPES[type]) return null;
      const it = sanitize({ id: uid(), type, ...TYPES[type].defaults, ...params }, items.length);
      // pick a colour no other indicator uses yet
      if (!params || !params.color) it.color = PALETTE.find(c => !items.some(x => x.color === c)) || it.color;
      items.push(it); save(); computeOne(it); renderLegend();
      return it;
    }

    function remove(id) {
      const s = lines.get(id);
      if (s) { chart.removeSeries(s); lines.delete(id); }
      values.delete(id);
      items = items.filter(x => x.id !== id);
      if (editing === id) editing = null;
      save(); renderLegend();
    }

    // ---- legend events ----
    if (legend) {
      legend.addEventListener('click', e => {
        const btn = e.target.closest('button[data-act]');
        if (!btn) return;
        const id = btn.closest('[data-id]').dataset.id, act = btn.dataset.act;
        const it = items.find(x => x.id === id);
        if (!it) return;
        if (act === 'hide') update(id, { hidden: !it.hidden });
        else if (act === 'edit') editing = editing === id ? null : id;
        else if (act === 'done') editing = null;
        else if (act === 'del') { remove(id); return; }
        renderLegend();
      });
      const onField = e => {
        const el = e.target.closest('[data-f]');
        if (!el) return;
        const id = el.closest('[data-id]').dataset.id, f = el.dataset.f;
        if (f === 'length' && el.value === '') return;          // still typing
        update(id, { [f]: el.value });
        // refresh the label/value text without rebuilding the form (keeps focus in the input)
        const it = items.find(x => x.id === id), row = legend.querySelector(`.ind-row[data-id="${id}"]`);
        if (it && row) {
          row.querySelector('.ind-name').textContent = TYPES[it.type].label(it);
          row.querySelector('i').style.background = it.color;
          const val = row.querySelector('.ind-val');
          val.style.color = it.color; val.innerHTML = valueText(it);
        }
      };
      legend.addEventListener('input', onField);
      legend.addEventListener('change', e => { onField(e); renderLegend(); });
    }

    if (chart.subscribeCrosshairMove) {
      chart.subscribeCrosshairMove(p => {
        const t = p && p.time != null ? p.time : null;
        if (t === hoverTime) return;
        hoverTime = t;
        if (!legend) return;
        items.forEach(it => {
          const el = legend.querySelector(`.ind-row[data-id="${it.id}"] .ind-val`);
          if (el) el.innerHTML = valueText(it);
        });
      });
    }

    // ---- the "Indicators" dialog ----
    function openDialog() {
      if (modal) { modal.querySelector('input').focus(); return; }
      modal = root.document.createElement('div');
      modal.className = 'ind-modal';
      modal.innerHTML = `<div class="ind-box" role="dialog" aria-label="Indicators">
        <div class="ind-head"><b>Indicators</b><button data-close title="Close (Esc)">&times;</button></div>
        <input type="search" placeholder="Search, e.g. ema or exponential" aria-label="Search indicators">
        <div class="ind-cap">SCRIPT NAME</div>
        <div class="ind-list"></div></div>`;
      root.document.body.appendChild(modal);
      const input = modal.querySelector('input'), list = modal.querySelector('.ind-list');
      const draw = () => {
        const found = search(input.value);
        list.innerHTML = found.length
          ? found.map((k, i) => `<div class="ind-item${i === 0 ? ' sel' : ''}" data-type="${k}">${highlight(TYPES[k].name, input.value)}</div>`).join('')
          : '<div class="ind-none">No indicator found</div>';
      };
      const close = () => { if (modal) { modal.remove(); modal = null; } };
      const pick = type => { add(type); close(); };
      input.addEventListener('input', draw);
      input.addEventListener('keydown', e => {
        if (e.key === 'Escape') close();
        else if (e.key === 'Enter') { const s = list.querySelector('.ind-item'); if (s) pick(s.dataset.type); }
      });
      modal.addEventListener('mousedown', e => { if (e.target === modal) close(); });
      modal.querySelector('[data-close]').onclick = close;
      list.addEventListener('click', e => { const it = e.target.closest('.ind-item'); if (it) pick(it.dataset.type); });
      draw();
      input.focus();
    }
    if (button) button.addEventListener('click', openDialog);

    renderLegend();

    return {
      /* Call with the chart's candles whenever they change. tz = seconds added to each candle time
         (the same shift used for the candlestick series). */
      setData(cs, tz) { candles = cs || []; tzShift = tz || 0; recomputeAll(); },
      add, remove, update, openDialog,
      list: () => items.map(x => ({ ...x })),
      valueAt(id, time) { const m = values.get(id); return m ? m.get(time) : undefined; },
    };
  }

  createIndicators.ema = ema;
  createIndicators.TYPES = TYPES;
  createIndicators._t = { sanitize, search, highlight };
  root.createIndicators = createIndicators;
  if (typeof module !== 'undefined') module.exports = createIndicators;
})(typeof window !== 'undefined' ? window : globalThis);
