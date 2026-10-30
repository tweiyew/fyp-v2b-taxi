"""Record one simulated episode as a compact per-hour trace for the 3D view.

Frame k describes hour k of the episode: where each taxi is at the start of the
hour, the requests that arrive in it, how many of those no taxi took, and what
happened during it (trips completed, power drawn). It reads only the `info`
dictionaries the simulator returns; no model code is changed.

Run: python -m viz.trace -c configs/chicago_v1g.yaml -p EIGHTYTWENTY
"""

import argparse
import contextlib
import datetime
import json
import os
import subprocess
import warnings
from collections import Counter
from typing import Dict, List, Optional

import yaml

from simulator.simulator import TaxiFleetSimulator
from simulator.vehicle import VehicleStatus

STATUSES = [s.name for s in sorted(VehicleStatus, key=lambda s: s.value)]
CONFIG_TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def with_hours(config: Dict, hours: int) -> Dict:
    """Return a copy of <config> whose episode ends <hours> after it starts."""
    start = datetime.datetime.strptime(config["start t"], CONFIG_TIME_FORMAT)
    end = start + datetime.timedelta(hours=hours) - datetime.timedelta(seconds=1)
    return {**config, "end t": end.strftime(CONFIG_TIME_FORMAT)}


def _waiting(info: Dict) -> List[Dict]:
    return [j for j in info["arrived"] if j["status"] == "ARRIVED"]


def _station_power(info: Dict) -> List[float]:
    return [
        sum(p["P_t"] for p in station["ports"] if p["vehicle"] is not None)
        for station in info["charging_network"]
    ]


class TraceRecorder:
    """Turns consecutive `info` dictionaries into per-hour frames."""

    def __init__(self, zones: List[int], first_info: Dict) -> None:
        self.zones = zones
        self.zone_index = {z: i for i, z in enumerate(zones)}
        self.stations = [s["location"] for s in first_info["charging_network"]]
        self.ports = [len(s["ports"]) for s in first_info["charging_network"]]
        self.start_zones = [v["location"] for v in first_info["fleet"]]
        self.before = first_info
        self.frames: Dict[str, List] = {
            key: []
            for key in (
                "taxi_zone", "taxi_dest", "taxi_status", "taxi_soc", "taxi_soh",
                "requests", "rejected", "completed", "failed", "grid_kw", "station_kw",
            )
        }

    def add(self, after: Dict) -> None:
        """Close the hour that started at `self.before` and ended at <after>."""
        before = self.before
        fleet = before["fleet"]
        f = self.frames
        f["taxi_zone"].append([v["location"] for v in fleet])
        f["taxi_dest"].append([v["destination"] for v in fleet])
        f["taxi_status"].append([STATUSES.index(v["status"]) for v in fleet])
        f["taxi_soc"].append([round(v["battery"]["soc"] * 100, 1) for v in fleet])
        f["taxi_soh"].append(
            [round(v["battery"]["actual_capacity"] / v["battery"]["initial_capacity"], 7) for v in fleet]
        )

        waiting = _waiting(before)
        requests = Counter(j["pickup_location"] for j in waiting)
        still_known = {
            j["id"] for key in ("arrived", "assigned", "inprogress") for j in after[key]
        }
        rejected = Counter(j["pickup_location"] for j in waiting if j["id"] not in still_known)
        f["requests"].append([requests.get(z, 0) for z in self.zones])
        f["rejected"].append([rejected.get(z, 0) for z in self.zones])

        f["completed"].append(after["completed"] - before["completed"])
        f["failed"].append(after["failed"] - before["failed"])
        f["grid_kw"].append(round(after["total_grid_power"], 3))
        f["station_kw"].append([round(p, 3) for p in _station_power(after)])
        self.before = after

    def summary(self, rejected_total: int) -> Dict:
        f = self.frames
        hours = len(f["completed"])
        zones_over_time = [self.start_zones] + f["taxi_zone"][1:] + [[v["location"] for v in self.before["fleet"]]]
        zone_changes = sum(
            a != b for prev, cur in zip(zones_over_time, zones_over_time[1:]) for a, b in zip(prev, cur)
        )
        recovery = STATUSES.index("RECOVERY")
        final_soh = [
            v["battery"]["actual_capacity"] / v["battery"]["initial_capacity"] for v in self.before["fleet"]
        ]
        return {
            "hours": hours,
            "requests": sum(map(sum, f["requests"])),
            "trips_completed": sum(f["completed"]),
            "requests_rejected": rejected_total,
            "trips_failed": sum(f["failed"]),
            "grid_energy_kwh": round(sum(f["grid_kw"]), 3),
            "taxi_zone_changes": zone_changes,
            "taxi_hours_in_recovery": sum(row.count(recovery) for row in f["taxi_status"]),
            "mean_final_soh": round(sum(final_soh) / len(final_soh), 7),
        }

    def trace(self, times: List[str], dt: float) -> Dict:
        return {
            "dt_seconds": dt,
            "times": times,
            "zones": self.zones,
            "statuses": STATUSES,
            "stations": {"zone": self.stations, "ports": self.ports},
            **self.frames,
        }


def make_policy(name: str, weights: Optional[str]):
    from scheduler.policies import DnnPolicy, EightyTwentyPolicy

    if name.upper() == "EIGHTYTWENTY":
        return EightyTwentyPolicy()
    if name.upper() == "DNN":
        return DnnPolicy(weights)
    raise ValueError(f"Unknown policy {name!r}: use EIGHTYTWENTY or DNN")


def record(config: Dict, policy) -> Dict:
    """Run one episode of <config> under <policy>; return {'trace', 'metrics'}."""
    env = TaxiFleetSimulator(config)
    with warnings.catch_warnings(), open(os.devnull, "w") as devnull, contextlib.redirect_stdout(devnull):
        # gymnasium warns that the action bounds are cast to float32; the values are exact.
        warnings.filterwarnings("ignore", category=UserWarning, module="gymnasium.spaces.box")
        observation, info = env.reset()
        recorder = TraceRecorder(sorted(env.region.map.keys()), info)
        rejected_start = info["rejected"]
        times, done = [], False
        while not done:
            times.append(env.t.strftime("%Y-%m-%dT%H:%M"))
            action = policy.schedule(observation, info)
            observation, _, done, _, info = env.step(action)
            recorder.add(info)
    return {
        "trace": recorder.trace(times, env.dt),
        "metrics": recorder.summary(info["rejected"] - rejected_start),
    }


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()


def write_run(result: Dict, config: Dict, run_dir: str, provenance: Dict) -> None:
    """Write trace.json, config.yaml and metrics.json (with the commit id) to <run_dir>."""
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "trace.json"), "w") as fp:
        json.dump(result["trace"], fp, separators=(",", ":"))
    with open(os.path.join(run_dir, "config.yaml"), "w") as fp:
        yaml.safe_dump(config, fp, sort_keys=False)
    with open(os.path.join(run_dir, "metrics.json"), "w") as fp:
        json.dump({**provenance, **result["metrics"]}, fp, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-c", "--config", required=True)
    parser.add_argument("-p", "--policy", default="EIGHTYTWENTY")
    parser.add_argument("-w", "--weights")
    parser.add_argument("--run-id", help="defaults to <timestamp>-<config>-<policy>")
    parser.add_argument("--hours", type=int, help="stop after this many hours")
    args = parser.parse_args()

    with open(args.config) as fp:
        config = yaml.safe_load(fp)
    if args.hours:
        config = with_hours(config, args.hours)

    config_name = os.path.splitext(os.path.basename(args.config))[0]
    run_id = args.run_id or (
        f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{config_name}-{args.policy.lower()}"
    )
    run_dir = os.path.join("results", run_id)
    result = record(config, make_policy(args.policy, args.weights))
    provenance = {
        "run_id": run_id,
        "config": args.config,
        "policy": args.policy.upper(),
        "weights": args.weights,
        "commit": _git("rev-parse", "HEAD"),
        "uncommitted_changes": bool(_git("status", "--porcelain", "--", "simulator", "scheduler", "configs")),
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    write_run(result, config, run_dir, provenance)
    print(run_dir)


if __name__ == "__main__":
    main()
