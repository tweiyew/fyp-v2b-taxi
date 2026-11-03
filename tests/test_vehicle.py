import pickle

import pytest

from simulator.charger import ChargePort, ChargeStation
from simulator.job import Job, JobStatus
from simulator.region import CyclicZoneGraph, CyclicZoneGraphLocation
from simulator.vehicle import Vehicle, VehicleStatus

HOUR = 3600
# Zones 1 to 3 are under an hour apart, so each leg between them ends at the first tick.
# Zone 4 is 1.5 hours from zone 1, like 98 of the 154 zone-to-charger drives in the Chicago map.
# Distances (km) and times (s) differ per pair, so a leg shows which zone it was costed from.
LEGS = {
    (1, 1): (0.5, 100), (1, 2): (2.0, 600), (1, 3): (9.0, 2700), (1, 4): (30.0, 5400),
    (2, 1): (2.0, 600), (2, 2): (0.5, 100), (2, 3): (4.0, 1200), (2, 4): (28.0, 5000),
    (3, 1): (9.0, 2700), (3, 2): (4.0, 1200), (3, 3): (0.5, 100), (3, 4): (25.0, 4500),
    (4, 1): (30.0, 5400), (4, 2): (28.0, 5000), (4, 3): (25.0, 4500), (4, 4): (0.5, 100),
}
ZONES = sorted({a for a, _ in LEGS})


@pytest.fixture
def region(tmp_path):
    table = {a: {b: {"distance": d, "time": t} for (a2, b), (d, t) in LEGS.items() if a2 == a} for a in ZONES}
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


def station_at(zone, region, port_kw=10.0):
    return ChargeStation(CyclicZoneGraphLocation(zone, region), [ChargePort(port_kw, 0.9)], P_max=500)


def test_a_charger_more_than_an_hour_away_is_reached_and_the_taxi_charges(region):
    """step() calls charge() every hour while the flag is on; the drive must still end."""
    taxi = taxi_at(1, region)
    taxi.battery.soc = 0.15
    station = station_at(4, region)
    soc = []
    for _ in range(5):
        taxi.charge(station, 72.1)
        taxi.tick(HOUR, {"T_a": 25})
        station.tick([taxi], HOUR, 25)
        soc.append(taxi.battery.soc)

    assert taxi.status == VehicleStatus.CHARGING
    assert taxi.location.zone == 4
    assert station.ports[0].vehicle == taxi.vid and station.ports[0].P_t == 10.0
    first_plugged_in = next(i for i, (a, b) in enumerate(zip(soc, soc[1:])) if b > a)
    assert all(b > a for a, b in zip(soc[first_plugged_in:], soc[first_plugged_in + 1:]))  # charges every hour once there


def test_a_new_charger_trip_starts_its_timer_from_the_current_zone(region):
    taxi = taxi_at(1, region)
    taxi.charge(station_at(4, region), 10.0)
    assert taxi.status == VehicleStatus.TOCHARGE
    assert taxi.time_remaining == LEGS[(1, 4)][1]
