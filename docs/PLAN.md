# FYP Plan: CCDS26-0598

Exported 22 Oct 2026 from the claude.ai doc. This file is the working copy from now on; edit it here.

## Where the code stands

The fork runs one month of Chicago (744 hourly ticks) in about 30 seconds, but it cannot produce a V2B result yet. Two upstream bugs stop taxis from moving or plugging in. The fork's discharge skips the battery model. Rows 1 to 4 below are confirmed by full-month runs and single-taxi traces on 22 Oct (`audit_checks.py` reproduces them). Rows 5 to 8 come from reading the code.

**What the V2G fork adds over Yuhas et al.** (75 changed lines in [radityachema/simulasi-pengisian-taksi-listrik-v2g](https://github.com/radityachema/simulasi-pengisian-taksi-listrik-v2g) against [sccicitb/simulasi-pengisian-taksi-listrik](https://github.com/sccicitb/simulasi-pengisian-taksi-listrik)):

- An `enable_v2g` flag. The charge rate range becomes −10 to +10 kW, taken from the first station's port power in the Chicago configs.
- A negative rate lowers SoC directly at 90% efficiency and is counted in `total_grid_power`.
- A reward bonus of 0.05 × |rate| for idle taxis given a negative rate.
- Chicago January 2019 demand (604,163 trips), the Chicago map, V1G and V2G configs, and `run_experiment.sh` (PPO for 5,000 timesteps per run, about 7 episodes).
- Small fixes: the 80-20 flag value, the TRAIN/EVAL string match, CPU fallback, a zone filter on demand.

**What blocks V2B work**

| # | Problem | Where | Effect | Fix |
| --- | --- | --- | --- | --- |
| 1 | No taxi ever plugs in. `charge()` restarts the trip to the charger every tick, and its "arrived" check compares location objects, not zones. Batteries refill only through the 24 h RECOVERY reset at 0% SoC. | `vehicle.py` `charge()`, upstream too | V1G run: grid charging power 0 kW in all 744 ticks. About 5 of 50 taxis sit in RECOVERY at any time. A taxi parked in the charger's own zone drained from 15% to 0% in 5 ticks while marked CHARGING. | Compare zones; keep the trip timer when the target charger is unchanged |
| 2 | Taxis never move. `location` is set only in `__init__`. | `vehicle.py`, upstream too | 0 of 50 taxis changed zone in a month. Every trip is costed from the start zone. No taxi can drive to a building. | Set `location = destination` on arrival |
| 3 | Discharge has no place and skips the battery model. Any idle taxi anywhere can discharge. | `simulator.py` `step()` | V2B costs zero SoH. All 506 discharge commands in my test run came from taxis not at a charger. | Discharge only at a V2B port, through `battery.discharge()` |
| 4 | The degradation term uses SoC after the tick where Wan et al. use depth of discharge. | `battery.py` `recalculate_capacity()` | 10 kW discharge from 80%: hour 1 costs 0.000274 kWh of capacity, hour 4 costs 0.000003 kWh. Deep discharge looks almost free. | Depth-based stress per half-cycle |
| 5 | The bonus pays for a negative rate even when the charge flag is off. | `simulator.py` reward | PPO can collect it without discharging | Pay on delivered kWh |
| 6 | Rate scale mismatch. PPO trains in kW (±10), then `DnnPolicy` multiplies the output by 50 at eval. | `policies.py` | Eval rates are 50× the training scale | Normalise actions to [−1, 1] inside the env |
| 7 | A charging taxi told to discharge keeps its port request. | `step()` + `Vehicle.tick()` | Charges and discharges in the same tick | Disconnect on discharge |
| 8 | Two taxis can take the same job in one tick. | `get_closest_job()`, upstream too | Duplicate pickups; fewer distinct trips served | Drop a job from the pool once assigned |

**Runs are not repeatable.** Jobs sit in Python sets, so tie-breaks between equally close jobs change from run to run despite the fixed seeds. Three identical January runs served 3,900 to 4,054 trips. Sort the job pool by id in P0, or average every result over several runs.

**Eq. 1, settled.** The August brief flagged that Paper A's Eq. 1 fails as typeset. The code uses the form x^(1/α) with N_cref = 513, as the brief guessed. The bug is what x is: SoC after the tick, not depth of discharge (row 4).

**Not in the code at all (all FYP-new):** building load, a V2B site, a tariff or payment rule, driver agents, a reporting channel. The observation holds only SoC and SoH per taxi, so no policy can see the hour or the building peak.

## Research question (open, 4 Nov)

Not decided. The question has to pass four tests: the answer can't be guessed beforehand; someone would act on it; the data, the simulator and about four months can answer it; and nobody has answered it already (needs a literature check, not yet done).

The August question (do drivers misreport availability under a capacity payment, and does settling on delivered kWh fix it) fails the first test as stated: paying for declared availability invites over-declaring, and paying on delivery removes it. What it lacks is the trade-off: paying on delivery puts the risk on drivers, so fewer take part. The 4 Nov O'Hare check (risk table) adds that, as configured, a fare is always waiting, so lying would cost nearly all V2B energy whatever the rule.

| | Candidate | The unknown it measures | Main cost |
| --- | --- | --- | --- |
| Q1 | Which payment rule gets the most V2B energy to the building at its peak when drivers choose what availability to declare? | Where truthfulness and participation balance | Supply and demand at O'Hare must be balanced first |
| Q2 | How much of an airport-side building's peak can taxis waiting in the airport queue cover, and what does it cost them in fares? | Queue length against the load curve | A queue model; an operations result more than a mechanism one |
| Q3 | A driver in the airport queue knows roughly when they will reach the front; the building needs those departure times to plan discharge. Can a payment rule make drivers report them truthfully, and how much peak shaving does truth buy? | The value of eliciting private departure times | A queue model and the driver model |

To settle with Wei Yew: which question; how to balance supply and demand (risk table, O'Hare row); what "settle on delivered kWh" means, since flat per-kWh pay is ruled out below.

## Decisions locked

Run everything on the Chicago data that ships with the fork, with O'Hare as the demand hub and a building load from the same weather station. Four rows change the August proposal; they are marked.

| Decision | Choice | Why |
| --- | --- | --- |
| City and data **(changed)** | Chicago, January 2019, as shipped: 604,163 trips, 77 zones | Data and map already work, and a month runs in 30 s. Paper A's main runs used NYC with Chicago as its transfer test, so state the reason in the report: NYC needs the prep script rewritten for TLC's Parquet files, a 263-zone map build, and far more trips per tick to loop over. |
| Demand hub | O'Hare, zone 76 | 73,449 pickups in January (third busiest zone), mean trip 23.8 km, mean fare $52.10. Already a charger site in the configs. Taxis queue there and the next airport fare is the opportunity cost: the Changi argument with real data. |
| Building **(changed)** | OpenEI hourly profile, large office, [Chicago O'Hare TMY3 station](https://openei.org/datasets/files/961/pub/COMMERCIAL_LOAD_DATA_E_PLUS_OUTPUT/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3/) | Same place and climate as the trips. A tropical profile becomes one sensitivity run for the Singapore framing. If the office peak misses O'Hare's pickup peak, switch to the large hotel profile. |
| Tick | Keep 1 hour | Matches the hourly load profile. One month runs in about 30 s. |
| Scheduler | Rule-based peak shaving **(changed)** | The contribution is the payment mechanism, not RL. PPO only if P4 finishes early. |
| Payment rule | Capacity + energy split (from August) | Under flat per-kWh pay every driver leaves and there is no equilibrium. |
| Detection | Cite Paper B's numbers (from August) | Frees time for the fix. |
| Driver cost **(changed)** | Built around lost fares and range for the next fare | Battery wear is near zero here: a 4-hour, 10 kW session costs 0.00039 kWh of capacity, 0.003% of the 20% fade the logger treats as end of life. One O'Hare trip uses about 4.1 kWh at 17.1 kWh/100 km. The rational lie is a discharge floor padded for that. |

Withdrawn from August: the check that a 60–65% depth optimum "appears on its own". With this battery code the cost of each extra hour of discharge falls with depth, so no interior optimum can appear. Fixing row 4 of the audit changes this, but fare loss will likely still dominate.

Load profile source: [Commercial and Residential Hourly Load Profiles for all TMY3 Locations](https://catalog.data.gov/dataset/commercial-and-residential-hourly-load-profiles-for-all-tmy3-locations-in-the-united-state-bbc75) (16 DOE commercial prototypes, hourly). The catalogue lists it as superseded by the End-Use Load Profiles dataset; its known errors are in the residential files.

## Work packages

The August phases P0 to P5 stay, with the same goals. P0 grows: it now means fixing the base simulator, not just running it. By the August schedule you would be in P3 this week; in practice P0 starts now.

| Phase | Work | Done when | Output for the report |
| --- | --- | --- | --- |
| P0 Fix the base simulator | Audit bugs 1, 2 and 8. Make the 80-20 policy hold the charge flag until 80% SoC (today it lets go at 20%). One unit test per fix. | In the January V1G run, charging power is nonzero and taxis change zones. RECOVERY stays near zero. | Baseline table: trips served, kWh charged, mean SoH after one month |
| P1 V2B site and building | A bidirectional port block at zone 76, with port power set on purpose: the shipped config gives zone 76 10 kW ports, Paper A used 50 kW. A building-load class that reads the OpenEI CSV. Discharge only at the V2B port, through the battery, with depth-based wear (bugs 3 to 7). Rule-based peak shaving: plugged-in taxis discharge while building load is above a threshold. Hour and building load added to `info`. Honest drivers. | V2B cuts the weekday peak in a January run, and battery energy out matches building energy in after the 90% efficiency, to within 1% | Figure 1: building load with and without V2B, weekday average |
| P2 Driver model and reporting channel | Each driver declares an availability window and a discharge floor, ported from Paper B's user-input channel. Utility = capacity payment + energy payment − expected lost fares − wear − low-range penalty. Best report found by search over a grid of reports, no RL. One driver first. | One driver's best report moves with the price ratio in a way you can explain in a sentence: not "always max lie", not "never lie" | Figure 2: misreport size against the capacity-to-energy price ratio |
| P3 Shortfall at peak | The full fleet with rational drivers on January data. V2B delivered at building peak, honest against rational. Show rational reports fall inside the honest spread; cite Paper B's 263 alarms for 196 attacks. | The main figure exists | Main figure: V2B at peak falls as the incentive to misreport grows |
| P4 Payment rule fix | Settle on delivered kWh. Rerun P3 under the new rule. | The new rule recovers most of the honest-case V2B at peak without any detector | Figure 4: V2B at peak under strategic drivers, old rule against new |
| P5 Write-up | Interim report, final report, paper draft | Submitted | |

**P0 tasks, in order**

- [ ] Branch the fork (`fyp-v2b`) and do the agent setup in "Running the work with agents" (half a day)
- [x] `Vehicle.tick()`: set `location = destination` on every arrival (bug 2)
- [x] `Vehicle.charge()`: compare zones, and keep the trip timer when the target charger is unchanged (bug 1)
- [x] 80-20 policy: hold the charge flag until SoC reaches 0.8
- [x] `get_closest_job()`: skip jobs already assigned this tick (bug 8)
- [x] Rerun January with V1G and record the baseline table (4 Nov: `docs/P0_PLAN.md`, As built)
- [ ] Send Raditya the audit table and the questions at the end of this file

## Timeline

P0 runs to 1 Nov. Experiments freeze on 28 Feb. The final report is estimated for Mon 22 Mar 2027.

| Item | Dates |
| --- | --- |
| P0 Fix base simulator | 22 Oct to 1 Nov 2026 |
| Group presentation | 5 Nov 2026 (pending confirmation) |
| P1 V2B site + building | 2 Nov to 22 Nov 2026 |
| Sem 1 exams (est.), no FYP work | 23 Nov to 4 Dec 2026 |
| P2 Driver model | 7 Dec 2026 to 3 Jan 2027 |
| P3 Shortfall at peak | 4 Jan to 17 Jan 2027 |
| BuildSys 2027 deadline (est.), skipped | 22 Jan 2027 |
| Interim report (est.) | 25 Jan 2027 |
| P4 Payment rule fix | 18 Jan to 28 Feb 2027 |
| P5 Final report writing | 1 Mar to 21 Mar 2027 |
| **Final report due (est.)** | **22 Mar 2027** |
| Amended report, paper draft | 23 Mar to 16 Apr 2027 |

The P0 baseline is your implementation slide on 5 Nov; build the deck on 2 to 4 Nov. Exam weeks carry no FYP work.

- **NTU dates are estimates.** AY2026/27 FYP dates are not online. I applied the [AY2024/25 pattern](https://www3.ntu.edu.sg/scse/fyp/ViewImportantDates/Dates%20Aug%202024.pdf) (interim in Sem 2 week 3, final in week 10, amended report on week 13's Friday, orals in May) to a Sem 2 start of Mon 11 Jan 2027 from a [third-party calendar](https://acadcalendar.com/ntu-academic-calendar/). Check NTULearn and move the rows if they differ.
- **Skip BuildSys 2027.** The 2026 paper deadline was [22 Jan 2026](https://www.myhuiban.com/conference/1783.md) for a June conference in Banff, [co-located with e-Energy](https://berl.me.columbia.edu/news/buildsys-2026-bring-together-global-research-smart-and-sustainable-built-environments). If 2027 repeats that, P4 will not exist by the deadline, and P4 is what BuildSys wants. Draft the paper from the final report in April and pick the venue with Raditya.

## Running the work with agents

Use Claude Code on your branch for code changes, which is where P0 and P1 lose time. Keep the modelling decisions and every claim in the report for yourself. No task goes to an agent without a check it can run, so tests come before code.

The loop, with two human gates and one test gate:

1. **You** write the task and its check.
2. **Implementer** (a Claude Code session) does the work.
3. **Tests pass?** No: the implementer fixes and reruns. Yes: go on.
4. **Reviewer** (a fresh-context subagent) reports gaps against this plan and the audit.
5. **You** read the diff and merge.
6. **Sweep script** (`run.py` over configs, no LLM) runs the experiments.
7. **`results/`** holds metrics and the commit id. You read it and decide the next task.

Agents write and fix code. Plain scripts run the experiments, so every result reruns without an LLM.

**What to hand off**

| Phase | Hand to the agent | Keep for yourself | The check |
| --- | --- | --- | --- |
| P0 | Fixes for audit rows 1, 2 and 8; the 80-20 policy | Approving each diff | `pytest` passes; the month run charges energy and taxis change zones |
| P1 | OpenEI loader, V2B port class, energy accounting, the Figure 1 plot | Port power, peak threshold, building type | Energy balance within 1%; one test per new class |
| P2 | The best-response search and the one-driver plots | The utility function and payment rule, written on paper first | The code matches your hand-worked best report on three test cases |
| P3 | Sweep configs, the sweep script, a draft of the main figure | What the figure claims | Every point traces to a `results/` folder, 10 seeds per point |
| P4 | The new rule in code, the same sweeps | Which rule | Same as P3 |
| P5 | Draft methods text from the code; a number check on your drafts | The argument, and every claim about Paper A or B | A reviewer subagent matches each number in the draft to a results file |

**Setup** (state on 4 Nov)

- [x] Claude Code in the repo, with a project `CLAUDE.md` (gitignored). Work happens on `main`; the `fyp-v2b` branch was not made.
- [x] Tests under `tests/` (50 on 4 Nov). `audit_checks.py` never existed; each P0 fix got a test that failed first instead.
- [x] One config in, one `results/<run-id>/` out: `make trace` (`viz/trace.py`) in place of `run.py`. A sweep script over many configs is still needed for P3.
- [ ] Put the three papers as text in `refs/` so agents can search them.
- [ ] Add two subagents in `.claude/agents/`: `reviewer` (read-only tools; checks a diff against this plan and the audit) and `paper-checker` (read-only; checks any sentence about Paper A or B against `refs/`).
- [ ] Optional: a Stop hook that runs `pytest -q`, so no session ends on a failing suite.

**One task, start to finish** (the loop P0 used, 3 to 4 Nov)

1. The agent reads the code and states what is wrong, with file and line.
2. It writes a test, runs it, and shows it failing on today's code.
3. It shows the fix as a diff. You approve or reject; nothing is applied before that.
4. It applies the fix, runs the whole suite, and commits that fix alone.
5. It runs a January month in memory and compares with the last baseline. A surprise is investigated before moving on: in P0, bug 2's fix exposed bug 1 (drives over an hour never ended) and bug 1's exposed bug 8 (98% of busy taxi-hours on shared jobs).
6. Push when `main` is in a sound state, not between dependent fixes.
7. Record the run with `make trace` from a clean tree, then summarise `results/` into a table.

A `/goal` stop condition (`/goal tests/test_<name>.py passes and no other test file changed`) and the reviewer subagent fit steps 2 to 4 for unattended work; P0 ran interactively without them.

**Guardrails**

- No sentence about Paper A or B enters the report without a page number. The paper-checker verifies it.
- The utility function, the payment rules and the thresholds are the thesis. An agent can propose; you decide.
- A figure enters the report only if its `results/` folder exists and reruns to the same numbers.
- After two failed corrections in one session, `/clear` and rewrite the task.
- A metric that moves the wrong way after a fix is explained from the trace before it goes in a table (e.g. the 80-20 fix raised trips because charging sessions fell from 2,443 to 645).

Docs: [best practices](https://code.claude.com/docs/en/best-practices), [subagents](https://code.claude.com/docs/en/sub-agents), [/goal](https://code.claude.com/docs/en/goal), [non-interactive runs](https://code.claude.com/docs/en/headless).

## Risks and fallbacks

The biggest risk is P2 producing a trivial equilibrium. The project still stands after P3, as in August: P4 can shrink to one rule change and one figure.

| Risk | You will know by | Fallback |
| --- | --- | --- |
| P2 equilibrium is trivial: every driver lies the maximum or never lies | The one-driver check, 20 Dec | Switch to the commitment-window rule from August, or add driver types that value fares differently |
| The public code is not what produced the paper, so the paper's numbers cannot be matched | Raditya's answer to question 1 | Report your fixed simulator as your baseline. The fixes become a short methods section, which is a contribution in its own right |
| More upstream bugs surface during P0 | V1G run on 1 Nov | Happened: duplicate pickups were fixed after all (they hid 86% of trips: 2,212 completed before the fix, 15,672 after); station energy logging and the demand reader are noted in `docs/P0_PLAN.md` and left for later |
| Supply is far below demand: 98.6% of O'Hare requests go unserved and a fare is always waiting, so V2B always costs a sure fare and the honest-vs-lying comparison is degenerate (found 4 Nov) | Now | Wei Yew to choose: A, model the O'Hare taxi queue; B, a bigger fleet (remove the hard-coded 50); C, give the 50 taxis their fleet's share of the trips; D, keep it and accept a degenerate comparison |
| The office peak misses the hours taxis dwell at O'Hare | First P1 plot | Large hotel profile, or move the V2B window to the evening |
| January is winter, so an examiner asks about cooling peaks | Interim report feedback | The tropical-profile sensitivity run. A July 2019 Chicago month only if P4 is done |
| P1 slips past exams | 22 Nov | Cut P1 to one V2B site, one fixed discharge rate and one threshold rule. Nothing later needs more |

## Questions for Raditya

Send these with the audit table this week. Question 1 decides whether P0 is a fix or a rediscovery.

1. Is there a newer or private version of the simulator? In the public upstream repo and in the V2G fork, no taxi ever reaches a charger (audit row 1), so the paper's charging results cannot come from that code as it stands.
2. Do the fixes go back into your fork as pull requests, or stay on my branch?
3. Is Chicago with O'Hare as the hub acceptable in place of NYC, with the building load from the O'Hare weather station and a tropical profile as a sensitivity run?
4. Is a rule-based scheduler acceptable for the FYP, with PPO dropped unless time remains?
5. Which venue after the FYP, given that BuildSys 2027's deadline will likely fall before P4 is done?
