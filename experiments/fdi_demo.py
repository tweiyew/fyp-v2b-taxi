"""Preliminary FDI vulnerability demo: a fixed false-telemetry attack on the
published 80-20 scheduler, on the fixed simulator and the real January data.

This is NOT the learned attacker of docs/RESEARCH_PLAN.md (that is the FYP). It
is the proof that the attack surface is real: the scheduler acts on each taxi's
self-reported SoC (scheduler/policies.py:54, from simulator/simulator.py:45), and
nothing checks it. We compromise a fixed set C of taxis and replace the SoC the
policy sees for them, changing physics nowhere.

Two fixed lies, the two ends of the attacker's action:
  mask_low  report SoC = 1.0  -> the policy never charges them -> they drain into
            the 24 h RECOVERY reset -> service collapses.
  fake_low  report SoC = 0.0  -> the policy keeps them at the charger -> grid
            energy is wasted and they serve no fares.

No model code is edited: the attack is a wrapper around the policy, injected at
the observation boundary, exactly as the MDP's action is (docs/figures/mdp-attacker.png).

Run: PYTHONPATH=. .venv/bin/python -m experiments.fdi_demo
"""
import argparse
import csv
import os
import random

import numpy
import yaml

from scheduler.policies import EightyTwentyPolicy
from viz.trace import record, with_hours, provenance, write_run


class FalseTelemetryPolicy:
    """Wraps a scheduler and lies about the SoC of the compromised taxis.

    The true observation is left untouched; only the copy the inner policy sees
    is changed, so the env steps the real batteries while the scheduler reacts to
    the lie.
    """

    def __init__(self, inner, compromised, reported_soc):
        self.inner = inner
        self.compromised = list(compromised)
        self.reported_soc = reported_soc

    def schedule(self, observation, info):
        obs = observation.copy()
        for v in self.compromised:
            obs[v, 1] = self.reported_soc
        return self.inner.schedule(obs, info)


MODES = {
    "honest": None,
    "mask_low": 1.0,   # report full: never charged, drains to RECOVERY
    "fake_low": 0.0,   # report empty: stuck at the charger
}


def run_one(config, mode, budget):
    """One reproducible episode. Reseeding before each run fixes the start zones
    and demand, so the only difference between runs is the injected lie."""
    random.seed(0)
    numpy.random.seed(0)
    compromised = range(budget)
    policy = EightyTwentyPolicy()
    if mode != "honest" and budget > 0:
        policy = FalseTelemetryPolicy(policy, compromised, MODES[mode])
    return record(config, policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-c", "--config", default="configs/chicago_v1g.yaml")
    parser.add_argument("--hours", type=int, help="shorten the episode for a quick check")
    parser.add_argument("--budgets", default="0,1,5,10,25")
    parser.add_argument("--out", default="results/20261104-fdi-demo")
    args = parser.parse_args()

    with open(args.config) as fp:
        config = yaml.safe_load(fp)
    if args.hours:
        config = with_hours(config, args.hours)

    budgets = [int(b) for b in args.budgets.split(",")]
    os.makedirs(args.out, exist_ok=True)

    rows = []
    base = run_one(config, "honest", 0)["metrics"]
    rows.append(("honest", 0, base))
    print(f"\n{'mode':10s} {'b':>3s} {'trips':>7s} {'rejected':>9s} {'grid kWh':>9s} "
          f"{'recov h':>8s} {'meanSoH':>8s}")
    print("-" * 62)

    def show(mode, b, m):
        print(f"{mode:10s} {b:3d} {m['trips_completed']:7d} {m['requests_rejected']:9d} "
              f"{m['grid_energy_kwh']:9.0f} {m['taxi_hours_in_recovery']:8d} {m['mean_final_soh']:8.5f}")

    show("honest", 0, base)
    for mode in ("mask_low", "fake_low"):
        for b in budgets:
            if b == 0:
                continue
            m = run_one(config, mode, b)["metrics"]
            rows.append((mode, b, m))
            show(mode, b, m)

    csv_path = os.path.join(args.out, "sweep.csv")
    with open(csv_path, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["mode", "budget", "trips_completed", "requests_rejected",
                    "grid_energy_kwh", "taxi_hours_in_recovery", "mean_final_soh"])
        for mode, b, m in rows:
            w.writerow([mode, b, m["trips_completed"], m["requests_rejected"],
                        m["grid_energy_kwh"], m["taxi_hours_in_recovery"], m["mean_final_soh"]])
    print(f"\nwrote {csv_path}")


if __name__ == "__main__":
    main()
