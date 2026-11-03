'use strict';
// FAA overlays for the Home Airspace map:
//  - Airspace: Class B/C/D boundaries (FAA Aeronautical Information Services data, fetched and cached by
//    our server at /api/airspace), drawn in sectional-chart colours with ceiling/floor labels.
//  - Sectional: the FAA VFR sectional chart tiles, partly see-through. The FAA only publishes them for
//    zoom levels 8-12; closer zooms enlarge level 12.
// Each has its own toolbar button; the choice is remembered on this device.
window.setupOverlays = (map, stored) => {
  const CELL = 2;                 // degrees, matches the server
  const MIN_AIRSPACE_ZOOM = 6;    // below this the outlines are too small to read
  const LABEL_ZOOM = 9;           // ceiling/floor labels from this zoom
  const CHART_MIN_ZOOM = 8;
  const MAX_CELLS = 16;

  map.createPane('chart').style.zIndex = 250;     // above the street map (200), below everything else
  map.createPane('airspace').style.zIndex = 350;  // below aircraft (600) and their labels (650)
  map.getPane('airspace').style.pointerEvents = 'none';

  const chart = L.tileLayer('https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}', {
    pane: 'chart', opacity: 0.75, minZoom: CHART_MIN_ZOOM, maxZoom: 18, minNativeZoom: CHART_MIN_ZOOM, maxNativeZoom: 12,
    attribution: 'Sectional: FAA Aeronautical Information Services'
  });
  const airspace = L.layerGroup();
  airspace.getAttribution = () => 'Airspace: FAA Aeronautical Information Services';
  const loaded = new Set(), pending = new Set(), failed = new Map(), drawn = new Set();
  const styles = {
    B: {color: '#3b82f6', weight: 2.5, fillColor: '#3b82f6', fillOpacity: 0.05},
    C: {color: '#d946b0', weight: 2.5, fillColor: '#d946b0', fillOpacity: 0.05},
    D: {color: '#3b82f6', weight: 2, dashArray: '7 6', fillOpacity: 0}
  };

  // A note on the map for "zoom in" and "data unavailable" messages.
  const Note = L.Control.extend({
    options: {position: 'bottomleft'},
    onAdd() { this.el = L.DomUtil.create('div', 'map-note'); this.el.hidden = true; return this.el; },
    show(text) { this.el.textContent = text; this.el.hidden = !text; }
  });
  const note = new Note().addTo(map);

  let showAirspace = stored.get('airspace') === '1';
  let showChart = stored.get('chart') === '1';

  // Sectional-style label: ceiling over floor in hundreds of feet, e.g. "125/25", "40/SFC"; Class D "[33]".
  const level = (v, code) => code === 'SFC' || v === 0 ? 'SFC' : Number.isFinite(v) ? String(Math.round(v / 100)) : '?';
  const labelText = p => p.class === 'D' ? `[${level(p.upper, p.upper_code)}]` : `${level(p.upper, p.upper_code)}/${level(p.lower, p.lower_code)}`;

  // Pick a point well inside the first polygon (shelves are rings around the airport, so the centre of
  // the bounding box is often outside the shape). Coarse grid search; fine for labels.
  function inside(x, y, ring) {
    let hit = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }
  function edgeDistance(x, y, rings) {
    let best = Infinity;
    for (const ring of rings) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [ax, ay] = ring[j], [bx, by] = ring[i], dx = bx - ax, dy = by - ay;
      const t = dx || dy ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) : 0;
      best = Math.min(best, Math.hypot(x - ax - t * dx, y - ay - t * dy));
    }
    return best;
  }
  function labelPoint(rings) {
    const outer = rings[0], xs = outer.map(p => p[0]), ys = outer.map(p => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    let best = null, bestDistance = -1;
    for (let i = 1; i < 12; i++) for (let j = 1; j < 12; j++) {
      const x = x0 + (x1 - x0) * i / 12, y = y0 + (y1 - y0) * j / 12;
      if (!inside(x, y, outer) || rings.slice(1).some(hole => inside(x, y, hole))) continue;
      const d = edgeDistance(x, y, rings);
      if (d > bestDistance) { best = [y, x]; bestDistance = d; }
    }
    return best;
  }

  function draw(feature) {
    const p = feature.properties || {}, style = styles[p.class];
    const key = feature.id ?? JSON.stringify(feature.geometry.coordinates[0][0][0]) + labelText(p);
    if (!style || drawn.has(key)) return;
    drawn.add(key);
    L.geoJSON(feature, {pane: 'airspace', style: () => style, interactive: false}).addTo(airspace);
    const point = labelPoint(feature.geometry.coordinates[0]);
    if (!point) return;
    const text = document.createElement('span');
    text.textContent = labelText(p);
    L.tooltip({permanent: true, direction: 'center', className: `airspace-label class-${p.class}`, pane: 'airspace', interactive: false})
      .setLatLng(point).setContent(text).addTo(airspace);
  }

  function cellsInView() {
    const b = map.getBounds().pad(0.15), cells = [];
    const s = Math.floor(Math.max(-90, b.getSouth()) / CELL) * CELL, n = Math.min(90 - CELL, b.getNorth());
    const w = Math.floor(Math.max(-180, b.getWest()) / CELL) * CELL, e = Math.min(180 - CELL, b.getEast());
    for (let lat = s; lat <= n; lat += CELL) for (let lon = w; lon <= e; lon += CELL) cells.push(`${lat},${lon}`);
    return cells;
  }

  async function loadCell(cell) {
    if (loaded.has(cell) || pending.has(cell) || Date.now() < (failed.get(cell) || 0)) return;
    pending.add(cell);
    try {
      const response = await fetch('/api/airspace?cell=' + encodeURIComponent(cell), {signal: AbortSignal.timeout(40000)});
      if (response.status === 401) { location.assign('/login'); return; }
      if (!response.ok) throw new Error('unavailable');
      const data = await response.json();
      loaded.add(cell); failed.delete(cell);
      for (const feature of data.features || []) draw(feature);
    } catch (_) {
      failed.set(cell, Date.now() + 60000);   // try that area again in a minute
    } finally {
      pending.delete(cell);
      updateNote();
    }
  }

  function refreshAirspace() {
    if (!showAirspace || map.getZoom() < MIN_AIRSPACE_ZOOM) return;
    const cells = cellsInView();
    if (cells.length <= MAX_CELLS) cells.forEach(loadCell);
  }

  function updateNote() {
    const zoom = map.getZoom(), notes = [];
    if (showChart && zoom < CHART_MIN_ZOOM) notes.push('Zoom in to see the sectional chart');
    if (showAirspace && zoom < MIN_AIRSPACE_ZOOM) notes.push('Zoom in to see airspace');
    else if (showAirspace && [...failed.keys()].some(cell => cellsInView().includes(cell))) notes.push('Some FAA airspace data is unavailable right now');
    note.show(notes.join(' · '));
    map.getContainer().classList.toggle('airspace-labels', zoom >= LABEL_ZOOM);
  }

  function apply() {
    map[showAirspace ? 'addLayer' : 'removeLayer'](airspace);
    map[showChart ? 'addLayer' : 'removeLayer'](chart);
    for (const [id, on, label] of [['airspace-toggle', showAirspace, 'Airspace'], ['chart-toggle', showChart, 'Sectional']]) {
      const button = document.getElementById(id);
      button.setAttribute('aria-pressed', String(on));
      button.textContent = label;
    }
    refreshAirspace();
    updateNote();
  }

  document.getElementById('airspace-toggle').onclick = () => { showAirspace = !showAirspace; stored.set('airspace', showAirspace ? '1' : '0'); apply(); };
  document.getElementById('chart-toggle').onclick = () => { showChart = !showChart; stored.set('chart', showChart ? '1' : '0'); apply(); };
  let timer = null;
  map.on('moveend zoomend', () => { clearTimeout(timer); timer = setTimeout(() => { refreshAirspace(); updateNote(); }, 300); });
  apply();
};
