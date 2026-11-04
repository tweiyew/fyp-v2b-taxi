# 20261104-fdi-demo

Preliminary false-data-injection vulnerability demo. A fixed (not learned)
false-telemetry attack on the published 80-20 scheduler, on the fixed simulator
and the real January data. Establishes the attack surface for the FYP
(`docs/RESEARCH_PLAN.md`); it is not the RL attacker.

- Code: commit `c35637e`, model code (`simulator/`, `scheduler/`, `configs/`, `data/`) unchanged.
- Config: `configs/chicago_v1g.yaml`, January 2019, 50 taxis, 744 hours.
- Reproduce: `PYTHONPATH=. .venv/bin/python -m experiments.fdi_demo`
- Figure: `PYTHONPATH=. .venv/bin/python -m experiments.fdi_figure` writes `docs/figures/fdi-demo.png`.

The attack is injected at the observation boundary (`experiments/fdi_demo.py`,
`FalseTelemetryPolicy`): for a compromised set of taxis, the SoC the 80-20 policy
sees is replaced before it chooses an action. No physics is changed.

## Results (`sweep.csv`)

The honest run reproduces the P0 baseline exactly (16,591 trips, 35,280 kWh,
0 RECOVERY), so the attack is the only thing moving the numbers.

| mode | budget | trips | grid kWh | RECOVERY taxi-h |
| --- | --- | --- | --- | --- |
| honest | 0 | 16,591 | 35,280 | 0 |
| report empty (SoC=0) | 1 | 16,233 | 42,050 | 24 |
| report empty | 5 | 14,877 | 98,230 | 0 |
| report empty | 10 | 9,586 | 153,180 | 0 |
| report empty | 25 | 968 | 334,390 | 0 |
| report full (SoC=1) | 1 | 16,575 | 34,380 | 185 |
| report full | 5 | 16,352 | 32,200 | 852 |
| report full | 10 | 16,051 | 28,230 | 1,692 |
| report full | 25 | 15,277 | 18,180 | 4,149 |

Two levers:
- **Report empty** pins taxis to the chargers: trips served fall to 58% at 10
  compromised taxis and 6% at 25. A service and grid-stress attack.
- **Report full** leaves taxis uncharged until they drain into the 24 h RECOVERY
  reset: 4,149 taxi-hours offline at 25 compromised. Fleet trips barely move
  because the oversupplied fleet absorbs it, so RECOVERY hours are the right
  damage metric here. An availability attack.

Caveat: the **grid kWh** column overstates real draw. A pinned taxi that fills
still logs full port power (the station-logging bug noted in `CLAUDE.md`), so use
it for direction, not magnitude. Trips and RECOVERY are not affected by that bug;
the slide figure uses only those.
