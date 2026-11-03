'use strict';
const $ = id => document.getElementById(id);
const map = L.map('map').setView([33.5, -83.5], 7);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
const markers = new Map();
let aircraft = [], selected = null, fitted = false, lastSuccess = 0, live = false, lastInput = Date.now(), wakeLock = null;
const fmt = (v, unit) => typeof v === 'number' ? Math.round(v).toLocaleString() + unit : (v === 'ground' ? 'Ground' : '—');
const callsign = a => a.flight || a.r || a.hex;
const positioned = a => Number.isFinite(a.lat) && Number.isFinite(a.lon) && Number.isFinite(a.seen_pos) && a.seen_pos < 60;

// TV mode: /?tv=1 turns it on, /?tv=0 turns it off; the choice is remembered on this device.
const stored = {get: k => { try { return localStorage.getItem(k); } catch (_) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} }};
const param = new URLSearchParams(location.search).get('tv');
if (param !== null) stored.set('tv', param === '0' ? '0' : '1');
let tv = stored.get('tv') === '1';
// The "On your radar" list can be hidden to give the map the whole width; remembered per device.
let showList = stored.get('list') !== '0';

function fit() {
  const points = aircraft.filter(positioned).map(a => [a.lat, a.lon]);
  if (points.length) map.fitBounds(points, {padding: [35, 35], maxZoom: 11});
}
function choose(a) {
  selected = a.hex;
  if (positioned(a)) { map.panTo([a.lat, a.lon]); markers.get(a.hex)?.openTooltip(); }
  render();
}
function render() {
  const query = tv ? '' : $('search').value.toLowerCase();
  const rows = aircraft.filter(a => [a.flight, a.r, a.t, a.hex, a.ownOp].some(v => String(v || '').toLowerCase().includes(query)));
  const list = $('aircraft'), scroll = list.scrollTop;
  const focusedHex = document.activeElement?.closest?.('.aircraft')?.dataset.hex;
  let refocus = null;
  $('count').textContent = aircraft.length;
  list.replaceChildren();
  if (!rows.length) {
    const p = document.createElement('p'); p.className = 'empty';
    p.textContent = !live ? 'No live data. Waiting for your receiver to connect.' : query ? 'No matching aircraft.' : 'Receiver connected. No aircraft currently detected.';
    list.append(p);
  }
  const active = new Set();
  const size = tv ? 44 : 30;
  for (const a of rows.sort((a,b) => callsign(a).localeCompare(callsign(b)))) {
    const row = document.createElement('button'); row.className = 'aircraft' + (selected === a.hex ? ' selected' : '');
    row.dataset.hex = a.hex;
    if (a.hex === focusedHex) refocus = row;
    const top = document.createElement('div'); top.className = 'row';
    const title = document.createElement('span'); title.className = 'callsign'; title.textContent = callsign(a);
    const type = document.createElement('span'); type.textContent = a.t || '';
    top.append(title, type);
    const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = [a.r, a.ownOp].filter(Boolean).join(' · ') || a.hex;
    const metrics = document.createElement('div'); metrics.className = 'metrics';
    metrics.textContent = `${fmt(a.alt_baro, ' ft')}  ·  ${fmt(a.gs, ' kt')}  ·  ${positioned(a) ? fmt(a.track, '°') : 'No recent position'}`;
    row.append(top, meta, metrics); row.onclick = () => choose(a); list.append(row);
    if (!positioned(a)) continue;
    active.add(a.hex);
    const heading = Number.isFinite(a.track) ? a.track : 0;
    const icon = L.divIcon({className: 'plane' + (selected === a.hex ? ' chosen' : ''), html: `<span style="transform:rotate(${heading}deg)">✈</span>`, iconSize: [size,size], iconAnchor: [size/2,size/2]});
    let marker = markers.get(a.hex);
    if (!marker) {
      marker = L.marker([a.lat,a.lon], {icon, keyboard: !tv}).addTo(map);
      marker.on('click', () => { const current = aircraft.find(x => x.hex === a.hex); if (current) choose(current); });
      markers.set(a.hex, marker);
    } else marker.setLatLng([a.lat,a.lon]).setIcon(icon);
    // On a TV, keep a short callsign label visible, since there is no hover.
    const label = document.createElement('span');
    label.textContent = tv ? callsign(a) : `${callsign(a)} · ${fmt(a.alt_baro, ' ft')} · ${fmt(a.gs, ' kt')}`;
    if (marker.getTooltip()) marker.setTooltipContent(label);
    else marker.bindTooltip(label, tv ? {permanent: true, direction: 'right', offset: [size/2, 0]} : {});
  }
  for (const [hex, marker] of markers) if (!active.has(hex)) { map.removeLayer(marker); markers.delete(hex); }
  list.scrollTop = scroll;
  if (refocus) refocus.focus({preventScroll: true});
}
function offline(text) {
  live = false; aircraft = []; render();
  $('status').textContent = text; $('status').className = 'offline';
}
async function poll() {
  try {
    const response = await fetch('/api/aircraft', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (response.status === 401) { location.assign('/login'); return; }
    if (!response.ok) throw new Error('Feed unavailable');
    const data = await response.json(); lastSuccess = Date.now();
    $('updated').textContent = data.now ? 'Receiver update ' + new Date(data.now * 1000).toLocaleTimeString() : 'No updates received yet';
    if (!data.online) offline(data.now ? 'Feed offline · data is stale' : 'Waiting for receiver');
    else {
      live = true; aircraft = data.aircraft.filter(a => !Number.isFinite(a.seen) || a.seen < 60);
      $('status').textContent = '● Receiver live'; $('status').className = 'live'; render();
      if (!fitted && aircraft.some(positioned)) { fit(); fitted = true; }
    }
  } catch (_) { offline('Connection lost · retrying'); }
  setTimeout(poll, 5000);
}

// Keep the TV screen on while the map is visible (where the browser supports it).
async function keepAwake() {
  if (!tv || document.hidden || wakeLock || !('wakeLock' in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } catch (_) { wakeLock = null; }
}
function applyList() {
  document.body.classList.toggle('no-list', !showList);
  $('list-toggle').textContent = showList ? 'Hide list' : 'Show list';
  $('list-toggle').setAttribute('aria-expanded', String(showList));
  setTimeout(() => map.invalidateSize(), 0);
}
function applyMode() {
  document.body.classList.toggle('tv', tv);
  window.tvNav.enabled = tv;
  $('tv-toggle').textContent = tv ? 'Exit TV mode' : 'TV mode';
  $('tv-toggle').setAttribute('aria-pressed', String(tv));
  for (const marker of markers.values()) map.removeLayer(marker);
  markers.clear();
  map.keyboard[tv ? 'disable' : 'enable']();
  if (tv) keepAwake(); else if (wakeLock) wakeLock.release().catch(() => {});
  setTimeout(() => { map.invalidateSize(); render(); if (aircraft.some(positioned)) fit(); }, 0);
}

// Remote control: arrow keys move between buttons and aircraft (static/tvnav.js);
// landing on an aircraft row shows it on the map.
document.addEventListener('keydown', () => { lastInput = Date.now(); });
document.addEventListener('pointerdown', () => { lastInput = Date.now(); });
$('aircraft').addEventListener('focusin', e => {
  const hex = e.target.closest?.('.aircraft')?.dataset.hex;
  if (!tv || !hex || hex === selected) return;
  const a = aircraft.find(x => x.hex === hex);
  if (a) choose(a);
});
// In TV mode, after two minutes without remote input, zoom back out to show all aircraft.
setInterval(() => { if (tv && Date.now() - lastInput > 120000) { selected = null; fit(); render(); lastInput = Date.now(); } }, 30000);

$('fit').onclick = fit; $('search').oninput = render;
$('list-toggle').onclick = () => { showList = !showList; stored.set('list', showList ? '1' : '0'); applyList(); };
$('tv-toggle').onclick = () => { tv = !tv; stored.set('tv', tv ? '1' : '0'); applyMode(); };
setInterval(() => { if (lastSuccess && Date.now() - lastSuccess > 30000) offline('Connection lost · data is stale'); }, 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && lastSuccess && Date.now() - lastSuccess > 30000) offline('Reconnecting…');
  keepAwake();
});
applyList();
applyMode();
if (tv) $('fit').focus();
poll();
