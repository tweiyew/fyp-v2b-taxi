# Plan: P0, fix the base simulator (3 to 5 Nov)

Written 3 Nov 2026. Goal: by the 5 Nov group presentation, the January V1G run charges energy, taxis change zones, and there is a before/after baseline table for the implementation slide (`docs/PLAN.md:97`). Line numbers are as of commit `cf3722f`.

## How each fix is done

1. Write a test that fails on today's code. Run it and show it failing.
2. Show the fix as a diff. Wei Yew approves it before it is applied (`docs/PLAN.md:122`).
3. Run the whole suite; it must pass. One commit per fix.

Tests go in `tests/test_vehicle.py`, `tests/test_simulator.py` and `tests/test_policies.py`. They build a small region and a few taxis by hand, so each runs in well under a second.

## Steps

| # | When | Step | What is wrong today | Fix | Done when |
| --- | --- | --- | --- | --- | --- |
| 0 | 3 Nov | Smoke test of the live site (Wei Yew, 5 min) | Not yet seen in a real browser | `make serve`, Run, 1 day | It plays; or we know what is broken |
| 1 | 3 Nov | Bug 2: taxis never move | `self.location` is set only in `__init__` (`simulator/vehicle.py:60`). Arrival at a pickup (`:149`), a dropoff (`:188`), a charger (`:163`), a reposition target (`:176`) and the end of RECOVERY (`:193`) never moves the taxi. | Set `location = destination` at each arrival; after RECOVERY the taxi is at its depot | Test: a taxi that finishes a trip is in the dropoff zone, and the second leg is costed from the pickup zone |
| 2 | 3 Nov | Bug 1: no taxi ever plugs in | While the flag is on, `step()` calls `charge()` every tick (`simulator/simulator.py:174`). `charge()` restarts the trip timer every time (`vehicle.py:114`), and its arrival check `self.location != self.destination` (`:116`) compares two `Location` objects, which have no `__eq__`, so it is true even in the same zone and throws a CHARGING taxi back to TOCHARGE | Compare `.zone`; keep the timer when the target charger is unchanged | Test: a taxi with the flag on reaches the charger, stays CHARGING, and its SoC rises; station power is above 0 |
| 3 | 3 or 4 Nov | Bug 8: two taxis take one job | `get_closest_job()` (`simulator.py:139`) reads `self.arrived`, but assigned jobs leave it only at the end of `step()` (`:224`) | Remove a job from the pool when it is assigned | Test: two idle taxis, one request: one taxi gets it, the other stays idle |
| 4 | 4 Nov | 80-20 policy lets go at 20% | `EightyTwentyPolicy.schedule()` sets the flag only while SoC < 0.2 (`scheduler/policies.py:53`), so a taxi leaves the charger as soon as it passes 20% | Keep the flag on while the taxi is TOCHARGE or CHARGING and SoC < 0.8 (read from `info`, so the policy stays stateless) | Test: a taxi at 50% that is CHARGING keeps the flag; at 80% it is released; an IDLE taxi at 50% gets no flag |
| 5 | 4 Nov | Repeatable runs (decision 1) | Jobs sit in Python sets, so tie-breaks change from run to run | Iterate the job pool in job-id order | Test: two 24-hour runs give identical metrics |
| 6 | 4 Nov | New baseline | | `make trace` on `chicago_v1g` after all fixes; keep `results/20261023-v1g-eightytwenty-baseline` as "before" | `results/<run-id>/` written; a before/after table (trips served, requests rejected, kWh charged, taxi-hours in RECOVERY, mean SoH, taxi zone changes); the live site shows taxis moving and chargers drawing power |
| 7 | 4 Nov | Slide material | | Before/after table; two screenshots from the live site (before, after); the audit table | Ready for the deck |

Order matters: bug 1's arrival check needs bug 2 (a taxi must be able to reach the charger's zone), and the baseline (6) needs all of 1 to 5.

## Decisions for Wei Yew

1. **Repeatable runs (step 5).** Sort the job pool by id (one fixed tie-break, runs repeat exactly), or keep sets and average every result over several runs. `docs/PLAN.md:30` allows either. Sorting is cheaper for the 5 Nov table; it changes which taxi gets a tied job, not how many jobs exist.
2. **If time runs out**, which steps can slip past 5 Nov? Suggested: 4 and 5 can slip; 1 and 2 are the slide.

## Not in P0

- Audit rows 3 to 7 (discharge, wear, reward, rate scale): P1.
- Fleet size (50 is hard-coded in `scheduler/policies.py:51` and `:83` to `:114`): a sensitivity question after P0.
- `audit_checks.py`: `CLAUDE.md` and `docs/PLAN.md` mention it, but it is not in the repo. The P0 tests replace it for rows 1 and 2.

## Risks

| Risk | Fallback |
| --- | --- |
| Fixing bug 2 changes trip costs a lot (every trip was costed from the start zone), so RECOVERY or rejections move in an unexpected direction | That is a finding, not a failure: report it in the table with the reason |
| A fix breaks the live site or the replay | `tests/test_viz.py` and `tests/test_live.py` run with every fix |
| Bug 1 needs more than the zone comparison (e.g. the charger's port assignment also misbehaves) | Stop after the failing test, show what the trace says, and decide together |
