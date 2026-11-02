import json

import pytest
import yaml

from viz.build import render, scene_parts
from viz.trace import STATUSES, episode_hours, make_policy, record, with_hours
from viz.zones import simplify_line, simplify_ring

HOURS = 24


@pytest.fixture(scope="module")
def run():
    with open("configs/chicago_v1g.yaml") as fp:
        config = with_hours(yaml.safe_load(fp), HOURS)
    streamed = {"header": None, "hours": []}
    result = record(
        config,
        make_policy("EIGHTYTWENTY", None),
        on_start=lambda header: streamed.update(header=header),
        on_hour=lambda time, frame: streamed["hours"].append((time, frame)),
    )
    return {**result, "streamed": streamed}


def test_one_frame_per_simulated_hour(run):
    trace = run["trace"]
    assert len(trace["times"]) == HOURS
    for key in ("taxi_zone", "taxi_status", "requests", "rejected", "completed", "grid_kw", "station_kw"):
        assert len(trace[key]) == HOURS, key
    assert trace["times"][:2] == ["2019-01-01T00:00", "2019-01-01T01:00"]


def test_every_frame_holds_the_whole_fleet_in_known_zones(run):
    trace = run["trace"]
    assert trace["zones"] == list(range(1, 78))
    for zones, dests, statuses in zip(trace["taxi_zone"], trace["taxi_dest"], trace["taxi_status"]):
        assert len(zones) == len(dests) == len(statuses) == 50
        assert set(zones) <= set(trace["zones"])
        assert set(dests) <= set(trace["zones"])
        assert all(0 <= s < len(STATUSES) for s in statuses)


def test_rejections_match_the_simulator_counter(run):
    trace, metrics = run["trace"], run["metrics"]
    assert sum(map(sum, trace["rejected"])) == metrics["requests_rejected"]
    for requests, rejected in zip(trace["requests"], trace["rejected"]):
        assert all(0 <= r <= q for q, r in zip(requests, rejected))


def test_station_power_adds_up_to_grid_power_without_v2g(run):
    trace = run["trace"]
    for stations, grid in zip(trace["station_kw"], trace["grid_kw"]):
        assert sum(stations) == pytest.approx(grid)


def test_metrics_agree_with_the_frames(run):
    trace, metrics = run["trace"], run["metrics"]
    assert metrics["hours"] == HOURS
    assert metrics["trips_completed"] == sum(trace["completed"])
    assert metrics["requests"] == sum(map(sum, trace["requests"]))
    assert metrics["grid_energy_kwh"] == pytest.approx(sum(trace["grid_kw"]))


def test_streamed_frames_stacked_equal_the_trace(run):
    trace, streamed = run["trace"], run["streamed"]
    assert {**streamed["header"], "times": trace["times"]} == {k: trace[k] for k in [*streamed["header"], "times"]}
    assert [time for time, _ in streamed["hours"]] == trace["times"]
    for key in streamed["hours"][0][1]:
        assert [frame[key] for _, frame in streamed["hours"]] == trace[key], key


def test_episode_hours_matches_the_simulated_hours(run):
    with open("configs/chicago_v1g.yaml") as fp:
        config = yaml.safe_load(fp)
    assert episode_hours(config) == 744
    assert episode_hours(with_hours(config, HOURS)) == HOURS == len(run["trace"]["times"])


def test_replay_page_fills_each_placeholder_once_and_leaves_the_data_alone():
    with open("viz/web/replay.html") as fp:
        template = fp.read()
    trace = {"note": "__SCENE_JS__ </script>"}
    page = render(template, {"features": []}, trace, {}, scene_parts())
    assert page.count("window.createFleetScene = ") == 1
    assert '{"note":"__SCENE_JS__ <\\/script>"}' in page
    assert page.count("__SCENE_JS__") == 1  # the one inside the trace
    for placeholder in ("__SCENE_CSS__", "__SCENE_HTML__", "__ZONES_JSON__", "__TRACE_JSON__", "__META_JSON__"):
        assert placeholder not in page


def test_with_hours_leaves_the_original_config_alone():
    config = {"start t": "2019/01/01 00:00:01", "end t": "2019/01/31 23:59:59"}
    short = with_hours(config, 24)
    assert short["end t"] == "2019/01/02 00:00:00"
    assert config["end t"] == "2019/01/31 23:59:59"


def test_simplify_drops_points_on_a_straight_line():
    line = [(0.0, 0.0), (1.0, 0.0001), (2.0, 0.0), (3.0, 0.0)]
    assert simplify_line(line, tolerance=0.001) == [(0.0, 0.0), (3.0, 0.0)]


def test_simplified_ring_stays_closed():
    square = [(0, 0), (0.5, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    ring = simplify_ring(square, tolerance=0.01)
    assert ring[0] == ring[-1]
    assert len(ring) == 5


def test_zone_file_covers_every_community_area():
    with open("viz/zones.geojson") as fp:
        zones = json.load(fp)
    assert [f["properties"]["zone"] for f in zones["features"]] == list(range(1, 78))
    ohare = zones["features"][75]["properties"]
    assert ohare["name"] == "O'Hare"
    assert -88.0 < ohare["cx"] < -87.8 and 41.9 < ohare["cy"] < 42.05
