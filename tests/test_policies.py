import numpy
import pytest

from scheduler.policies import EightyTwentyPolicy

FLEET = 50


def flags(cases):
    """Run the policy on a fleet whose first taxis are <cases> [(status, soc)]; the rest are IDLE and full."""
    cases = cases + [("IDLE", 1.0)] * (FLEET - len(cases))
    observation = numpy.array([[1.0, soc] for _, soc in cases])
    info = {"fleet": [{"status": status} for status, _ in cases]}
    action = EightyTwentyPolicy().schedule(observation, info)
    return [(bool(action[v, 0]), action[v, 1]) for v in range(len(cases))]


@pytest.mark.parametrize(
    "status, soc, charge",
    [
        ("IDLE", 0.15, True),  # below 20%: go and charge
        ("ONJOB", 0.15, True),  # below 20% (step() acts on the flag once the trip ends)
        ("IDLE", 0.5, False),  # in between and not charging: keep driving
        ("TOCHARGE", 0.5, True),  # on the way to a charger: keep going
        ("CHARGING", 0.5, True),  # plugged in below 80%: stay
        ("CHARGING", 0.79, True),
        ("CHARGING", 0.8, False),  # reached 80%: release
        ("TOCHARGE", 0.9, False),
    ],
)
def test_the_80_20_rule_charges_from_below_20_until_80(status, soc, charge):
    flag, rate = flags([(status, soc)])[0]
    assert flag is charge
    assert rate == (72.1 if charge else 0.0)
