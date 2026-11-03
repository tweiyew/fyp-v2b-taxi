import pickle

import pytest

from simulator.job import Job, JobStatus
from simulator.region import CyclicZoneGraph, CyclicZoneGraphLocation
from simulator.vehicle import Vehicle, VehicleStatus

HOUR = 3600
# Three zones; every leg is under an hour, so each leg ends at the first tick.
# Distances (km) and times (s) differ per pair, so a leg shows which zone it was costed from.
LEGS = {
    (1, 1): (0.5, 100), (1, 2): (2.0, 600), (1, 3): (9.0, 2700),
    (2, 1): (2.0, 600), (2, 2): (0.5, 100), (2, 3): (4.0, 1200),
    (3, 1): (9.0, 2700), (3, 2): (4.0, 1200), (3, 3): (0.5, 100),
}


@pytest.fixture
def region(tmp_path):
    table = {a: {b: {"distance": d, "time": t} for (a2, b), (d, t) in LEGS.items() if a2 == a} for a in (1, 2, 3)}
    path = tmp_path / "map.pkl"
    path.write_bytes(pickle.dumps(table))
    return CyclicZoneGraph(str(path))


def taxi_at(zone, region):
    return Vehicle("BYD E6", "multistage", CyclicZoneGraphLocation(zone, region), vid=0)


def job(pickup, dropoff, region):
    data = {
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "pickup_time": "2019-01-01 00:00:00",
        "dropoff_time": "2019-01-01 00:20:00",
        "distance": 4.0,
        "fare": 10.0,
    }
    return Job(data, job_id=1, region=region)


def test_a_taxi_ends_a_trip_at_the_dropoff_and_drives_the_second_leg_from_the_pickup(region):
    taxi = taxi_at(1, region)
    trip = job(pickup=2, dropoff=3, region=region)
    taxi.service_demand(trip)

    taxi.tick(HOUR, {"T_a": 25})  # reaches the pickup
    assert taxi.status == VehicleStatus.ONJOB
    assert taxi.location.zone == 2
    assert taxi.time_remaining == LEGS[(2, 3)][1]  # not the 1 -> 3 time

    taxi.tick(HOUR, {"T_a": 25})  # reaches the dropoff
    assert trip.status == JobStatus.COMPLETE
    assert taxi.status == VehicleStatus.IDLE
    assert taxi.location.zone == 3


def test_the_next_trip_starts_where_the_last_one_ended(region):
    taxi = taxi_at(1, region)
    taxi.service_demand(job(pickup=2, dropoff=3, region=region))
    taxi.tick(HOUR, {"T_a": 25})
    taxi.tick(HOUR, {"T_a": 25})

    taxi.service_demand(job(pickup=3, dropoff=1, region=region))
    assert taxi.time_remaining == LEGS[(3, 3)][1]  # already in zone 3, not driving from zone 1


def test_a_taxi_sent_to_a_charger_ends_up_in_the_charger_zone(region):
    class Charger:
        location = CyclicZoneGraphLocation(3, region)

        def disconnect(self, vid):
            pass

    taxi = taxi_at(1, region)
    taxi.charge(Charger(), 10.0)
    taxi.tick(HOUR, {"T_a": 25})
    assert taxi.status == VehicleStatus.CHARGING
    assert taxi.location.zone == 3


def test_a_taxi_back_from_recovery_is_at_its_depot(region):
    taxi = taxi_at(1, region)
    taxi.service_demand(job(pickup=2, dropoff=3, region=region))
    taxi.tick(HOUR, {"T_a": 25})
    taxi.tick(HOUR, {"T_a": 25})
    assert taxi.location.zone == 3

    taxi.battery.soc = 1e-6  # runs out on the next leg
    taxi.service_demand(job(pickup=2, dropoff=1, region=region))
    taxi.tick(HOUR, {"T_a": 25})
    assert taxi.status == VehicleStatus.RECOVERY
    for _ in range(24):
        taxi.tick(HOUR, {"T_a": 25})
    assert taxi.status == VehicleStatus.IDLE
    assert taxi.location.zone == 1
