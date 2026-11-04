# Research plan: a learned FDI attack on the taxi fleet scheduler, and a metered V2B defense

Proposal for the supervisor meeting, written 4 Nov 2026, revised the same day after the minutes asked for a false-data-injection (FDI) attack learned by reinforcement learning (RL), stated as a full Markov decision process (MDP) with an appropriate reward, that proves the current system assumes too much. This file is the revision. The attacker's budget, the stealth model, the reward weighting, the defence rule and the floor are the thesis; where this file recommends, it says so and gives the alternatives.

Locked on 4 Nov (meeting): the attack is false battery telemetry fooling the scheduler; the V2B settlement rule is the defence. Headline damage: lost V2B peak shaving (section 4).

Sources for every number: `data/chicago_demand.csv` (January 2019, 604,163 trips), `results/20261104-v1g-eightytwenty-p0` (post-P0 run), the OpenEI reference buildings for the [Chicago O'Hare TMY3 station](https://openei.org/datasets/files/961/pub/COMMERCIAL_LOAD_DATA_E_PLUS_OUTPUT/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3/), and `refs/` (Paper A Yuhas, Paper B Basumatary, the V2G/V2B review). All code numbers computed 4 Nov. Section 11 lists what could not be checked.

## In one minute

The published fleet scheduler (Paper A) decides which taxis charge, and at what rate, from each taxi's self-reported state of charge and state of health (`simulator/simulator.py:45`). It trusts those reports. Paper B shows the reports can be false and builds a detector, but only for the charging channel, one session at a time, as an alarm after the fact, with no discharge. This FYP asks what a determined attacker can do to that scheduler: model a false-data-injection attacker as an MDP, learn its policy with RL under a fixed budget and a stealth constraint set by Paper B's detector, and measure the damage. The damage is measured where discharge is cheap enough to happen at all: taxis running vehicle-to-building (V2B) discharge while they wait in the O'Hare queue. The attack erases the building peak shaving that honest taxis provide; the defence, settling dispatch and payment on metered delivered energy rather than on reports, puts most of it back.

## 1. The vulnerability: what the current system assumes

| System | What it assumes | Where | Why that is too much |
| --- | --- | --- | --- |
| Paper A scheduler | The reported `(SoH, SoC)` per taxi is the true battery state | `_get_obs` builds the observation from each battery and hands it to the policy, which acts on it (`simulator/simulator.py:45`, `scheduler/policies.py:50`) | In a real fleet those numbers come from each vehicle's own telemetry. Nothing checks them. A compromised taxi, or a tampered channel, reports whatever it likes |
| Paper A reward and dispatch | A taxi that says it is low charges; a taxi that says it is full is left to drive or discharge | The 80-20 policy charges when reported SoC < 0.2, holds until 0.8 (`scheduler/policies.py:55`) | False-low reports pull taxis to the ports (synchronised charging, grid stress, no V2B). False-high reports leave a taxi to drain into the 24 h RECOVERY reset (lost service, lost V2B) |
| Paper B detector | FDI happens on the charging user-input channel, one session at a time, and is caught after the session by a per-session energy screen | Paper B p9686-9691: a NARX network estimates the kWh delivered in a charging session; the reported demand is screened against it by interquartile range; 99.40% accuracy. Charging only | It cannot see a fleet-level attack that spreads small, plausible lies across many taxis and many ticks, and it has nothing to say about V2B discharge, where the attack suppresses peak shaving or diverts discharge payment |

"Assumes too much" is the result to produce, not an assertion. Section 1a is a first, fixed-attack proof of it; section 4's learned attack is the full one.

## 1a. Preliminary result: the attack surface is real (4 Nov)

A fixed, non-learned false-telemetry attack on the published 80-20 scheduler, run on the fixed simulator and the real January data (`results/20261104-fdi-demo`, commit `c35637e`, no model code changed). The attack is injected at the observation boundary (`experiments/fdi_demo.py`): for a compromised set of taxis, the SoC the policy sees is replaced before it acts. The honest run reproduces the P0 baseline exactly (16,591 trips, 0 RECOVERY), so the attack is the only thing moving the numbers.

| Compromised of 50 | Report empty (SoC=0): trips served | Report full (SoC=1): taxi-hours in RECOVERY |
| --- | --- | --- |
| 0 (honest) | 16,591 (100%) | 0 |
| 1 | 16,233 (98%) | 185 |
| 5 | 14,877 (90%) | 852 |
| 10 | 9,586 (58%) | 1,692 |
| 25 | 968 (6%) | 4,149 |

Two levers, the two ends of the attacker's action: reporting "empty" pins taxis to the chargers and collapses service (to 6% of honest trips at 25 compromised); reporting "full" leaves taxis uncharged until they drain into the 24 h RECOVERY reset (4,149 taxi-hours offline). Figure: `docs/figures/fdi-demo.png`. This is the fixed-attack floor the learned, stealthy attacker of section 4 must beat, and it already shows the scheduler trusts its telemetry with no check. (The grid-energy column in the results overstates real draw because of the station-logging bug in `CLAUDE.md`, so the figure uses only trips and RECOVERY, which that bug does not touch.)

## 2. Research question

**Can a reinforcement-learning adversary learn a false-data-injection attack that makes the fleet scheduler destroy the V2B peak shaving honest taxis provide, within a small budget and while staying inside a published FDI detector's tolerance, and does settling dispatch and payment on metered delivered energy restore it?**

| | Sub-question | Measured by | Figure | Phase |
| --- | --- | --- | --- | --- |
| SQ1 Attack | As a function of the budget (how many taxis are compromised) and the stealth bound on each lie, how much V2B peak shaving does the learned attack remove, against the rule scheduler and against the DNN scheduler, and how much more than a naive attack? | kW of peak shaving removed; grid stress and degradation reported alongside | Main attack figure: damage against budget | P2, P3 |
| SQ2 Evasion | Does the learned attack stay inside Paper B's detector while doing that damage? Where is the frontier between damage and detectability? | Damage against Paper B's screen score; share of attack ticks flagged | Evasion figure: damage against detection | P3 |
| SQ3 Defence | Does a scheduler that dispatches and pays on metered delivered energy, not on reports, shrink the damage, and by how much? | Peak shaving removed, trusting scheduler against metered scheduler, at each budget | Main defence figure | P4 |

The airport-queue V2B is the setting the damage is measured in, not a sub-question. Section 6 is why that setting is the right one.

## 3. Threat model and the MDP

**Threat model.** An operator runs the fleet scheduler. An attacker compromises a fixed subset C of the 50 taxis, the budget b = |C|, and controls the telemetry those taxis report each tick: the state of charge, the state of health, and the user-input energy demand of a charging session. The attacker cannot change physics (the true battery, the real charge and discharge) or the taxis it has not compromised. It wants to damage the operator while staying inside the tolerance of a deployed detector (Paper B). This is the standard observation-perturbation threat model of the state-adversarial MDP (Zhang et al. 2020; verify before citing), made concrete for battery telemetry.

**The MDP** (attacker). The scheduler is a fixed victim policy π_v this episode; the attacker policy π_a is learned.

| Element | Definition |
| --- | --- |
| State s_t | hour and weekday features; the true `(SoC, SoH)` of the compromised taxis; the building load L_t; the station power and the V2B dispatch last tick; a running detector score per compromised taxi |
| Action a_t | for each taxi i in C, the report to send this tick: SoC_i^report = clip(SoC_i^true + δ_{i,t}, 0, 1); SoH likewise; and the declared session energy. Bounded by \|δ\| ≤ Δ (the stealth bound) and required to move consistently with a real battery between ticks |
| Transition | the simulator steps: π_v reads the reports, dispatches charge and V2B discharge, the true batteries evolve under the real energy flows, demand replays, the detector updates |
| Reward r_t | r_t = D_t − λ·d_t. D_t is the damage: V2B peak shaving removed at tick t (headline), with grid stress, true degradation and diverted payment as alternates and as reported metrics. d_t is the detector score: how far the report sits from the energy-balance-feasible state the meter allows, screened as in Paper B. λ sweeps aggression against stealth |
| Discount, horizon | γ < 1 over an episode of one representative day or week (a full month is heavy to train over; section 9) |

The reward is appropriate because it encodes the attacker's real goal, damage, traded against the real constraint, staying undetected by the published detector. Dropping the λ·d_t term gives a loud attack that Paper B catches; a large λ gives a safe attack that does nothing. The interesting policy lives between, and the sweep over λ, b and Δ maps that out. That sweep is what makes the attack methodological rather than a single hand-built spike.

**Injection point in the code.** The attack is a wrapper around the observation: for taxis in C, replace the `(SoH, SoC)` the env hands the policy (`simulator/simulator.py:45`) with the attacker's report, and the session energy the charger reads. No model physics change. The meter the defence and detector use is the charger's actual delivered energy (`simulator/charger.py:128`).

**Victim is a swept axis**, which covers both readings of the minutes' phrase "FDI-create reinforcement learning". The attacker is always the RL agent. The victim is the 80-20 rule first (deterministic, no training, and fragility there is the sharper claim), then Paper A's DNN scheduler (the attack against a learned victim). The DNN victim needs audit rows 5 and 6 fixed first (section 7).

## 4. Headline damage, and why

Decided 4 Nov: D_t is **V2B peak shaving removed**, in kW below the honest-case shave (or the building's demand-charge bill). Reasons, from what this simulator can move in a one-month run:

- **Degradation barely moves in a month.** Mean SoH went 0.99877 to 0.99808 over all of January in the post-P0 run. Paper A needed five years to make degradation a headline. So degradation is a long-horizon sweep, not a one-month figure.
- **Grid stress is modest at O'Hare.** The O'Hare port block caps at 100 kW (10 ports x 10 kW) against a 500 kW station cap, so overload is a weak claim at this site. Keep grid stress as the second reported metric, the one that attacks Paper A on its own title ("grid stress").
- **Peak shaving has the largest, cleanest swing** and it is the V2B story the defence maps to one-for-one. Taxi discharge of 100 kW (more at 50 kW ports) is a real fraction of the 378 kW hotel peak.

If the supervisor prefers to lead with grid stress, that is the one knob: set D_t to the station or feeder power above a cap. Every run reports all four damage metrics whichever is the reward.

## 5. Why the answer is not known in advance

- **Attack strength against budget is unknown.** One compromised taxi out of 50 is 2% of the fleet but can occupy a V2B port for the building's whole peak. Whether damage rises linearly with b, or saturates once the ports are blocked, or needs a coordinated several, is what SQ1 measures.
- **The stealth frontier is unknown.** Paper B reports 99.40% accuracy on single sessions. Whether many small, slow, plausible lies across a fleet stay inside its interquartile screen while still removing peak shaving is exactly what is not known, and is SQ2.
- **Charge on arrival limits the attack and the defence both.** In the post-P0 run a taxi finishing a trip at O'Hare has a median SoC of 48% (10th percentile 20, 90th 73). It holds 13.6 kWh above a 30% floor on average; a quarter hold nothing above it. So a false-high report can only tip a taxi that was near the floor anyway. How much headroom the attacker has depends on the hour.
- **The defence may not be free.** Metering removes the attacker's lever but can only dispatch what the meter has seen, so it may react a tick late and shave slightly less even with honest taxis. Whether it keeps most of the honest shave is SQ3.

## 6. Why the airport-queue V2B is the testbed

The attack needs a setting where V2B discharge happens at all, and where its loss is worth measuring. The post-P0 run shows the city is not that setting and the airport is.

- **In the city, discharge costs a fare.** The 50 taxis turn away 97.0% of all requests and 98.6% of O'Hare's, so a free taxi always has a fare waiting. A taxi earns about $9 of fares an hour (0.45 trips an hour at the $20.45 mean fare), so an hour at a 10 kW city port costs about $0.90 per kWh in lost fares before energy or wear. No honest taxi would discharge in the city, so there is nothing for an attack to remove.
- **In the airport queue it does not.** A taxi in the O'Hare staging lot waits for its turn whatever it does; plugged in, it keeps its place and loses no fare. On January 2019 weekdays (21, leaving out New Year's Day and Martin Luther King Day) O'Hare had 2,589 pickups a day against 954 drop-offs, so most taxis leaving with a fare had driven out empty to wait. O'Hare fares are long ($52.08, 23.8 km on average) but light on energy: 4.1 kWh on average, 6.5 kWh at the 99th percentile, 9% of a 71.7 kWh pack. A queued taxi can give energy and still take its next fare, so honest V2B exists here, and the attack has something to destroy.
- **Timing lines up.** `docs/figures/ohare-timing-jan-weekdays.png` (built 4 Nov; P1's building-load class should regenerate it): O'Hare pickups and drop-offs against the office and hotel load, each divided by its own peak hour. The large office draws about 1 MW from 08:00 to 17:00; the large hotel peaks at 378 kW at 20:00, the hour O'Hare pickups peak. When each building peaks, and how many taxis are queued then, decides how much there is to shave and to attack.

January weekday averages, holidays left out (hour starting):

| Hour | O'Hare pickups | O'Hare drop-offs | Large office kW | Large hotel kW |
| --- | --- | --- | --- | --- |
| 00 | 88 | 6 | 294 | 143 |
| 04 | 3 | 14 | 311 | 128 |
| 08 | 56 | 49 | 1,051 | 292 |
| 12 | 107 | 64 | 915 | 200 |
| 16 | 154 | 81 | 1,035 | 215 |
| 20 | 258 | 22 | 579 | 378 |

## 7. Method

### 7.1 Build order

| Part | New or from the audit | What it does | Where |
| --- | --- | --- | --- |
| V2B discharge through the battery | Audit rows 3, 4, 7 | Discharge only at a V2B port, through `battery.discharge()`, with depth-based wear, and the port released on discharge | `simulator/simulator.py` step, `simulator/battery.py` |
| RL soundness | Audit rows 5, 6 | Pay the bonus on delivered energy, normalise the action scale, so a retrained DNN victim is meaningful | `simulator/simulator.py` reward, `scheduler/policies.py` |
| Energy accounting | Known problems in `CLAUDE.md` | Apply the 0.9 station efficiency; log delivered energy not the port's full hour; fix the demand reader's extra row | `simulator/charger.py`, `simulator/demand.py` |
| Building load | New | kW for the simulated hour, added to `info`; align by weekday and hour, not date | reads the OpenEI CSV |
| Airport queue | New | First-in first-out staging lot at zone 76; a taxi joins after an O'Hare drop-off or an empty drive out; it unplugs when it reaches the head | |
| Honest V2B scheduler | New, rule-based | Discharge plugged-in taxis while building load is above a threshold, never below a taxi's floor | the victim's V2B half |
| Telemetry attack wrapper | New | For taxis in C, replace the reported `(SoC, SoH)` and session energy before the policy reads them | around `_get_obs` |
| Detector | New, reimplements Paper B | Estimate delivered energy, screen the report by interquartile range; the stealth penalty d_t | a simple energy-balance screen first; the NARX version if time allows |
| Metered scheduler | New, the defence | Dispatch and pay on metered delivered energy, reject energy-infeasible reports | the defended victim |

### 7.2 Experiments

| | Experiment | Varies | Answers |
| --- | --- | --- | --- |
| E0 | Honest baseline | office, hotel; ports K in {5, 10, 20}, P in {10, 50} kW | The honest V2B peak shave, to attack and to defend |
| E1 | Naive attack | random and greedy false reports; budget b | The floor the learned attack must beat |
| E2 | Learned attack, rule victim | b, stealth Δ, λ | SQ1 against the 80-20 rule |
| E3 | Learned attack, DNN victim | same | SQ1 against a learned scheduler |
| E4 | Evasion | λ against Paper B's screen | SQ2: the damage-detectability frontier |
| E5 | Metered defence | trusting against metered, all budgets | SQ3: damage recovered |

Ten seeds per point (start zones, demand sampling, the compromised set). Every point traces to a `results/<run-id>/` folder with its config and commit.

### 7.3 Validation

- Energy balance: battery energy out x 0.9 = building energy in, within 1%.
- With K = 0 the building load equals the OpenEI input, hour for hour.
- The naive attack is weaker than the learned attack (else the learning is not doing anything).
- The detector flags a loud attack (λ = 0) and passes honest taxis.
- One unit test per new class, written to fail first, as in P0.

## 8. Work packages

Replaces P1 to P4 of `docs/PLAN.md` once agreed. P0 and the calendar anchors stay.

| Phase | Dates | Work | Done when | Output |
| --- | --- | --- | --- | --- |
| P1 RL-sound V2B testbed | 5 to 22 Nov | Audit rows 3 to 7; energy accounting; building load; airport queue; honest V2B scheduler | Energy balances within 1%; honest V2B shaves the hotel peak in a January run; DNN retrains without the scale bug | Figure 1: honest V2B, load with and without |
| Exams | 23 Nov to 4 Dec | No FYP work | | |
| P2 Attacker MDP | 7 Dec to 3 Jan | Telemetry wrapper; reward and detector screen; train PPO attacker against the 80-20 rule; E0 to E2 | E2 complete, learned attack beats naive, 10 seeds | Main attack figure, rule victim |
| P3 Learned victim and evasion | 4 to 17 Jan | DNN victim; E3; Paper B screen; E4 | The attack stays inside the screen while doing damage, or the frontier is drawn | Evasion figure |
| Interim report | 25 Jan (est.) | SQ1 and SQ2 | | |
| P4 Defence | 18 Jan to 28 Feb | Metered scheduler; E5; stretch: adversarial co-training of victim and attacker | The metered scheduler recovers most of the honest shave | Main defence figure |
| P5 Write-up | 1 to 21 Mar | | Submitted | Final report 22 Mar 2027 (est.) |

## 9. Decisions for the meeting

Thesis-level, options only, for the supervisor to set.

1. **Budget.** The compromised counts to sweep: 1, 2, 5, 10, 20 of 50? And is the compromised set fixed for the episode or re-drawn?
2. **Stealth model.** The bound Δ on each lie, and which channels the attacker controls: SoC telemetry only, SoH too, the session energy too.
3. **Detector.** Reimplement Paper B's NARX plus interquartile screen as the stealth penalty, or start with a plain energy-balance screen and add NARX only if time remains. The second is lighter and may be enough to show evasion.
4. **Headline victim.** The 80-20 rule, the DNN, or both, for the main figure. (The attacker is RL either way.)
5. **Defence rule.** Dispatch on metered state; pay on metered discharge; reject infeasible reports. Which combination, and does it also meter charging.
6. **Headline damage.** Lost peak shaving (recommended, section 4) or grid stress.
7. **The floor** a taxi keeps: 20% (where 80-20 charges), 29% (20% plus a 99th-percentile O'Hare fare), or a per-driver floor.
8. **Episode for RL.** A representative day, a week, or the month. Shorter trains faster; longer is more realistic. Recommended: a week for training, the month for the reported runs.

## 10. Related work

From `refs/` (page numbers there) and searches on 4 Nov. Read each before citing; verify the two RL-theory names from source.

- **Paper A, Yuhas et al. 2025** (`refs/`, p1-7): the scheduler this forks; 80-20 against an RL policy on NYC then Chicago taxi data; no V2G, that came with the fork. The system whose telemetry trust this attack breaks.
- **Paper B, Basumatary et al. 2025** (`refs/`, p9686-9694): an FDI detector for the EV charging user-input channel, NARX plus interquartile screen, 99.40% accuracy, charging only. The detector the attack must evade and the metering the defence extends to discharge. The "263 alarms for 196 attacks" from the old plan is not yet located in the paper; do not cite it until it is.
- **V2G/V2B review, Frattale Mascioli et al. 2025** (`refs/`, p631-632): why a taxi gives power to a building, peak shaving and load balancing.
- **State-adversarial MDP** (Zhang et al. 2020) and **adversarial attacks on RL policies via the observation** (Huang et al. 2017): the formal frame for perturbing what a policy sees. Verify titles and results before citing.
- **Lying EVs reporting false SoC** (Shafee et al. 2020, arXiv 2005.13813): prior false-report attack on charging coordination, detector-side. Prior art the learned, fleet-level, discharge-aware attack goes beyond.
- **Setting:** airport taxi queues ([Zhao et al., JFK, arXiv 2101.12043](https://arxiv.org/abs/2101.12043)); V2G at airports with parked cars ([Schiphol](https://repository.tudelft.nl/record/uuid:462d2fd3-b2c1-418d-a359-3c048192574a), [Oslo](https://www.nmbu.no/en/research/projects/nex2g-eng)); taxi V2G in cities ([Transport Policy 2025](https://ideas.repec.org/a/eee/trapol/v172y2025ics0967070x25003099.html)). None models an FDI attack on a taxi V2B queue.

## 11. Could not check on 4 Nov

- **O'Hare waits and the count of active taxis.** The shipped CSV has no Taxi ID (`scripts/chicago_cab_data_prep.py` drops it), so the queue length in each hour is unmeasured. The Chicago portal query was blocked by the shell hook on outbound requests carrying data. Download January 2019 from the [Taxi Trips dataset](https://data.cityofchicago.org/Transportation/Taxi-Trips-2013-2023-/wrvz-psew/about_data) in a browser, outside `data/`. Biggest risk: short waits mean a small resource to attack.
- **Paper B's detector reimplementation.** Whether the NARX plus interquartile screen can be rebuilt from the paper, or needs their data, is unknown until the paper is read in full. The energy-balance screen is the fallback stealth penalty.
- **The two RL-theory citations** (state-adversarial MDP, adversarial attacks on observations) are from memory; confirm from source before the report.
- **The building's 2019 demand charge** for the O'Hare feeder's rate class; until sourced, E5 sweeps it.

## 12. Slide outline for the meeting

1. **Title and question.** "A learned false-data-injection attack on an EV fleet scheduler, and a metered defence", with the question from section 2.
2. **P0 done.** The before and after table from `docs/P0_PLAN.md` (4,046 to 16,591 trips; 0 to 35,280 kWh charged; RECOVERY 3,809 taxi-hours to 0) and the two images in `docs/figures/`.
3. **The assumption.** Paper A acts on self-reported `(SoC, SoH)` (`simulator/simulator.py:45`); Paper B catches FDI but only on charging, per session, after the fact, and never on discharge. Nobody has built the learned attack.
4. **Preliminary result (already done).** `docs/figures/fdi-demo.png` (section 1a): a fixed false-telemetry attack on the published scheduler. Reporting 25 of 50 taxis "empty" collapses trips to 6% of honest; reporting them "full" forces 4,149 taxi-hours offline. The honest run reproduces the P0 baseline, so the lie is the only cause. The surface is real; the FYP learns the stealthy, optimal attack on it.
5. **The attack as an MDP.** `docs/figures/mdp-attacker.png` (editable source `docs/figures/mdp-attacker.drawio`): the attacker-environment loop with the state, action, transition and reward of section 3. This is the artifact the minutes asked for.
6. **Why it is methodological.** Budget, stealth against Paper B's detector, and beating a naive attack. The damage-against-budget and damage-against-detectability sketches.
7. **The defence.** Meter and settle on delivered energy, extending Paper B into the dispatch loop and to discharge; damage shrinks.
8. **The testbed.** The timing figure and the fare argument: why V2B at the airport queue is where this is measured (section 6).
9. **Plan, risks, and the decisions needed** (sections 8 and 9).
