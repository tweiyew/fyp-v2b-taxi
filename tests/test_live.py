import http.client
import json
import os
import socket
import subprocess
import sys
import threading

import pytest

from viz.live import RunManager
from viz.server import make_server

FRAME_KEYS = {
    "taxi_zone", "taxi_dest", "taxi_status", "taxi_soc", "taxi_soh",
    "requests", "rejected", "completed", "failed", "grid_kw", "station_kw",
}


@pytest.fixture
def site(tmp_path):
    """A live site on a free port that saves runs into a temporary results folder."""
    manager = RunManager(results_dir=str(tmp_path))
    server = make_server(0, manager)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield {"port": server.server_address[1], "results": tmp_path, "manager": manager}
    manager.shutdown()
    server.shutdown()
    server.server_close()


def call(site, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", site["port"], timeout=120)
    conn.request(method, path, body=None if body is None else json.dumps(body), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    try:
        return res.status, json.loads(data)
    except ValueError:
        return res.status, data


def stream(site, run_id, until=None):
    """Read the run's server-sent events until the server closes the stream (or <until> says stop)."""
    conn = http.client.HTTPConnection("127.0.0.1", site["port"], timeout=120)
    conn.request("GET", f"/api/runs/{run_id}/stream")
    res = conn.getresponse()
    assert res.status == 200
    assert res.getheader("Content-Type") == "text/event-stream"
    events, kind = [], None
    for raw in res:
        line = raw.decode().rstrip("\n")
        if line.startswith("event: "):
            kind = line[len("event: "):]
        elif line.startswith("data: "):
            events.append((kind, json.loads(line[len("data: "):])))
            if until and until(events):
                break
    conn.close()
    return events


def test_options_list_the_runnable_chicago_configs(site):
    status, options = call(site, "GET", "/api/options")
    assert status == 200
    configs = {c["name"]: c for c in options["configs"]}
    # nyc's data files are not in data/; chicago.yaml names ../data/..., which is outside the repo.
    assert set(configs) == {"chicago_v1g", "chicago_v2g"}
    assert configs["chicago_v1g"]["hours"] == 744
    dnn = next(p for p in options["policies"] if p["name"] == "DNN")
    assert dnn["available"] is False and dnn["reason"]


def test_a_three_hour_run_streams_three_frames_then_saves(site):
    status, started = call(site, "POST", "/api/runs", {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": 3})
    assert status == 201
    run_id = started["run_id"]
    assert started["total_hours"] == 3

    events = stream(site, run_id)
    kinds = [k for k, _ in events]
    assert kinds == ["start", "frame", "frame", "frame", "done"]
    start, frames, done = events[0][1], [d for k, d in events if k == "frame"], events[-1][1]
    assert start["total_hours"] == 3 and len(start["zones"]) == 77
    assert [f["time"] for f in frames] == ["2019-01-01T00:00", "2019-01-01T01:00", "2019-01-01T02:00"]
    assert all(set(f) == FRAME_KEYS | {"time"} for f in frames)

    folder = site["results"] / run_id
    assert sorted(os.listdir(folder)) == ["config.yaml", "metrics.json", "trace.json"]
    metrics = json.loads((folder / "metrics.json").read_text())
    assert len(metrics["commit"]) == 40 and metrics["hours"] == 3 and metrics == done
    trace = json.loads((folder / "trace.json").read_text())
    for key in FRAME_KEYS:
        assert trace[key] == [f[key] for f in frames], key

    status, listing = call(site, "GET", "/api/runs")
    assert [r["run_id"] for r in listing] == [run_id]
    status, saved = call(site, "GET", f"/api/runs/{run_id}")
    assert status == 200 and saved["trace"] == trace and saved["meta"] == metrics


def test_stop_ends_the_worker_and_saves_nothing(site):
    status, started = call(site, "POST", "/api/runs", {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": None})
    assert status == 201 and started["total_hours"] == 744
    run_id = started["run_id"]
    stream(site, run_id, until=lambda events: events[-1][0] == "frame")
    status, computing = call(site, "GET", "/api/live")
    assert status == 200 and computing["run_id"] == run_id

    status, busy = call(site, "POST", "/api/runs", {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": 3})
    assert status == 409 and "still going" in busy["error"]

    status, _ = call(site, "POST", f"/api/runs/{run_id}/stop")
    assert status == 200
    events = stream(site, run_id)
    assert events[-1][0] == "stopped"
    assert sum(k == "frame" for k, _ in events) < 744
    assert not site["manager"].current.process.is_alive()
    assert not (site["results"] / run_id).exists()
    assert call(site, "GET", "/api/live")[0] == 404


@pytest.mark.parametrize(
    "body",
    [
        {"config": "nyc", "policy": "EIGHTYTWENTY"},
        {"config": "../configs/chicago_v1g", "policy": "EIGHTYTWENTY"},
        {"config": "chicago_v1g", "policy": "RANDOM"},
        {"config": "chicago_v1g", "policy": "DNN", "weights": "../../x.pt"},
        {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": 0},
        {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": 745},
        {"config": "chicago_v1g", "policy": "EIGHTYTWENTY", "hours": "24"},
    ],
)
def test_bad_run_requests_are_rejected(site, body):
    status, reply = call(site, "POST", "/api/runs", body)
    assert status == 400 and reply["error"]
    assert site["manager"].current is None


@pytest.mark.parametrize(
    "path",
    ["/../viz/server.py", "/vendor/../../server.py", "/live.html", "/api/runs/..", "/api/runs/..%2F..%2Fdata", "/api/runs/nope/stream"],
)
def test_paths_outside_the_site_are_not_served(site, path):
    status, _ = call(site, "GET", path)
    assert status == 404


def test_page_and_its_files_are_served(site):
    status, page = call(site, "GET", "/")
    assert status == 200 and b"__SCENE_HTML__" not in page and b'id="timeline"' in page and b'id="runBtn"' in page
    for path in ("/scene.js", "/scene.css", "/live.js", "/live.css"):
        assert call(site, "GET", path)[0] == 200, path


def test_a_port_in_use_is_reported_by_number():
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        proc = subprocess.run(
            [sys.executable, "-m", "viz.server", "--port", str(port)], capture_output=True, text=True, timeout=60
        )
    assert proc.returncode != 0
    assert f"Port {port} is already in use" in proc.stderr
