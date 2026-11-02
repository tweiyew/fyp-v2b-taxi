// The 3D city and its readouts, shared by the replay page (viz/build.py) and the live site
// (viz/server.py). createFleetScene(zones) returns a scene that draws one run at a time:
// load() gives it a trace, whole for a saved run or empty for a live one, and append()
// adds each hour as the simulator produces it. Needs deck.gl (global `deck`) and scene.html.
window.createFleetScene = function createFleetScene(ZONES) {
  const FRAME_KEYS = [
    "taxi_zone", "taxi_dest", "taxi_status", "taxi_soc", "taxi_soh",
    "requests", "rejected", "completed", "failed", "grid_kw", "station_kw",
  ];
  const STATUS_INFO = {
    IDLE: { name: "Idle", color: [143, 160, 184] },
    TOPICKUP: { name: "To pickup", color: [255, 214, 120] },
    ONJOB: { name: "On a trip", color: [242, 179, 61] },
    TOCHARGE: { name: "To charger", color: [125, 200, 255] },
    CHARGING: { name: "Charging", color: [69, 214, 195] },
    TOLOC: { name: "Repositioning", color: [180, 156, 255] },
    OFFDUTY: { name: "Off duty", color: [90, 100, 118] },
    RECOVERY: { name: "Out of charge (24 h)", color: [236, 96, 150] },
  };
  const RAMP = [[38, 56, 79], [176, 122, 69], [239, 106, 91]];
  const STATION_ELEV_PER_KW = 12;
  const COLUMN_TOP = 6000;
  const LOOP_ZONE = 32;
  const OHARE_ZONE = 76;

  // Zones: centroid and name from the shapes file.
  const zoneInfo = new Map(ZONES.features.map((f) => [f.properties.zone, f.properties]));
  const center = (zone) => { const p = zoneInfo.get(zone); return [p.cx, p.cy]; };
  const zoneName = (zone) => (zoneInfo.get(zone) || { name: "Zone " + zone }).name;

  // ---- the run being shown, and what is derived from its frames
  let T = null;          // trace: header fields, `times`, and one array per FRAME_KEYS entry
  let META = {};         // metrics.json for a finished run; run settings while a live run computes
  let TOTAL = 0;         // hours the run will have when complete
  let LIVE = false;
  let zoneIndex = new Map();
  let MOVING = new Set();
  let FLEET = 0;
  let OFFSETS = [];
  let maxReq = 1;
  let ELEV_PER_REQUEST = COLUMN_TOP;
  let nonzeroRej = [];
  let rejCap = 1;
  let rejDirty = false;
  let cityRequests = [];
  let cityRejected = [];
  let doneCum = [];

  const ready = () => (T ? T.times.length : 0);
  const statusOf = (i) => STATUS_INFO[T.statuses[i]];

  function rejCapNow() {
    if (rejDirty) {
      const sorted = [...nonzeroRej].sort((a, b) => a - b);
      rejCap = sorted.length ? Math.max(1, sorted[Math.floor(sorted.length * 0.95)]) : 1;
      rejDirty = false;
    }
    return rejCap;
  }
  function rampColor(v) {
    const t = Math.min(1, v / rejCapNow()) * (RAMP.length - 1);
    const i = Math.min(RAMP.length - 2, Math.floor(t));
    const f = t - i;
    return RAMP[i].map((c, j) => Math.round(c + (RAMP[i + 1][j] - c) * f));
  }

  // Each taxi keeps a fixed spot inside its zone so taxis in one zone don't overlap.
  function makeOffsets(n) {
    return Array.from({ length: n }, (_, i) => {
      const angle = i * 2.39996;
      const r = 250 + 450 * (((i * 37) % n) / n);
      return [(r * Math.sin(angle)) / (111320 * Math.cos((41.85 * Math.PI) / 180)), (r * Math.cos(angle)) / 111320];
    });
  }

  // Fold hour k into the scales and running totals.
  function ingest(k) {
    if (!FLEET) { FLEET = T.taxi_zone[k].length; OFFSETS = makeOffsets(FLEET); }
    let req = 0, rej = 0;
    for (const v of T.requests[k]) { req += v; if (v > maxReq) maxReq = v; }
    for (const v of T.rejected[k]) { rej += v; if (v > 0) { nonzeroRej.push(v); rejDirty = true; } }
    ELEV_PER_REQUEST = COLUMN_TOP / maxReq;
    cityRequests[k] = req;
    cityRejected[k] = rej;
    doneCum[k] = (k ? doneCum[k - 1] : 0) + T.completed[k];
  }

  // ---- time helpers
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FULL_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  function parseTime(s) {
    const [d, t] = s.split("T");
    const [y, m, dd] = d.split("-").map(Number);
    const [hh, mm] = t.split(":").map(Number);
    return new Date(Date.UTC(y, m - 1, dd, hh, mm));
  }
  const pad = (n) => String(n).padStart(2, "0");
  function clockText(k) {
    const d = parseTime(T.times[k]);
    const end = new Date(d.getTime() + T.dt_seconds * 1000);
    return `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}, ${pad(d.getUTCHours())}:00 to ${pad(end.getUTCHours())}:00`;
  }
  const fmt = (n) => n.toLocaleString("en-US");

  // ---- deck.gl
  const lerp = (a, b, f) => a + (b - a) * f;
  function taxiPosition(k, i) {
    const zone = T.taxi_zone[k][i];
    const [x, y] = center(zone);
    const z = T.requests[k][zoneIndex.get(zone)] * ELEV_PER_REQUEST;
    return [x + OFFSETS[i][0], y + OFFSETS[i][1], z + 60];
  }

  const narrow = () => window.innerWidth < 900;
  // Fit the city's bounding box into the space the panels leave free, then tilt. A window too
  // small to fit into (an embedding frame that is not laid out yet) gets a fixed view instead.
  function fittedView() {
    const xs = [], ys = [];
    for (const f of ZONES.features) for (const poly of f.geometry.coordinates) for (const [x, y] of poly[0]) { xs.push(x); ys.push(y); }
    const w = window.innerWidth, h = window.innerHeight;
    const padding = narrow()
      ? { top: 120, bottom: 150, left: 10, right: 10 }
      : { top: 40, bottom: 120, left: 40, right: 360 };
    const tilt = { pitch: 50, bearing: -16, maxPitch: 75 };
    if (w - padding.left - padding.right < 100 || h - padding.top - padding.bottom < 100) {
      return { longitude: (Math.min(...xs) + Math.max(...xs)) / 2, latitude: (Math.min(...ys) + Math.max(...ys)) / 2, zoom: 9, ...tilt };
    }
    const fit = new deck.WebMercatorViewport({ width: w, height: h }).fitBounds(
      [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
      { padding }
    );
    return { longitude: fit.longitude, latitude: fit.latitude, zoom: fit.zoom + (narrow() ? -0.3 : 0.35), ...tilt };
  }
  function closeUp(zone, zoom, bearing) {
    const [longitude, latitude] = center(zone);
    // Shift the target a little right so the panel on the right does not cover it.
    return { longitude: longitude + (narrow() ? 0 : 0.03), latitude: latitude - 0.02, zoom: narrow() ? zoom - 0.8 : zoom, pitch: 58, bearing, maxPitch: 75 };
  }
  const VIEWS = {
    city: fittedView,
    ohare: () => closeUp(OHARE_ZONE, 12.2, 20),
    loop: () => closeUp(LOOP_ZONE, 12.6, -24),
  };

  const deckgl = new deck.Deck({
    parent: document.getElementById("map"),
    initialViewState: fittedView(),
    controller: true,
    getTooltip: tooltip,
    onClick: (info) => { if (!info.object) select(null); },
    layers: [],
  });

  let playhead = 0;      // fractional hour
  let shownFrame = -1;   // frame the readouts show
  let selected = null;   // { kind: "taxi", i } or { kind: "zone", zone }

  function emptyLayers() {
    return [new deck.GeoJsonLayer({
      id: "zones",
      data: ZONES,
      extruded: true,
      getElevation: 40,
      getFillColor: RAMP[0],
      getLineColor: [120, 140, 170, 90],
      wireframe: true,
      opacity: 0.9,
    })];
  }

  function layers() {
    if (!ready()) return emptyLayers();
    rejCapNow();
    const last = ready() - 1;
    const k = Math.min(last, Math.floor(playhead));
    const k2 = Math.min(last, k + 1);
    const f = playhead - k;
    const kk = f < 0.5 ? k : k2;
    const stations = T.stations.zone.map((zone, s) => ({ zone, s, ports: T.stations.ports[s] }));

    const zoneLayer = new deck.GeoJsonLayer({
      id: "zones",
      data: ZONES,
      extruded: true,
      wireframe: true,
      pickable: true,
      opacity: 0.9,
      getElevation: (feat) => {
        const i = zoneIndex.get(feat.properties.zone);
        return lerp(T.requests[k][i], T.requests[k2][i], f) * ELEV_PER_REQUEST;
      },
      getFillColor: (feat) => rampColor(T.rejected[kk][zoneIndex.get(feat.properties.zone)]),
      getLineColor: [120, 140, 170, 90],
      material: { ambient: 0.5, diffuse: 0.55, shininess: 24, specularColor: [70, 76, 90] },
      updateTriggers: { getElevation: [playhead, ELEV_PER_REQUEST], getFillColor: [kk, rejCap] },
      onClick: (info) => select({ kind: "zone", zone: info.object.properties.zone }),
    });

    const taxis = Array.from({ length: FLEET }, (_, i) => {
      const a = taxiPosition(k, i);
      const b = taxiPosition(k2, i);
      return { i, position: [lerp(a[0], b[0], f), lerp(a[1], b[1], f), lerp(a[2], b[2], f)], status: T.taxi_status[kk][i] };
    });
    const taxiLayer = new deck.ScatterplotLayer({
      id: "taxis",
      data: taxis,
      pickable: true,
      radiusUnits: "meters",
      getRadius: 170,
      radiusMinPixels: 3.5,
      radiusMaxPixels: 12,
      stroked: true,
      lineWidthMinPixels: 1,
      getLineColor: (d) => (selected && selected.kind === "taxi" && selected.i === d.i ? [255, 255, 255] : [11, 18, 32]),
      getFillColor: (d) => statusOf(d.status).color,
      getPosition: (d) => d.position,
      updateTriggers: { getLineColor: selected && selected.kind === "taxi" ? selected.i : -1 },
      onClick: (info) => select({ kind: "taxi", i: info.object.i }),
    });

    const arcs = taxis
      .filter((d) => MOVING.has(d.status) && T.taxi_dest[kk][d.i] !== T.taxi_zone[kk][d.i])
      .map((d) => {
        const dest = T.taxi_dest[kk][d.i];
        const [x, y] = center(dest);
        return { source: d.position, target: [x, y, T.requests[kk][zoneIndex.get(dest)] * ELEV_PER_REQUEST + 60], status: d.status };
      });
    const arcLayer = new deck.ArcLayer({
      id: "trips",
      data: arcs,
      getSourcePosition: (d) => d.source,
      getTargetPosition: (d) => d.target,
      getSourceColor: (d) => [...statusOf(d.status).color, 200],
      getTargetColor: (d) => [...statusOf(d.status).color, 60],
      getHeight: 0.35,
      getWidth: 1.5,
      widthMinPixels: 1,
    });

    const stationRings = new deck.ScatterplotLayer({
      id: "station-rings",
      data: stations,
      radiusUnits: "meters",
      getRadius: 900,
      radiusMinPixels: 8,
      stroked: true,
      filled: false,
      lineWidthMinPixels: 2,
      getLineColor: [69, 214, 195],
      getPosition: (d) => [...center(d.zone), T.requests[kk][zoneIndex.get(d.zone)] * ELEV_PER_REQUEST + 20],
      updateTriggers: { getPosition: [kk, ELEV_PER_REQUEST] },
    });
    const stationColumns = new deck.ColumnLayer({
      id: "station-power",
      data: stations,
      radius: 500,
      diskResolution: 24,
      extruded: true,
      getPosition: (d) => center(d.zone),
      getElevation: (d) => T.station_kw[kk][d.s] * STATION_ELEV_PER_KW,
      getFillColor: [69, 214, 195, 210],
      updateTriggers: { getElevation: kk },
    });
    const labels = new deck.TextLayer({
      id: "labels",
      data: stations,
      getPosition: (d) => [...center(d.zone), T.requests[kk][zoneIndex.get(d.zone)] * ELEV_PER_REQUEST + 400],
      getText: (d) => `${zoneName(d.zone)} charger, ${fmt(Math.round(T.station_kw[kk][d.s]))} kW`,
      getSize: 13,
      getColor: [230, 235, 242],
      fontFamily: '"Barlow Condensed", "Arial Narrow", sans-serif',
      fontWeight: 600,
      characterSet: "auto",
      background: true,
      getBackgroundColor: [11, 18, 32, 215],
      backgroundPadding: [5, 3],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      updateTriggers: { getPosition: [kk, ELEV_PER_REQUEST], getText: kk },
    });

    return [zoneLayer, stationColumns, stationRings, arcLayer, taxiLayer, labels];
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function tooltip({ object, layer }) {
    if (!object || !layer || !ready()) return null;
    const k = Math.min(ready() - 1, Math.round(playhead));
    let html;
    if (layer.id === "zones") {
      const zone = object.properties.zone;
      const i = zoneIndex.get(zone);
      html = `<b>${escapeHtml(zoneName(zone))}</b> (zone ${zone})<br>${fmt(T.requests[k][i])} requests, ${fmt(T.rejected[k][i])} no taxi took`;
    } else if (layer.id === "taxis") {
      const i = object.i;
      html = `<b>Taxi ${i}</b>: ${statusOf(T.taxi_status[k][i]).name}<br>Charge ${T.taxi_soc[k][i].toFixed(1)}%`;
    } else {
      return null;
    }
    return {
      html,
      style: {
        background: "#0f1726",
        color: "#e6ebf2",
        border: "1px solid #24324a",
        borderRadius: "8px",
        padding: "6px 8px",
        fontFamily: '"Barlow", system-ui, sans-serif',
        fontSize: "13px",
      },
    };
  }

  // ---- readouts
  const $ = (id) => document.getElementById(id);
  const legendOrder = ["ONJOB", "TOPICKUP", "IDLE", "TOCHARGE", "CHARGING", "RECOVERY", "TOLOC", "OFFDUTY"];

  function renderReadouts(k) {
    $("clock").textContent = clockText(k);
    $("hourOf").textContent = `Hour ${k + 1} of ${TOTAL}`;
    $("tReq").textContent = fmt(cityRequests[k]);
    $("tRej").textContent = fmt(cityRejected[k]);
    $("tDone").textContent = fmt(T.completed[k]);
    $("tDoneCum").textContent = fmt(doneCum[k]);
    $("tGrid").textContent = `${fmt(Math.round(T.grid_kw[k]))} kW`;

    const statuses = T.taxi_status[k];
    const counts = new Map();
    statuses.forEach((s) => counts.set(s, (counts.get(s) || 0) + 1));
    const sorted = [...statuses].sort((a, b) => legendOrder.indexOf(T.statuses[a]) - legendOrder.indexOf(T.statuses[b]));
    $("fleetbar").innerHTML = sorted.map((s) => `<span style="background: rgb(${statusOf(s).color.join(",")})"></span>`).join("");
    $("legend").innerHTML = legendOrder
      .map((name) => {
        const idx = T.statuses.indexOf(name);
        const n = counts.get(idx) || 0;
        return `<li class="${n ? "" : "zero"}"><span class="dot" style="background: rgb(${STATUS_INFO[name].color.join(",")})"></span>${STATUS_INFO[name].name}<span class="n num">${n}</span></li>`;
      })
      .join("");

    const bins = new Array(10).fill(0);
    T.taxi_soc[k].forEach((soc) => bins[Math.min(9, Math.floor(soc / 10))]++);
    const top = Math.max(...bins, 1);
    $("hist").innerHTML = bins
      .map((n, b) => `<span style="height: ${(n / top) * 100}%" title="${b * 10} to ${b * 10 + 10}%: ${n} taxis"></span>`)
      .join("");
    const soh = T.taxi_soh[k];
    $("sohMean").textContent = `${((soh.reduce((a, b) => a + b, 0) / soh.length) * 100).toFixed(4)}%`;
    $("sohMin").textContent = `${(Math.min(...soh) * 100).toFixed(4)}%`;
    $("keyMax").textContent = fmt(maxReq);
    $("keyRej").textContent = `${fmt(rejCapNow())}+`;

    renderPick(k);
    drawTimeline();
  }

  function renderEmpty() {
    $("clock").textContent = LIVE ? "Starting the simulator" : "No run loaded";
    $("hourOf").textContent = LIVE ? `0 of ${TOTAL} hours computed` : "";
    for (const id of ["tReq", "tRej", "tDone", "tDoneCum", "tGrid", "sohMean", "sohMin", "keyMax", "keyRej"]) $(id).textContent = "";
    for (const id of ["fleetbar", "legend", "hist"]) $(id).innerHTML = "";
    $("pick").hidden = true;
    drawTimeline();
  }

  function renderPick(k) {
    const box = $("pick");
    if (!selected) { box.hidden = true; return; }
    box.hidden = false;
    const rows = [];
    if (selected.kind === "taxi") {
      const i = selected.i;
      const status = statusOf(T.taxi_status[k][i]).name;
      const zone = T.taxi_zone[k][i];
      const dest = T.taxi_dest[k][i];
      $("pickTitle").textContent = `Taxi ${i}`;
      rows.push(["Status", status], ["Zone", `${zoneName(zone)} (${zone})`]);
      if (dest !== zone) rows.push(["Heading to", `${zoneName(dest)} (${dest})`]);
      rows.push(["Charge", `${T.taxi_soc[k][i].toFixed(1)}%`], ["Battery health", `${(T.taxi_soh[k][i] * 100).toFixed(4)}%`]);
    } else {
      const zone = selected.zone;
      const i = zoneIndex.get(zone);
      $("pickTitle").textContent = zoneName(zone);
      const here = T.taxi_zone[k].filter((z) => z === zone).length;
      rows.push(["Zone", String(zone)], ["Requests", fmt(T.requests[k][i])], ["No taxi took", fmt(T.rejected[k][i])], ["Taxis here", String(here)]);
    }
    $("pickBody").innerHTML = rows.map(([a, b]) => `<dt>${escapeHtml(a)}</dt><dd class="num">${escapeHtml(b)}</dd>`).join("");
  }

  function select(sel) {
    selected = ready() ? sel : null;
    render(true);
  }
  $("pickClose").addEventListener("click", () => select(null));

  // Title line, run details and the notes; rerun when a live run gets its first hour or finishes.
  function renderStatic() {
    const parts = ["Chicago"];
    if (ready()) {
      const first = parseTime(T.times[0]);
      parts.push(`${FULL_MONTHS[first.getUTCMonth()]} ${first.getUTCFullYear()}`, `${FLEET} taxis`);
    }
    $("eyebrow").textContent = parts.join(" · ");
    $("slider").max = String(Math.max(0, TOTAL - 1));

    const m = META || {};
    const notes = [];
    if (m.taxi_zone_changes === 0) notes.push("No taxi left the zone it started in. Audit row 2: a taxi's location is never updated when it arrives.");
    if (m.grid_energy_kwh === 0) notes.push("No charger drew any power. Audit row 1: taxis sent to charge never get plugged in.");
    if (m.taxi_hours_in_recovery > 0) notes.push(`Taxis spent ${fmt(m.taxi_hours_in_recovery)} taxi-hours out of charge, waiting out the 24-hour reset.`);
    const note = $("note");
    note.querySelectorAll("p").forEach((p) => p.remove());
    notes.forEach((text) => { const p = document.createElement("p"); p.textContent = text; note.appendChild(p); });
    note.hidden = notes.length === 0;

    const commit = m.commit ? m.commit.slice(0, 7) + (m.uncommitted_changes ? " + local edits" : "") : undefined;
    const num = (v, unit) => (typeof v === "number" ? fmt(v) + (unit || "") : undefined);
    const run = [
      ["Run", m.run_id], ["Config", m.config], ["Policy", m.policy], ["Code", commit],
      ["Requests", num(m.requests)], ["Trips done", num(m.trips_completed)],
      ["No taxi took", num(m.requests_rejected)], ["Grid energy", num(m.grid_energy_kwh, " kWh")],
    ].filter(([, v]) => v !== undefined && v !== null);
    $("run").innerHTML = run.map(([a, b]) => `<dt>${escapeHtml(a)}</dt><dd>${escapeHtml(b)}</dd>`).join("");
  }

  // ---- timeline: requests per hour across the run, with the playhead; hours not yet computed are dimmed
  const timeline = $("timeline");
  function drawTimeline() {
    const dpr = window.devicePixelRatio || 1;
    const w = timeline.clientWidth, h = timeline.clientHeight;
    if (!w) return;
    if (timeline.width !== Math.round(w * dpr)) { timeline.width = Math.round(w * dpr); timeline.height = Math.round(h * dpr); }
    const ctx = timeline.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const n = ready();
    const x = (k) => (TOTAL > 1 ? (k / (TOTAL - 1)) * w : 0);
    if (n < TOTAL) {
      ctx.fillStyle = "rgba(138,151,171,0.08)";
      ctx.fillRect(x(Math.max(0, n - 1)), 0, w - x(Math.max(0, n - 1)), h);
    }
    if (!n) return;
    const peak = Math.max(...cityRequests, 1);
    // midnight ticks, weekly labels
    ctx.font = '11px "IBM Plex Mono", ui-monospace, monospace';
    ctx.textBaseline = "top";
    T.times.forEach((t, k) => {
      if (!t.endsWith("T00:00")) return;
      const d = parseTime(t);
      ctx.fillStyle = "rgba(138,151,171,0.25)";
      ctx.fillRect(Math.round(x(k)), 0, 1, h);
      if (d.getUTCDay() === 1 && w > 320) { ctx.fillStyle = "#8a97ab"; ctx.fillText(`${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`, x(k) + 3, 1); }
    });
    // requests area
    const y = (v) => h - (v / peak) * (h - 12);
    ctx.beginPath();
    ctx.moveTo(0, h);
    cityRequests.forEach((v, k) => ctx.lineTo(x(k), y(v)));
    ctx.lineTo(x(n - 1), h);
    ctx.closePath();
    ctx.fillStyle = "rgba(242,179,61,0.28)";
    ctx.fill();
    ctx.strokeStyle = "rgba(242,179,61,0.8)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    cityRequests.forEach((v, k) => (k ? ctx.lineTo : ctx.moveTo).call(ctx, x(k), y(v)));
    ctx.stroke();
    // playhead
    ctx.fillStyle = "#e6ebf2";
    ctx.fillRect(Math.round(x(playhead)) - 1, 0, 2, h);
  }
  function seekFromPointer(ev) {
    const rect = timeline.getBoundingClientRect();
    const t = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
    setPlayhead(Math.round(t * (TOTAL - 1)));
  }
  timeline.addEventListener("pointerdown", (ev) => { timeline.setPointerCapture(ev.pointerId); pause(); seekFromPointer(ev); });
  timeline.addEventListener("pointermove", (ev) => { if (timeline.hasPointerCapture(ev.pointerId)) seekFromPointer(ev); });
  timeline.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowRight") { pause(); setPlayhead(Math.floor(playhead) + 1); ev.preventDefault(); }
    if (ev.key === "ArrowLeft") { pause(); setPlayhead(Math.ceil(playhead) - 1); ev.preventDefault(); }
  });

  // ---- playback. The playhead never passes the last computed hour; while a live run is
  // still computing, playback waits there instead of stopping.
  let playing = false;
  let lastTs = null;
  function render(force) {
    deckgl.setProps({ layers: layers() });
    if (!ready()) { renderEmpty(); return; }
    const kk = Math.min(ready() - 1, Math.round(playhead));
    if (force || kk !== shownFrame) {
      shownFrame = kk;
      $("slider").value = String(kk);
      renderReadouts(kk);
    } else {
      drawTimeline();
    }
  }
  function setPlayhead(h) { playhead = Math.min(Math.max(0, ready() - 1), Math.max(0, h)); render(false); }
  function tick(ts) {
    if (!playing) return;
    if (lastTs !== null && ready()) {
      const speed = Number($("speed").value);
      playhead = Math.min(ready() - 1, playhead + ((ts - lastTs) / 1000) * speed);
      if (playhead >= TOTAL - 1) pause();
      render(false);
    }
    lastTs = ts;
    requestAnimationFrame(tick);
  }
  function play() {
    if (ready() && playhead >= TOTAL - 1) playhead = 0;
    playing = true;
    lastTs = null;
    $("play").innerHTML = "&#10074;&#10074;";
    $("play").setAttribute("aria-label", "Pause");
    requestAnimationFrame(tick);
  }
  function pause() {
    playing = false;
    $("play").innerHTML = "&#9654;";
    $("play").setAttribute("aria-label", "Play");
  }
  const toggle = () => (playing ? pause() : play());
  $("play").addEventListener("click", toggle);
  $("slider").addEventListener("input", (ev) => { pause(); setPlayhead(Number(ev.target.value)); });
  document.addEventListener("keydown", (ev) => {
    if (ev.code === "Space" && ev.target === document.body) { ev.preventDefault(); toggle(); }
  });
  $("statsToggle").addEventListener("click", () => {
    const open = $("panel").classList.toggle("open");
    $("statsToggle").setAttribute("aria-expanded", String(open));
    $("statsToggle").textContent = open ? "Map" : "Stats";
  });
  window.addEventListener("resize", () => { timeline.width = 0; drawTimeline(); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => render(true));

  // ---- public API
  // load(trace, meta, {live, total}): show a run. A saved run opens paused on the busiest hour
  // of its first week; a live run starts empty at hour 0 and grows through append().
  function load(trace, meta, opts) {
    const o = opts || {};
    pause();
    T = { ...trace, times: [...(trace.times || [])] };
    for (const key of FRAME_KEYS) T[key] = [...(trace[key] || [])];
    META = meta || {};
    LIVE = !!o.live;
    TOTAL = o.total || T.times.length;
    zoneIndex = new Map(T.zones.map((z, i) => [z, i]));
    MOVING = new Set(["TOPICKUP", "ONJOB", "TOCHARGE", "TOLOC"].map((s) => T.statuses.indexOf(s)));
    FLEET = 0; OFFSETS = [];
    maxReq = 1; ELEV_PER_REQUEST = COLUMN_TOP; nonzeroRej = []; rejCap = 1; rejDirty = false;
    cityRequests = []; cityRejected = []; doneCum = [];
    selected = null; shownFrame = -1;
    for (let k = 0; k < T.times.length; k++) ingest(k);
    let start = 0;
    if (!LIVE) for (let k = 0; k < Math.min(ready(), 168); k++) if (cityRequests[k] > cityRequests[start]) start = k;
    playhead = start;
    timeline.width = 0;
    renderStatic();
    render(true);
  }
  // append(frame): one more computed hour of a live run, with its `time`.
  function append(frame) {
    T.times.push(frame.time);
    for (const key of FRAME_KEYS) T[key].push(frame[key]);
    ingest(ready() - 1);
    if (ready() === 1) { renderStatic(); render(true); } else if (!playing) drawTimeline();
  }
  // finish(meta): the run is over; show its metrics and notes.
  function finish(meta) {
    META = meta || META;
    LIVE = false;
    TOTAL = ready() || TOTAL;
    renderStatic();
    render(true);
  }
  function flyTo(name) {
    const view = (VIEWS[name] || VIEWS.city)();
    deckgl.setProps({ initialViewState: { ...view, transitionDuration: 1400, transitionInterpolator: new deck.FlyToInterpolator() } });
  }

  return { load, append, finish, play, pause, toggle, flyTo, ready, isPlaying: () => playing, playhead: () => playhead };
};
