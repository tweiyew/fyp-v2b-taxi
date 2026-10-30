import json

import pytest
import yaml

from viz.trace import STATUSES, make_policy, record, with_hours
from viz.zones import simplify_line, simplify_ring

HOURS = 24


@pytest.fixture(scope="module")
def run():
    with open("configs/chicago_v1g.yaml") as fp:
        config = with_hours(yaml.safe_load(fp), HOURS)
    return record(config, make_policy("EIGHTYTWENTY", None))


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
