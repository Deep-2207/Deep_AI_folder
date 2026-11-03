const $ = id => document.getElementById(id);
let S = null;

async function init() {
  S = await getSettings();
  $('provider').value = S.provider;
  $('symbol').value = S.symbol;
  $('interval').value = S.interval;
  $('horizon').value = String(S.horizon);
  $('alerts').checked = S.alerts;
  refresh();
  setInterval(refresh, 15000);
}

async function changed() {
  S = { ...S, provider: $('provider').value, symbol: $('symbol').value.trim().toUpperCase() || DEFAULT_SYMBOL[$('provider').value],
    interval: $('interval').value, horizon: +$('horizon').value, alerts: $('alerts').checked };
  await saveSettings(S);
  $('main').innerHTML = '<div class="note muted">Loading the trade signal...</div>';
  refresh();
  chrome.runtime.sendMessage('check').catch(() => {});      // update the toolbar badge too
}

function offline(msg) {
  $('dot').className = 'dot off';
  $('main').innerHTML = `<div class="err"><b>Can't reach the scanner.</b> ${msg}</div>
    <div class="note muted small">Start it in a terminal:<br><code>cd D:\\Deep_AI\\StockMarketProject</code><br><code>python app.py</code></div>`;
}

const chip = v => `<span class="chip ${v}">${ARROW[v] || ({ BULLISH: '\u25B2', BEARISH: '\u25BC' }[v] || '\u2013')} ${v}</span>`;
const rr = v => v == null ? '-' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}R`;

function modelLine(s) {
  const m = s.model;
  if (!m) return '';
  const rm = m.record.model;
  const state = m.phase === 'learning' ? `learning (${m.lessons}/${m.lessons_needed} lessons)`
    : `version ${m.version}, ${rm.trades} paper trades, ${rr(rm.avg_r)} per trade, ${m.gate.promoted ? '<b class="UP">proven</b>' : 'not proven yet'}`;
  return `<div class="note small">Signal by: ${s.logic === 'model' ? '<b>self-learning model</b>' : 'fixed rule'}.
    Model: ${state}${m.busy ? ' (training...)' : ''}.</div>`;
}

async function refresh() {
  let s;
  try {
    s = await api('/api/signal', signalParams(S));
  } catch (e) {
    return offline(e.message === 'Failed to fetch' ? 'Is the server running?' : e.message);
  }
  $('dot').className = 'dot on';
  const h = headline(s), t = s.trade, v = s.votes;
  let line;
  if (s.stale) line = 'Not live: this is the last session. Don\'t trade on it; use the Test Lab or an open market.';
  else if (!t) line = s.wait_reason;
  else if (s.state === 'enter') line = `New signal on the last candle: the rule expects price to go <b>${t.side === 'CALL' ? 'UP' : 'DOWN'}</b>. Enter now.`;
  else if (s.state === 'hold') line = `Entered ${t.candles_held} candle(s) ago at ${fmt(t.entry)}; now <b class="${t.pl_points >= 0 ? 'UP' : 'DOWN'}">${signed(t.pl_points)} pts</b>. Not in it? Don't chase.`;
  else line = t.hit === 'target' ? `Take the profit (about ${signed(t.target_points)} pts).` : `Stop-loss reached (about -${fmt(t.stop_points)} pts). Close it.`;

  const b = s.backtest;
  const verdict = b.trades < 20 ? 'too few trades to judge'
    : b.profit_factor == null || b.profit_factor >= 1.2 ? '<span class="UP">made money before</span>'
    : b.profit_factor >= 0.95 ? '<span style="color:var(--warn)">about break-even before</span>'
    : '<span class="DOWN">LOST money before: practice only</span>';
  const lt = s.last_trade;

  $('main').innerHTML = `
    <div class="banner ${h.cls}">
      <div class="head">${h.text}</div>
      <div class="line">${line}</div>
      <div class="small muted" style="margin-top:4px">${s.symbol} ${s.interval} · price ${fmt(s.current_price)} · ${new Date().toLocaleTimeString()}</div>
    </div>
    ${t ? `<div class="levels">
      <div><small>Entry</small><b>${fmt(t.entry)}</b></div>
      <div><small>Stop-loss</small><b class="DOWN">${fmt(t.stop)}</b><small>risk ${fmt(t.stop_points)}</small></div>
      <div><small>Target</small><b class="UP">${fmt(t.target)}</b><small>gain ${fmt(t.target_points)}</small></div>
    </div>
    <div class="note small muted">Exit at stop, target, after ${t.candles_left} more candles, or at the market close.</div>` : ''}
    <div class="votes">
      <span class="muted">Trend</span>${chip(v.trend)}<span class="muted small">${s.explain[0].replace(/^Trend [A-Z]+: /, '')}</span>
      <span class="muted">Patterns</span>${chip(v.pattern)}<span class="muted small">${(s.explain[1] || '').replace(/^Patterns [A-Z]+: /, '')}</span>
    </div>
    <div class="note small muted">${s.logic === 'model'
      ? `The self-learning model is in charge: <b class="UP">CALL</b> / <b class="DOWN">PUT</b> when it expects more than ${rr(s.model.edge)}, otherwise WAIT. Trend and Patterns are the rule's view.`
      : '<b class="UP">CALL</b> needs Trend UP + Patterns BULLISH. <b class="DOWN">PUT</b> needs Trend DOWN + Patterns BEARISH. Otherwise WAIT.'}</div>
    ${modelLine(s)}
    ${lt ? `<div class="note small">Last trade: ${lt.side} &rarr; <b class="${lt.points > 0 ? 'UP' : 'DOWN'}">${({ target: 'target hit', stop: 'stop hit', timeout: 'time limit', close: 'market close' })[lt.exit]} ${signed(lt.points)} pts</b></div>` : ''}
    <div class="note small">Track record here: ${b.trades} trades, ${b.win_rate == null ? '-' : Math.round(b.win_rate * 100) + '%'} won, ${b.total_r >= 0 ? '+' : ''}${b.total_r}R, so the ${s.logic === 'model' ? 'model' : 'rule'} ${verdict}.</div>`;
}

$('provider').onchange = () => { $('symbol').value = DEFAULT_SYMBOL[$('provider').value]; changed(); };
$('symbol').addEventListener('keydown', e => { if (e.key === 'Enter') changed(); });
$('symbol').addEventListener('change', changed);
['interval', 'horizon', 'alerts'].forEach(id => $(id).onchange = changed);
$('refresh').onclick = refresh;
document.querySelectorAll('[data-open]').forEach(b => b.onclick = () => openPage(b.dataset.open));
init();
