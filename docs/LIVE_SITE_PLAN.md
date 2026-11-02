# Plan: a live simulation website

Written 24 Oct 2026. Status: built 30 Oct (see "As built"). Decisions taken with the defaults on 30 Oct.

## As built (30 Oct)

- Start: `make serve` (port 8765, or `PORT=...`), which opens the browser. The first time, it runs `make vendor` to download deck.gl 9.3.11 and the fonts into `viz/web/vendor/` (gitignored); after that it works offline.
- Code: `viz/live.py` (worker process, run manager, config and saved-run listings), `viz/server.py` (HTTP), `viz/vendor.py`. Page: `viz/web/scene.{js,css,html}` shared with the replay, `viz/web/live.{html,js,css}`, `viz/web/replay.html` (replaces `viz/template.html`).
- Runnable configs are `chicago_v1g` and `chicago_v2g` only. `configs/chicago.yaml` names `../data/...`, which is outside the repo when run from the root; `nyc.yaml`'s data is not in `data/`.
- Run ids: `<timestamp>-<config>-<policy>`, plus `-<hours>h` for runs shorter than the config.
- Endpoints as planned, plus `GET /api/live`: the run still computing, so a page reloaded mid-run reattaches to it. The worker's failure event is named `failed`, because `error` is the browser's own `EventSource` connection event. Unknown run ids and paths outside `viz/web/` get 404; bad run settings get 400; a second run while one computes gets 409.
- No polling fallback: `EventSource` reconnects by itself and the server resumes from `Last-Event-ID`.
- The replay's two notes no longer say "all month", since a run can be a day long.
- Checks: `tests/test_live.py` (18 tests: options, a 3-hour run streams 3 frames then saves, Stop, bad requests, paths, busy port) and 3 new tests in `tests/test_viz.py`. Screenshots at 1920 x 1080, 1400 x 900 and 500 x 860; the rebuilt replay matches the old one at 1400 x 900. Appending hours to the scene was checked in headless Chrome by feeding it the saved trace (readouts at hour 100 match `trace.json`). Not checked in a browser: playback while frames stream in (headless Chrome on this Mac fires no animation frames), and a run started from the page (the shell hook blocks POST requests).

A local website for the presentation. On the page you pick a config, a policy and a length, press Run, and the simulator computes the run on your laptop while the 3D city fills in hour by hour. Every run is saved, so any run can be replayed later without computing it again. Start it with `make serve`; it opens at `http://localhost:8765` in your own browser (override with `make serve PORT=...`). Nothing goes through claude.ai.

It builds on the replay already in `viz/` (see `docs/VISUALISATION_PLAN.md`): the same 3D scene, the same per-hour frames, the same `results/<run-id>/` folders. No model code changes.

## What the page does

| Area | What you see and do |
| --- | --- |
| Run controls | Config (only those whose map and demand files exist: today `chicago_v1g` and `chicago_v2g`), policy (`EIGHTYTWENTY`; `DNN` only when a `.pt` weights file is present, none today), length (1 day, 1 week, the whole month). Run and Stop buttons. |
| Progress | "Computing hour 312 of 744" beside the playback clock, so the audience sees the simulator working. Playback can lag behind computation; it never runs ahead of it. |
| 3D city | As in the replay: zone columns = requests in the hour, colour = requests no taxi took, taxis by status, trip arcs, charger rings and power columns. |
| Readouts | As in the replay: this hour's numbers, fleet by status, state of charge, battery health, and the "What this run shows" notes once the run ends. |
| Saved runs | A list of `results/` folders, newest first; picking one replays it at once. |
| Presenting | Full-screen button; camera presets (whole city, O'Hare close up, the Loop); hide-panels toggle; keys: Space play or pause, R run, F full screen, 1 to 3 camera presets. |

## How it works

```
browser  --GET /api/options------------------>  server (Python, standard library only)
browser  --POST /api/runs {config, policy, hours}->  starts a worker process
browser  <--GET /api/runs/<id>/stream (server-sent events, one frame per simulated hour)--
worker:  TaxiFleetSimulator + policy + TraceRecorder, sends each frame back to the server
server:  forwards frames to the page; writes results/<id>/ when the run ends
```

- **Server** (`viz/server.py`): `http.server.ThreadingHTTPServer`, bound to `127.0.0.1` only. No new packages. Endpoints:
  - `GET /`: the page and its static files from `viz/web/`.
  - `GET /api/options`: runnable configs, available policies, lengths.
  - `GET /api/zones`: `viz/zones.geojson`.
  - `POST /api/runs`: start a run; returns its run id. One run at a time; a second request while one runs gets a clear error.
  - `GET /api/runs/<id>/stream`: server-sent events, one `frame` event per hour, then a `done` event with the metrics.
  - `POST /api/runs/<id>/stop`: stop the worker; nothing is saved for a stopped run.
  - `GET /api/runs`, `GET /api/runs/<id>`: list saved runs, fetch one saved trace.
- **Worker**: one `multiprocessing` process per run. A separate process because the simulator prints every hour to stdout (`simulator/simulator.py:243`) and seeds `random` at import; in its own process both stay out of the server, and Stop can end it cleanly.
- **Frames**: `TraceRecorder.add()` in `viz/trace.py` gains a return value, the frame it just closed. The worker sends that dict; `record()` and its tests keep working unchanged. Same frame format as `trace.json`, so live and replayed runs draw with the same code.
- **Page** (`viz/web/`): the scene and readout code moves out of `viz/template.html` into `viz/web/scene.js`, shared by the live site and the replay builder (`viz/build.py` inlines it). `viz/web/live.js` adds the controls, the event stream and the saved-runs list.
- **Works without internet**: deck.gl (`dist.min.js`, 1.6 MB) and the three fonts are copied into `viz/web/vendor/` and served locally, so a venue without wifi doesn't break the demo. The replay builder keeps loading them from the CDN.
- **Speed**: a month computes in about 15 s (roughly 50 hours a second); default playback is 6 hours a second, so frames buffer ahead and playback stays smooth.

## Steps and checks

| # | Step | Done when |
| --- | --- | --- |
| 1 | `TraceRecorder.add()` returns the frame | Existing `tests/test_viz.py` passes; new test: the returned frames, stacked, equal the trace |
| 2 | Worker process + server endpoints | Tests start the server on a free port: `/api/options` lists the runnable Chicago configs; a 3-hour run streams exactly 3 frames then `done`; Stop ends the worker; an unknown config or a path like `../x` is rejected with a 400 |
| 3 | Run saving | A finished run leaves `results/<id>/` with `trace.json`, `config.yaml` and `metrics.json` with the commit id, identical in format to `make trace` |
| 4 | Split the page: `scene.js` shared, replay rebuilt from it | `make viz` output looks the same as before (screenshot at 1400 x 900) |
| 5 | Live page: controls, progress, streaming playback, saved runs | A full-month run plays from the first hour while it computes; picking a saved run replays it |
| 6 | Presenting: full screen, camera presets, keys, offline assets | Works with wifi off; screenshot at 1920 x 1080 and in a 400 px frame |
| 7 | `make serve` | One command starts the server on port 8765 (or `PORT`) and opens the browser; a port already in use gives a clear error naming it; Ctrl+C stops it |

## Rules for whoever builds it

- No edits to `simulator/`, `scheduler/` or `data/`.
- No new Python packages; the server uses the standard library.
- Bind to `127.0.0.1` only. Configs and run ids come only from the server's own lists, never as file paths from the page.
- Runs are not repeatable yet (job pool in sets), so two runs of the same config differ slightly; the page labels each run by its id.
- The fleet size is fixed at 50 because `EightyTwentyPolicy` and `DataLogger` hard-code it (`scheduler/policies.py:51`, `:83` to `:114`), so the page offers no fleet-size control.
- No em dashes in any text the page shows.

## Decisions for you

1. **Controls on the page**: config, policy and length only (the plan), or more? Anything that changes the model (port power, thresholds, payment rules) is yours to define first, so it stays off the page until you do.
2. **Saving**: save every finished run to `results/` (the plan), or only when you press Save? Saving everything means demo runs pile up in `results/`.
3. **Old replay page**: keep `make viz` and the published artifact as they are (the plan), or retire them once the live site works?

## Risks

| Risk | Fallback |
| --- | --- |
| Laptop is slower on presentation day, or the run stalls | Pick a saved run from the list; it replays without computing |
| Projector resolution makes the panels crowd the map | Hide-panels toggle; camera presets tuned at 1920 x 1080 |
| Audience asks why taxis never move | That is audit row 2; the "What this run shows" notes say so. After P0 the same site shows the fixed behaviour |
| Server-sent events blocked by a browser extension | The page falls back to polling `GET /api/runs/<id>` every second |
