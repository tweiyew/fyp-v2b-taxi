import pickle

import numpy
import pytest

from simulator.job import Job
from simulator.region import CyclicZoneGraphLocation
from simulator.simulator import TaxiFleetSimulator
from simulator.vehicle import VehicleStatus

# Two zones under an hour apart; zone 2 is further from zone 1 than zone 1 is from itself.
LEGS = {(1, 1): (0.5, 100), (1, 2): (3.0, 900), (2, 1): (3.0, 900), (2, 2): (0.5, 100)}
TRIP = {"pickup_time": "2019-01-01 00:00:00", "dropoff_time": "2019-01-01 00:20:00", "distance": 3.0, "fare": 10.0}


@pytest.fixture
def env(tmp_path):
    table = {a: {b: {"distance": d, "time": t} for (a2, b), (d, t) in LEGS.items() if a2 == a} for a in (1, 2)}
    (tmp_path / "map.pkl").write_bytes(pickle.dumps(table))
    rows = ["pickup_time,dropoff_time,distance,pickup_location,dropoff_location,fare"]
    rows += [f"2019-01-01 0{h}:00:00,2019-01-01 0{h}:20:00,3.0,2,2,10.0" for h in range(0, 9)]
    (tmp_path / "demand.csv").write_text("\n".join(rows) + "\n")
    config = {
        "delta t": 3600,
        "start t": "2019/01/01 00:00:00",
        "end t": "2019/01/01 05:00:00",
        "city": str(tmp_path / "map.pkl"),
        "demand": str(tmp_path / "demand.csv"),
        "enable_v2g": False,
        "fleet": {"size": 2, "vehicle": "BYD E6", "battery model": "multistage", "depot": "none"},
        "charging stations": [
            {"location": 2, "max port power": 10, "max total power": 500, "efficiency": 0.9, "ports": 2}
        ],
    }
    simulator = TaxiFleetSimulator(config)
    simulator.reset()
    for taxi in simulator.fleet:
        taxi.location = taxi.destination = taxi.depo = CyclicZoneGraphLocation(1, simulator.region)
    return simulator


def requests(env, *pickups):
    return {
        Job({**TRIP, "pickup_location": zone, "dropoff_location": 2}, job_id=100 + i, region=env.region)
        for i, zone in enumerate(pickups)
    }


def held_jobs(env):
    return [taxi.job for taxi in env.fleet if taxi.status in (VehicleStatus.TOPICKUP, VehicleStatus.ONJOB)]


def test_one_request_goes_to_one_taxi(env):
    env.arrived = requests(env, 1)
    env.step(numpy.zeros((2, 2)))
    assert len(held_jobs(env)) == 1
    assert [t.status for t in env.fleet].count(VehicleStatus.IDLE) == 1


def test_two_taxis_take_two_different_requests(env):
    env.arrived = requests(env, 1, 2)
    env.step(numpy.zeros((2, 2)))
    jobs = held_jobs(env)
    assert len(jobs) == 2
    assert jobs[0] is not jobs[1]
    assert sorted(j.pickup_location.zone for j in jobs) == [1, 2]


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_equally_close_requests_go_by_job_id_whatever_the_pool_order(env, order):
    jobs = sorted(requests(env, 1, 1), key=lambda j: j.id)
    env.arrived = [jobs[i] for i in order]  # a list, so the test fixes the iteration order
    assert env.get_closest_job(env.fleet[0]) is jobs[0]


def test_two_runs_of_the_same_config_are_identical():
    import random

    import yaml

    from viz.trace import make_policy, record, with_hours

    with open("configs/chicago_v1g.yaml") as fp:
        config = with_hours(yaml.safe_load(fp), 48)
    runs = []
    for _ in range(2):
        random.seed(0)  # start zones come from `random`, seeded once at import; reseed so only job order can differ
        runs.append(record(config, make_policy("EIGHTYTWENTY", None)))
    assert runs[0]["trace"] == runs[1]["trace"]
    assert runs[0]["metrics"] == runs[1]["metrics"]
