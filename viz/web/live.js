// Live site: run controls, the event stream from the server, saved runs and presenting keys.
// The 3D scene and readouts come from scene.js.
(async function () {
  const $ = (id) => document.getElementById(id);

  async function getJSON(url, init) {
    const res = await fetch(url, init);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
    return body;
  }
  function showMessage(text) {
    $("msg").textContent = text || "";
    $("msg").hidden = !text;
  }
  const fmt = (n) => n.toLocaleString("en-US");

  let zones;
  let options;
  try {
    [zones, options] = await Promise.all([getJSON("/api/zones"), getJSON("/api/options")]);
  } catch (err) {
    showMessage(`Could not reach the server: ${err.message}`);
    return;
  }
  let scene;
  try {
    scene = createFleetScene(zones);
  } catch (err) {
    showMessage(`Could not draw the 3D city: ${err.message}`);
    throw err;
  }

  // ---- controls
  for (const c of options.configs) $("cfg").add(new Option(c.name, c.name));
  if (!options.configs.length) showMessage("No config has its map and demand files in data/.");
  for (const p of options.policies) {
    if (p.name === "DNN" && p.available) {
      for (const w of p.weights) $("pol").add(new Option(`DNN: ${w}`, `DNN|${w}`));
    } else {
      const o = new Option(p.available ? p.label : `${p.label}: ${p.reason}`, p.name);
      o.disabled = !p.available;
      $("pol").add(o);
    }
  }
  function fillLengths() {
    const cfg = options.configs.find((c) => c.name === $("cfg").value);
    const keep = $("len").value;
    $("len").innerHTML = "";
    if (!cfg) return;
    for (const l of options.lengths) if (l.hours < cfg.hours) $("len").add(new Option(l.label, String(l.hours)));
    $("len").add(new Option(`Full (${cfg.hours} h)`, "full"));
    $("len").value = [...$("len").options].some((o) => o.value === keep) ? keep : "full";
  }
  $("cfg").addEventListener("change", fillLengths);
  fillLengths();

  // ---- saved runs
  let savedRuns = [];
  function savedLabel(r) {
    const when = (r.created || "").replace("T", " ").slice(0, 16);
    const cfg = (r.config || "").split("/").pop().replace(/\.yaml$/, "");
    return `${when} · ${cfg} · ${r.policy || "?"} · ${r.hours} h · ${fmt(r.trips_completed || 0)} trips`;
  }
  async function refreshSaved(selectId) {
    try {
      savedRuns = await getJSON("/api/runs");
    } catch (err) {
      showMessage(`Could not list saved runs: ${err.message}`);
      return;
    }
    $("saved").innerHTML = "";
    $("saved").add(new Option(savedRuns.length ? "Pick a saved run to replay" : "No saved runs yet", ""));
    for (const r of savedRuns) $("saved").add(new Option(savedLabel(r), r.run_id));
    $("saved").value = selectId && savedRuns.some((r) => r.run_id === selectId) ? selectId : "";
  }
  async function loadSaved(runId) {
    if (!runId) return;
    try {
      setProgress(`Loading ${runId}`, 0);
      const { trace, meta } = await getJSON(`/api/runs/${encodeURIComponent(runId)}`);
      scene.load(trace, meta);
      setProgress(`Saved run, ${fmt(trace.times.length)} hours`, 1);
      showMessage("");
    } catch (err) {
      showMessage(`Could not load ${runId}: ${err.message}`);
    }
  }
  $("saved").addEventListener("change", () => loadSaved($("saved").value));

  // ---- live runs
  let live = null; // { id, total, source }

  function setProgress(text, fraction) {
    $("progressText").textContent = text;
    $("progressFill").style.width = `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`;
  }
  function setRunning(on) {
    $("runBtn").textContent = on ? "Stop" : "Run";
    $("runBtn").classList.toggle("stop", on);
    for (const id of ["cfg", "pol", "len", "saved"]) $(id).disabled = on;
  }
  function endLive() {
    if (live && live.source) live.source.close();
    live = null;
    setRunning(false);
  }

  async function startRun() {
    showMessage("");
    const [policy, weights] = $("pol").value.split("|");
    const len = $("len").value;
    let started;
    try {
      started = await getJSON("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config: $("cfg").value, policy, weights: weights || null, hours: len === "full" ? null : Number(len) }),
      });
    } catch (err) {
      showMessage(err.message);
      return;
    }
    attach(started);
  }

  // Follow a run's event stream from its first event; used for new runs and for a run that
  // was already computing when the page loaded.
  function attach(run) {
    live = { id: run.run_id, total: run.total_hours };
    setRunning(true);
    setProgress("Starting the simulator", 0);
    $("saved").value = "";

    const source = new EventSource(`/api/runs/${encodeURIComponent(live.id)}/stream`);
    live.source = source;
    const mine = (run) => live && live.source === source && run;
    source.addEventListener("start", (ev) => {
      if (!mine(true)) return;
      const header = JSON.parse(ev.data);
      scene.load(header, { run_id: header.run_id, config: header.config, policy: header.policy }, { live: true, total: header.total_hours });
      scene.play();
    });
    source.addEventListener("frame", (ev) => {
      if (!mine(true)) return;
      scene.append(JSON.parse(ev.data));
      const n = scene.ready();
      setProgress(`Computing hour ${fmt(n)} of ${fmt(live.total)}`, n / live.total);
    });
    source.addEventListener("done", (ev) => {
      if (!mine(true)) return;
      const meta = JSON.parse(ev.data);
      scene.finish(meta);
      setProgress(`Done: ${fmt(meta.hours)} hours computed and saved`, 1);
      endLive();
      refreshSaved(meta.run_id);
    });
    source.addEventListener("failed", (ev) => {
      if (!mine(true)) return;
      scene.finish();
      setProgress("Run failed; nothing saved", 0);
      showMessage(JSON.parse(ev.data));
      endLive();
    });
    source.addEventListener("stopped", () => {
      if (!mine(true)) return;
      scene.finish();
      setProgress(`Stopped at hour ${fmt(scene.ready())}; nothing saved`, 0);
      endLive();
    });
    // Connection errors: EventSource reconnects by itself and resumes from the last event id.
    source.addEventListener("error", () => {
      if (mine(true) && source.readyState === EventSource.CONNECTING) setProgress("Reconnecting to the server", scene.ready() / live.total);
    });
  }

  async function stopRun() {
    if (!live) return;
    try {
      await getJSON(`/api/runs/${encodeURIComponent(live.id)}/stop`, { method: "POST" });
    } catch (err) {
      showMessage(err.message);
    }
  }
  $("runBtn").addEventListener("click", () => (live ? stopRun() : startRun()));

  // ---- presenting
  document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => scene.flyTo(b.dataset.view)));
  function toggleBare() {
    const bare = document.body.classList.toggle("bare");
    $("hideBtn").textContent = bare ? "Show panels" : "Hide panels";
  }
  function toggleFull() {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch((err) => showMessage(`Full screen refused: ${err.message}`));
  }
  document.addEventListener("fullscreenchange", () => {
    $("fullBtn").textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
  });
  $("hideBtn").addEventListener("click", toggleBare);
  $("controlsToggle").addEventListener("click", () => {
    const open = document.body.classList.toggle("controls-open");
    $("controlsToggle").setAttribute("aria-expanded", String(open));
    $("controlsToggle").textContent = open ? "Close" : "Simulate";
  });
  $("fullBtn").addEventListener("click", toggleFull);
  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.target.closest && ev.target.closest("input, select, textarea")) return;
    const key = ev.key.toLowerCase();
    if (key === "r" && !live) startRun();
    else if (key === "f") toggleFull();
    else if (key === "h") toggleBare();
    else if (key === "1") scene.flyTo("city");
    else if (key === "2") scene.flyTo("ohare");
    else if (key === "3") scene.flyTo("loop");
  });

  // Reattach to a run that is still computing; otherwise open on the newest saved run,
  // so the city is not empty before the first Run.
  await refreshSaved();
  const computing = await getJSON("/api/live").catch(() => null);
  if (computing) {
    attach(computing);
  } else if (savedRuns.length) {
    $("saved").value = savedRuns[0].run_id;
    await loadSaved(savedRuns[0].run_id);
  } else {
    scene.load({ zones: [], statuses: [], stations: { zone: [], ports: [] }, dt_seconds: 3600 }, {});
    setProgress("Ready", 0);
  }
})();
