/* NSE Test Lab: turns the dashboard (served at /test) into a replay/simulator page.
   Loaded before the dashboard script, after the page markup. The live page at / is not affected. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);

  document.title = 'NSE Test Lab';
  const nav = document.querySelector('a.navlink[href="/test"]');      // on this page, link back to Live
  if (nav) { nav.href = '/'; nav.textContent = 'Live'; }
  document.querySelector('header h1').innerHTML = 'NSE Test Lab <span style="font-size:11px;color:#f0b429;border:1px solid #f0b429;border-radius:4px;padding:1px 6px;margin-left:6px">REPLAY</span>';

  // data sources
  $('provider').innerHTML = `
    <option value="nse_replay">NSE replay (real past data)</option>
    <option value="seeder">Pattern seeder (synthetic NSE)</option>`;
  window.TEST_DEFAULT_SYMBOL = { nse_replay: 'RELIANCE', seeder: 'SEEDED' };
  $('symbol').value = 'RELIANCE';
  $('symbol').setAttribute('list', 'nse-symbols');
  $('symbol').insertAdjacentHTML('afterend', `<datalist id="nse-symbols">
    ${['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'TMPV', 'ITC', 'LT', 'BHARTIARTL', '^NSEI', '^NSEBANK']
      .map(s => `<option value="${s}">${s === '^NSEI' ? 'NIFTY 50' : s === '^NSEBANK' ? 'BANK NIFTY' : ''}</option>`).join('')}
  </datalist>`);
  $('poll').insertAdjacentHTML('afterbegin', '<option value="1000">every 1s</option>');
  $('poll').value = '1000';

  // replay control bar
  document.querySelector('header').insertAdjacentHTML('afterend', `
  <div id="replaybar" style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:rgba(240,180,41,.06)">
    <button id="rp-play" style="min-width:92px">&#9208; Pause</button>
    <button id="rp-step" class="btn2" title="Pause and show the next candle">&#9197; Next candle</button>
    <select id="rp-speed" title="Replay speed">
      <option value="real">real time</option><option value="6">6 candles/min</option>
      <option value="20" selected>20 candles/min</option><option value="60">60 candles/min</option>
      <option value="180">180 candles/min</option>
    </select>
    <input id="rp-seek" type="range" min="30" max="100" value="50" style="flex:1;min-width:160px" title="Jump in time">
    <span id="rp-time" class="muted" style="font-size:12px;min-width:250px"></span>
    <span id="rp-seedopts" style="display:none;gap:8px;align-items:center">
      <label class="muted" style="font-size:12px">pattern follow-through
        <select id="rp-follow">
          <option value="0.5">50% (no edge)</option><option value="0.7" selected>70%</option>
          <option value="0.85">85%</option><option value="0.95">95%</option>
        </select></label>
    </span>
    <button id="rp-new" class="btn2" title="Seeder: new random data. Replay: start again">&#8635; New data</button>
  </div>
  <div class="muted" style="padding:6px 16px;font-size:12px">
    Test mode: candles are replayed as if live so you can practise when NSE is closed.
    <b>NSE replay</b> plays real past candles (Yahoo, about 7 days of 1m). <b>Pattern seeder</b> plays a random market full
    of textbook patterns; set the follow-through to 50% (patterns mean nothing: there is nothing to learn) or higher
    (patterns work) and check whether the trade signal and the self-learning model notice the difference.
  </div>`);

  const cur = () => ({ provider: $('provider').value, symbol: $('symbol').value.trim() || 'SEEDED', interval: $('interval').value });
  let state = null, seeking = false;

  async function control(action, value) {
    try {
      const r = await fetch('/api/replay/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...cur(), action, value }),
      });
      const s = await r.json();
      if (!r.ok) throw new Error(s.error);
      show(s);
      $('go').click();                 // refresh chart right away
    } catch (e) { $('err').textContent = 'Replay: ' + e.message; }
  }

  function show(s) {
    state = s;
    $('rp-play').innerHTML = s.playing ? '&#9208; Pause' : '&#9654; Play';
    if (!seeking) { $('rp-seek').max = s.total; $('rp-seek').value = Math.floor(s.position); }
    $('rp-time').textContent = `${s.current_time_ist}  |  candle ${Math.floor(s.position)} of ${s.total}  (${s.start_time_ist} to ${s.end_time_ist})`;
    $('rp-seedopts').style.display = s.provider === 'seeder' ? 'inline-flex' : 'none';
    $('rp-follow').value = String(s.follow);
    const sp = $('rp-speed');
    const realPerMin = 60 / ({ '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600 }[s.interval] || 60);
    if (document.activeElement !== sp) sp.value = Math.abs(s.speed - realPerMin) < 1e-6 ? 'real' : String(s.speed);
  }

  async function poll() {
    try {
      const r = await fetch('/api/replay/state?' + new URLSearchParams(cur()));
      const s = await r.json();
      if (r.ok) show(s);
    } catch (e) { /* server restarting */ }
  }

  $('rp-play').onclick = () => control(state && state.playing ? 'pause' : 'play');
  $('rp-step').onclick = () => control('step');
  $('rp-new').onclick = () => control('new');
  $('rp-follow').onchange = () => control('follow', +$('rp-follow').value);
  $('rp-speed').onchange = () => {
    const v = $('rp-speed').value;
    const per = { '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600 }[$('interval').value] || 60;
    control('speed', v === 'real' ? 60 / per : +v);
  };
  $('rp-seek').oninput = () => { seeking = true; };
  $('rp-seek').onchange = () => { seeking = false; control('seek', +$('rp-seek').value); };

  poll();
  setInterval(poll, 1000);
})();
