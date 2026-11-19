(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const PEOPLE = ['justin', 'yvette'];
  const adlDate = (offset = 0) => {
    const d = new Date(Date.now() + offset * 86400000);
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Australia/Adelaide' }).format(d); // YYYY-MM-DD
  };
  const store = {
    get(k, d) { try { const v = localStorage.getItem('cam.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('cam.' + k, JSON.stringify(v)); } catch {} }
  };
  const gmaps = r => 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(`${r.road}, ${r.suburb} SA`);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  let data, geo, dayIdx = 0, who = location.hash.slice(1) || store.get('who', 'all');
  if (!['all', ...PEOPLE].includes(who)) who = 'all';

  // ---------------------------------------------------------------- map
  const map = L.map('map', { zoomControl: false, attributionControl: true }).setView([-34.95, 138.58], 11);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19, subdomains: 'abcd',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a> · Locations: SA Police'
  }).addTo(map);
  const routeLayer = L.layerGroup().addTo(map);
  const camLayer = L.layerGroup().addTo(map);
  const camById = {};
  let meMarker = null;

  const people = () => who === 'all' ? PEOPLE : [who];
  const day = () => data.days[dayIdx];

  function drawRoutes() {
    routeLayer.clearLayers();
    for (const p of people()) {
      const r = data.routes[p]; if (!r) continue;
      L.polyline(r.coords, { color: r.color, weight: 6, opacity: 0.5, lineCap: 'round' }).addTo(routeLayer)
        .bindTooltip(`${r.name}: ${r.label}`, { sticky: true });
    }
  }

  function drawCams() {
    camLayer.clearLayers();
    for (const k in camById) delete camById[k];
    const bounds = [];
    for (const r of day().roads) {
      const lines = geo[r.id]; if (!lines) continue;
      const on = people().filter(p => r.match[p] === 'on');
      const near = people().filter(p => r.match[p] === 'near');
      const hot = on.length > 0;
      if (hot) L.polyline(lines, { color: '#ff3b30', weight: 16, opacity: 0.25, lineCap: 'round' }).addTo(camLayer);
      const line = L.polyline(lines, { color: hot ? '#ff3b30' : '#ff6b5e', weight: hot ? 7 : 4, opacity: hot ? 1 : 0.8, lineCap: 'round' }).addTo(camLayer);
      const tags = on.map(p => `<b style="color:${data.routes[p].color}">On ${data.routes[p].name}'s drive</b>`)
        .concat(near.map(p => `Near ${data.routes[p].name}'s drive`));
      camById[r.id] = line;
      line.bindPopup(`<b>${esc(r.road)}</b>, ${esc(r.suburb)}<br>${tags.join('<br>') || ''}<br><a href="${gmaps(r)}" target="_blank" rel="noopener">Open in Google Maps</a>`);
      lines.forEach(l => bounds.push(...l));
    }
    return bounds;
  }

  function fit(bounds) {
    let b = [];
    if (who !== 'all') {
      b = data.routes[who].coords.slice();
      day().roads.filter(r => r.match[who] && geo[r.id]).forEach(r => geo[r.id].forEach(l => b.push(...l)));
    } else b = bounds;
    if (b.length) map.fitBounds(b, { paddingTopLeft: [20, 150], paddingBottomRight: [20, 240], maxZoom: 15 });
  }

  // ---------------------------------------------------------------- UI
  function renderTabs() {
    const today = adlDate(), tomorrow = adlDate(1);
    $('days').innerHTML = data.days.map((d, i) => {
      const name = d.date === today ? 'Today' : d.date === tomorrow ? 'Tomorrow' : d.label.split(' ')[0].slice(0, 3);
      const n = d.roads.filter(r => people().some(p => r.match[p] === 'on')).length;
      return `<button data-i="${i}" class="${i === dayIdx ? 'on' : ''}">${name} <small>${d.label.split(' ').slice(1, 3).join(' ')}</small>${n ? ` · ${n}` : ''}</button>`;
    }).join('');
    $('days').querySelectorAll('button').forEach(b => b.onclick = () => { dayIdx = +b.dataset.i; render(); });
    $('who').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.who === who));
  }

  function renderSummary() {
    $('summary').innerHTML = people().map(p => {
      const r = data.routes[p];
      const on = day().roads.filter(x => x.match[p] === 'on');
      const near = day().roads.filter(x => x.match[p] === 'near');
      const pills = on.map(x => `<button class="pill" data-id="${x.id}">${esc(x.road)}, ${esc(x.suburb)}</button>`)
        .concat(near.map(x => `<button class="pill near" data-id="${x.id}">${esc(x.road)}, ${esc(x.suburb)}</button>`)).join('');
      return `<div class="card"><h3><i class="sw" style="background:${r.color}"></i>${r.name}
        <span class="count">${on.length} on route · ${near.length} near</span></h3>
        ${on.length + near.length ? `<div class="roads">${pills}</div>` : '<div class="clear">Clear ✓ nothing on or near this drive</div>'}</div>`;
    }).join('');
    $('summary').querySelectorAll('[data-id]').forEach(b => b.onclick = () => zoomTo(b.dataset.id));
  }

  function zoomTo(id) {
    const lines = geo[id]; if (!lines) return;
    map.fitBounds(lines.flat(), { paddingTopLeft: [30, 160], paddingBottomRight: [30, 260], maxZoom: 16 });
    if (camById[id]) setTimeout(() => camById[id].openPopup(), 350);
    $('sheet').hidden = true;
  }

  function renderSheet() {
    const d = day();
    const tags = r => PEOPLE.map(p => r.match[p] ? `<span class="tag ${p[0]} ${r.match[p] === 'near' ? 'near' : ''}" title="${r.match[p] === 'on' ? 'On' : 'Near'} ${data.routes[p].name}'s drive">${p[0].toUpperCase()}</span>` : '').join('')
      + (r.placed ? '' : '<span class="tag x" title="Not found on the map">?</span>');
    const group = list => {
      const by = {};
      list.forEach(r => (by[r.suburb] = by[r.suburb] || []).push(r));
      return Object.keys(by).sort().map(s => by[s].map(r =>
        `<div class="item" data-id="${r.id}"><span>${esc(r.road)} <span class="sub">· ${esc(s)}</span></span><span class="tags">${tags(r)}</span></div>`).join('')).join('');
    };
    let html = `<h4>${esc(d.label)} · ${d.roads.length} roads</h4>${group(d.roads)}`;
    if (data.country && data.country.roads.length)
      html += `<h4>Country · ${esc(data.country.label || 'this week')}</h4>${group(data.country.roads)}`;
    html += `<p class="fine"><b>J</b> = Justin's drive, <b>Y</b> = Yvette's (faded = nearby, within about 1 km). <b>?</b> = couldn't place on the map.<br>
      Source: ${esc(data.source)}. Updated ${esc(data.generated.replace('T', ' '))}.<br>
      SAPOL lists roads where cameras may operate that day, not exact spots or times.</p>`;
    $('sheet-title').textContent = 'All roads';
    $('sheet-body').innerHTML = html;
    $('sheet-body').querySelectorAll('.item').forEach(el => el.onclick = () => {
      if (geo[el.dataset.id]) zoomTo(el.dataset.id); else window.open(gmaps(findRoad(el.dataset.id)), '_blank');
    });
  }
  const findRoad = id => day().roads.concat(data.country.roads).find(r => r.id === id);

  function renderBanner() {
    const today = adlDate();
    let msg = '';
    if (!data.days.some(d => d.date === today)) msg = `Today's list isn't in yet (last update ${data.generated.slice(0, 10)}). Showing the latest available.`;
    else if (data.stale) msg = `Couldn't refresh the list this morning; showing data from ${data.generated.slice(0, 10)}.`;
    $('banner').hidden = !msg; $('banner').textContent = msg;
    const unplaced = day().roads.filter(r => !r.placed).length;
    $('sub').textContent = `${day().roads.length} roads${unplaced ? ` · ${unplaced} not mapped` : ''} · SA Police list`;
  }

  function render(refit = true) {
    renderTabs(); drawRoutes(); const b = drawCams(); renderSummary(); renderBanner();
    if (refit) fit(b);
    if (!$('sheet').hidden) renderSheet();
  }

  $('who').querySelectorAll('button').forEach(b => b.onclick = () => {
    who = b.dataset.who; store.set('who', who);
    history.replaceState(null, '', who === 'all' ? location.pathname : '#' + who);
    render();
  });
  $('btn-list').onclick = () => { renderSheet(); $('sheet').hidden = false; };
  $('btn-close').onclick = () => { $('sheet').hidden = true; };

  // ---------------------------------------------------------------- drive alerts
  const R = 6371000, rad = x => x * Math.PI / 180;
  const toXY = (lat, lon, lat0) => [rad(lon) * R * Math.cos(rad(lat0)), rad(lat) * R];
  function nearest(px, py, lines, lat0) {
    let best = { d: Infinity, x: 0, y: 0 };
    for (const ln of lines) for (let i = 1; i < ln.length; i++) {
      const [ax, ay] = toXY(ln[i - 1][0], ln[i - 1][1], lat0), [bx, by] = toXY(ln[i][0], ln[i][1], lat0);
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
      const x = ax + t * dx, y = ay + t * dy, d = Math.hypot(px - x, py - y);
      if (d < best.d) best = { d, x, y };
    }
    return best;
  }
  let watchId = null, wake = null, last = null, alertTimer = null;
  const state = {};
  function say(text) {
    try { const u = new SpeechSynthesisUtterance(text); u.lang = 'en-AU'; u.rate = 1.02; speechSynthesis.cancel(); speechSynthesis.speak(u); } catch {}
    try { navigator.vibrate && navigator.vibrate([200, 100, 200]); } catch {}
  }
  function showAlert(kicker, road, meta) {
    $('alert-k').textContent = kicker; $('alert-r').textContent = road; $('alert-m').textContent = meta;
    $('alert').hidden = false; $('banner').hidden = true;
    clearTimeout(alertTimer); alertTimer = setTimeout(() => { $('alert').hidden = true; renderBanner(); }, 9000);
  }
  function onFix(pos) {
    const { latitude: lat, longitude: lon, speed, heading } = pos.coords;
    const t = pos.timestamp, lat0 = lat, [px, py] = toXY(lat, lon, lat0);
    let v = speed, hd = heading;
    if (last) {
      const [lx, ly] = toXY(last.lat, last.lon, lat0), dist = Math.hypot(px - lx, py - ly), dt = (t - last.t) / 1000;
      if ((v == null || isNaN(v)) && dt > 0) v = dist / dt;
      if ((hd == null || isNaN(hd)) && dist > 4) hd = (Math.atan2(px - lx, py - ly) * 180 / Math.PI + 360) % 360;
    }
    last = { lat, lon, t };
    v = v || 0;
    $('d-speed').textContent = Math.round(v * 3.6);
    if (!meMarker) meMarker = L.circleMarker([lat, lon], { radius: 8, color: '#fff', weight: 3, fillColor: '#3fa9ff', fillOpacity: 1 }).addTo(map);
    else meMarker.setLatLng([lat, lon]);
    map.panTo([lat, lon], { animate: true });

    const todayDay = data.days.find(d => d.date === adlDate());
    if (!todayDay) { $('d-next').textContent = "No list for today"; return; }
    const look = Math.max(300, v * 25);
    let closest = null;
    for (const r of todayDay.roads) {
      const lines = geo[r.id]; if (!lines) continue;
      const n = nearest(px, py, lines, lat0), s = state[r.id] = state[r.id] || {};
      if (!closest || n.d < closest.d) closest = { d: n.d, r };
      const approaching = s.d != null && n.d < s.d - 3;
      const brg = (Math.atan2(n.x - px, n.y - py) * 180 / Math.PI + 360) % 360;
      const facing = hd == null || Math.abs(((brg - hd + 540) % 360) - 180) < 50;
      if (n.d < 25 && !s.on) { s.on = s.ahead = true; showAlert("You're on a camera road", r.road, r.suburb); say(`Camera road. ${r.road}.`); }
      else if (n.d < look && n.d >= 25 && approaching && facing && v > 3 && !s.ahead) {
        s.ahead = true; const m = Math.round(n.d / 10) * 10;
        showAlert('Camera road ahead', r.road, `${m} m · ${r.suburb}`); say(`Camera road ahead. ${r.road}, ${m} metres.`);
      }
      if (n.d > look * 2 + 300) { s.on = s.ahead = false; }
      s.d = n.d;
    }
    $('d-next').textContent = closest ? `Nearest: ${closest.r.road} ${closest.d < 1000 ? Math.round(closest.d) + ' m' : (closest.d / 1000).toFixed(1) + ' km'}` : 'No mapped roads today';
  }
  async function startDrive() {
    if (!navigator.geolocation) { alert('Location is not available on this device.'); return; }
    say('Drive alerts on.');
    const t = data.days.findIndex(d => d.date === adlDate()); if (t >= 0) { dayIdx = t; render(false); }
    watchId = navigator.geolocation.watchPosition(onFix, e => { $('d-next').textContent = 'Location error: ' + e.message; },
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 20000 });
    try { wake = await navigator.wakeLock.request('screen'); } catch {}
    $('btn-drive').textContent = 'Stop drive'; $('btn-drive').classList.add('stop'); $('drive').hidden = false;
  }
  function stopDrive() {
    navigator.geolocation.clearWatch(watchId); watchId = null;
    try { wake && wake.release(); } catch {} wake = null;
    $('btn-drive').textContent = 'Start drive'; $('btn-drive').classList.remove('stop'); $('drive').hidden = true;
  }
  $('btn-drive').onclick = () => watchId == null ? startDrive() : stopDrive();
  $('btn-test').onclick = () => { showAlert('Camera road ahead', 'Test Road', '400 m · this is a test'); say('Camera road ahead. Test road, 400 metres.'); };
  document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'visible' && watchId != null) { try { wake = await navigator.wakeLock.request('screen'); } catch {} }
  });

  // ---------------------------------------------------------------- load
  async function load() {
    const bust = '?t=' + Date.now();
    [data, geo] = await Promise.all([fetch('data/data.json' + bust).then(r => r.json()), fetch('data/geo.json' + bust).then(r => r.json())]);
    const today = adlDate();
    dayIdx = Math.max(0, data.days.findIndex(d => d.date >= today));
    if (data.days[dayIdx] && data.days[dayIdx].date < today) dayIdx = data.days.length - 1;
    render();
  }
  load().catch(e => { $('sub').textContent = 'Could not load data: ' + e.message; });
})();
