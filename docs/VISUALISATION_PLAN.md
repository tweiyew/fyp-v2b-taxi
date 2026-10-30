# Plan: a 3D view of the simulator

Written 23 Oct 2026. Status: steps 1 to 5 built on 24 Oct; step 6 waits for the P0 fixes.

## As built (24 Oct)

- Code lives in a `viz/` package rather than `scripts/`, so the tests can import it: `viz/zones.py` (step 1), `viz/trace.py` (step 2), `viz/build.py` + `viz/template.html` (steps 3 to 5). Tests: `tests/test_viz.py`, 9 tests.
- `make viz` records a run into `results/<RUN_ID>/` and writes `viz/out/<RUN_ID>.html` (open locally) and `viz/out/<RUN_ID>.artifact.html` (publish). `viz/out/` is gitignored.
- `viz/zones.geojson`: 77 zones, 55 kB, simplified at 20 m.
- Frame k is hour k: taxis where they are at the start of the hour; requests arriving in the hour; how many of those no taxi took (checked against the simulator's own rejected counter); trips completed and power drawn during the hour.
- First page: run `20261023-v1g-eightytwenty-baseline`, published at https://claude.ai/artifact/NTfNxDnEgHhdUV1kaQefsV (private).
- deck.gl 9.3.11 from unpkg; no basemap.

A single HTML page that replays one simulated month over a 3D model of Chicago's 77 community areas, hour by hour. It reads what the simulator already reports each tick; it changes no model code. The page opens on a phone (published as a claude.ai artifact) and in a desktop browser.

Why it is worth building now: the audit's worst bugs are visible at a glance. On today's code the 50 taxis never leave their start zones (row 2) and no station ever draws power (row 1). After P0 the same page should show taxis moving and stations charging, so it doubles as a visual check on the fixes, and later shows V2B at O'Hare for the report and the 5 Nov slide.

## What the page shows

| Layer | Drawn as | Source in `info` each tick |
| --- | --- | --- |
| Zones | 77 extruded polygons; height = requests that arrived this hour, colour = requests rejected | `info['arrived']` pickup zones, rejected count per zone |
| Taxis | 50 dots at their zone (spread so they don't overlap), coloured by status | `info['fleet'][i]['location']`, `['status']` |
| Trips in progress | Arcs from taxi zone to destination zone | `info['fleet'][i]['destination']` when status is TOPICKUP, ONJOB or TOCHARGE |
| Stations | Columns at zones 76 and 55; height = power drawn this hour | `info['charging_network'][s]['ports'][p]['P_t']` |
| Side panel | Clock, trips completed, grid kW, a SoC histogram of the fleet, taxis in RECOVERY | `info['completed']`, `info['total_grid_power']`, `info['fleet'][i]['battery']` |

Controls: play/pause, a time slider over the 744 hours, speed, tap a taxi to see its SoC, SoH and status. Camera: tilt and rotate by touch.

Later, after P1: a building-load column at O'Hare and the V2B power flowing into it.

## How it is built

```
make viz
  1. scripts/export_trace.py  runs one episode, records a compact trace per tick
  2. viz/build.py             joins the trace with the zone shapes, writes one HTML file
  3. publish                  the HTML file goes up as an artifact (private by default)
```

1. **Zone shapes** (`scripts/fetch_zones.py`, run once). Download the community-area boundaries from the City of Chicago data portal: `https://data.cityofchicago.org/resource/igwz-8jzy.geojson`. Checked 23 Oct: 77 features, `area_numbe` runs 1 to 77 and matches our zone ids, 76 is OHARE. The raw file is 2.0 MB with 52,641 vertices, so simplify it (keep about 5%, round to 5 decimals) to stay well under 300 kB. Store it in `viz/zones.geojson`, never in `data/`.
2. **Trace export** (`scripts/export_trace.py`). Same loop as `scheduler/__main__.py` EVAL, but after each `step()` it stores, from `info`: each taxi's zone, destination, status, SoC and SoH; requests and rejections per zone; power per station; trips completed; grid power. About 744 x 50 taxi rows plus 744 x 77 zone counts, a few MB as JSON before compression. Writes `results/<run-id>/trace.json`, `config.yaml`, `metrics.json` and the commit id, as `CLAUDE.md` requires.
3. **Page** (`viz/template.html` + `viz/build.py`). deck.gl from unpkg, pinned to an exact version, with no basemap: the extruded zones are the map, so the page needs no tile server, which the artifact host would block anyway. `build.py` inlines the zone shapes and the trace into one self-contained file under 16 MB.
4. **Make targets**: `make trace` (step 2), `make viz` (steps 2 and 3, writes `viz/out/index.html`). Same `CONFIG`, `POLICY`, `OUT` variables as `make run`.

Positions between hours are interpolated on the page only (a taxi slides from its zone to its destination over the hour). The simulator stays hourly; the animation does not pretend to more resolution than the trace has.

## Steps and checks

| # | Step | Done when |
| --- | --- | --- |
| 1 | `fetch_zones.py` | `viz/zones.geojson` has 77 features with ids 1 to 77 and is under 300 kB |
| 2 | `export_trace.py` + tests | Tests pass: 744 ticks for January, 50 taxis every tick, every zone id in 1 to 77, statuses from `VehicleStatus`, station power equals `total_grid_power` when V2G is off |
| 3 | Static page: zones + taxis at one hour | Opens in a desktop browser and on a phone; zone 76 sits where O'Hare is |
| 4 | Time slider, play, arcs, stations, side panel | Scrubbing to any hour shows that hour's numbers matching `trace.json` |
| 5 | `make viz` + publish | One command rebuilds the page; the artifact link opens on a phone |
| 6 | Rebuild after each P0 fix | Taxis visibly change zones after bug 2 is fixed; station columns rise after bug 1 |

Steps 1 to 5 need no decision from you and touch no model code, so they can run unattended.

## Rules for whoever builds it

- No edits to `simulator/`, `scheduler/` or `data/`. The export reads `info`; if something needed is missing from `info`, stop and ask.
- Runs are not repeatable yet (job pool in sets), so a trace is one sample, labelled with its run id.
- Read `trip counts`, `SoH` and `status` from the trace, not from the logger CSV: the CSV columns are shifted by one (see `CLAUDE.md`).
- No em dashes in any text the page shows.

## Decisions (Wei Yew, 23 Oct)

1. Zone height is requests per hour. Rejected requests stay as the zone colour.
2. One run per page. Comparing runs on one page is out of scope for now.

## Risks

| Risk | Fallback |
| --- | --- |
| deck.gl is slow on a phone with 77 extruded polygons and 50 animated points | Drop arcs on small screens; lower polygon detail further |
| The city portal URL moves | The file is fetched once and kept in `viz/`; the source URL is recorded in the file's header |
| Trace JSON too large for the page | Store per-tick arrays (columnar), quantise SoC to 1%, gzip and inflate in the page |
