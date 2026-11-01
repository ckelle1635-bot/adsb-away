'use strict';
const $ = id => document.getElementById(id);
const map = L.map('map').setView([33.5, -83.5], 7);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
const markers = new Map();
let aircraft = [], selected = null, fitted = false, lastSuccess = 0, live = false;
const fmt = (v, unit) => typeof v === 'number' ? Math.round(v).toLocaleString() + unit : (v === 'ground' ? 'Ground' : '—');
const callsign = a => a.flight || a.r || a.hex;
const positioned = a => Number.isFinite(a.lat) && Number.isFinite(a.lon) && Number.isFinite(a.seen_pos) && a.seen_pos < 60;
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
  const query = $('search').value.toLowerCase();
  const rows = aircraft.filter(a => [a.flight, a.r, a.t, a.hex, a.ownOp].some(v => String(v || '').toLowerCase().includes(query)));
  $('count').textContent = aircraft.length;
  $('aircraft').replaceChildren();
  if (!rows.length) {
    const p = document.createElement('p'); p.className = 'empty';
    p.textContent = !live ? 'No live data. Waiting for your receiver to connect.' : query ? 'No matching aircraft.' : 'Receiver connected. No aircraft currently detected.';
    $('aircraft').append(p);
  }
  const active = new Set();
  for (const a of rows.sort((a,b) => callsign(a).localeCompare(callsign(b)))) {
    const row = document.createElement('button'); row.className = 'aircraft' + (selected === a.hex ? ' selected' : '');
    const top = document.createElement('div'); top.className = 'row';
    const title = document.createElement('span'); title.className = 'callsign'; title.textContent = callsign(a);
    const type = document.createElement('span'); type.textContent = a.t || '';
    top.append(title, type);
    const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = [a.r, a.ownOp].filter(Boolean).join(' · ') || a.hex;
    const metrics = document.createElement('div'); metrics.className = 'metrics';
    metrics.textContent = `${fmt(a.alt_baro, ' ft')}  ·  ${fmt(a.gs, ' kt')}  ·  ${positioned(a) ? fmt(a.track, '°') : 'No recent position'}`;
    row.append(top, meta, metrics); row.onclick = () => choose(a); $('aircraft').append(row);
    if (!positioned(a)) continue;
    active.add(a.hex);
    const heading = Number.isFinite(a.track) ? a.track : 0;
    const icon = L.divIcon({className: 'plane' + (selected === a.hex ? ' chosen' : ''), html: `<span style="transform:rotate(${heading}deg)">✈</span>`, iconSize: [30,30], iconAnchor: [15,15]});
    let marker = markers.get(a.hex);
    if (!marker) {
      marker = L.marker([a.lat,a.lon], {icon}).addTo(map);
      marker.on('click', () => { const current = aircraft.find(x => x.hex === a.hex); if (current) choose(current); });
      markers.set(a.hex, marker);
    } else marker.setLatLng([a.lat,a.lon]).setIcon(icon);
    const label = document.createElement('span'); label.textContent = `${callsign(a)} · ${fmt(a.alt_baro, ' ft')} · ${fmt(a.gs, ' kt')}`;
    if (marker.getTooltip()) marker.setTooltipContent(label); else marker.bindTooltip(label);
  }
  for (const [hex, marker] of markers) if (!active.has(hex)) { map.removeLayer(marker); markers.delete(hex); }
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
$('fit').onclick = fit; $('search').oninput = render;
setInterval(() => { if (lastSuccess && Date.now() - lastSuccess > 30000) offline('Connection lost · data is stale'); }, 1000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && lastSuccess && Date.now() - lastSuccess > 30000) offline('Reconnecting…'); });
poll();
