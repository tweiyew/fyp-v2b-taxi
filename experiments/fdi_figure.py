"""Slide figure from results/20261104-fdi-demo/sweep.csv.

Two panels, x = number of compromised taxis (of 50):
  (a) report 'empty': trips served and grid energy, each as % of the honest run.
  (b) report 'full': taxi-hours knocked into RECOVERY (honest = 0).

Run: PYTHONPATH=. .venv/bin/python -m experiments.fdi_figure
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = sys.argv[1] if len(sys.argv) > 1 else "results/20261104-fdi-demo/sweep.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "docs/figures/fdi-demo.png"

rows = list(csv.DictReader(open(CSV)))
def series(mode, key):
    pts = [(int(r["budget"]), float(r[key])) for r in rows if r["mode"] in (mode, "honest")]
    pts = sorted(set(pts))
    return [p[0] for p in pts], [p[1] for p in pts]

honest = next(r for r in rows if r["mode"] == "honest")
h_trips = float(honest["trips_completed"])
h_grid = float(honest["grid_energy_kwh"])

fx_t, f_trips = series("fake_low", "trips_completed")
mx_t, m_trips = series("mask_low", "trips_completed")
fx_r, f_recov = series("fake_low", "taxi_hours_in_recovery")
mx_r, m_recov = series("mask_low", "taxi_hours_in_recovery")

BLUE, ORANGE, RED = "#2a78d6", "#eb6834", "#b85450"
INK, INK2, MUTED, GRID, BASE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 11})
fig, (axa, axb) = plt.subplots(1, 2, figsize=(12.6, 5.4), dpi=200)
fig.patch.set_facecolor("#fcfcfb")

def dress(ax, xlab, ylab):
    ax.set_facecolor("#fcfcfb")
    ax.grid(axis="y", color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(BASE)
    ax.tick_params(colors=MUTED, labelcolor=INK2, length=0)
    ax.set_xlabel(xlab, color=INK2); ax.set_ylabel(ylab, color=INK2)

# Two attack modes, consistent colour per mode across both panels.
FAKE, MASK = BLUE, RED

# Panel a: trips served (% of honest)
axa.axhline(100, color=MUTED, lw=1, ls=(0, (4, 3)))
axa.plot(fx_t, [100 * v / h_trips for v in f_trips], "-o", color=FAKE, lw=2.2, ms=7, mec="#fcfcfb", mew=1.5, label="report 'empty' (SoC = 0)")
axa.plot(mx_t, [100 * v / h_trips for v in m_trips], "-o", color=MASK, lw=2.2, ms=7, mec="#fcfcfb", mew=1.5, label="report 'full' (SoC = 1)")
axa.text(fx_t[-1], 100 * f_trips[-1] / h_trips, f"  {100*f_trips[-1]/h_trips:.0f}%", color=FAKE, va="center", fontsize=10, fontweight="bold")
axa.text(mx_t[-1], 100 * m_trips[-1] / h_trips, f"  {100*m_trips[-1]/h_trips:.0f}%", color=MASK, va="center", fontsize=10, fontweight="bold")
axa.text(0.4, 101.5, "honest = 100", color=MUTED, fontsize=9, va="bottom")
axa.set_ylim(0, 112); axa.set_xlim(-1, 29)
dress(axa, "Compromised taxis (of 50)", "Trips served (% of honest run)")
axa.set_title("Service collapses when taxis are told to charge", color=INK, fontsize=12.5, fontweight="semibold", loc="left", pad=10)
leg = axa.legend(frameon=False, fontsize=10, loc="lower left")
for t in leg.get_texts():
    t.set_color(INK2)

# Panel b: taxi-hours knocked into RECOVERY
axb.plot(mx_r, m_recov, "-o", color=MASK, lw=2.2, ms=7, mec="#fcfcfb", mew=1.5, label="report 'full' (SoC = 1)")
axb.plot(fx_r, f_recov, "-o", color=FAKE, lw=2.2, ms=7, mec="#fcfcfb", mew=1.5, label="report 'empty' (SoC = 0)")
axb.text(mx_r[-1], m_recov[-1], f"  {int(m_recov[-1]):,}", color=MASK, va="center", fontsize=10, fontweight="bold")
axb.set_ylim(0, 4600); axb.set_xlim(-1, 29)
dress(axb, "Compromised taxis (of 50)", "Taxi-hours knocked into RECOVERY")
axb.set_title("Taxis drained offline when told they are full", color=INK, fontsize=12.5, fontweight="semibold", loc="left", pad=10)
leg2 = axb.legend(frameon=False, fontsize=10, loc="upper left")
for t in leg2.get_texts():
    t.set_color(INK2)

fig.suptitle("A fixed false-telemetry attack on the published 80-20 scheduler (Chicago, January, 50 taxis)",
             x=0.015, ha="left", fontsize=14, color=INK, fontweight="bold")
fig.text(0.015, 0.905, "The scheduler acts on each taxi's self-reported SoC and never checks it. Nothing but the number the policy is shown was changed. "
                       "results/20261104-fdi-demo.", fontsize=9.5, color=INK2, va="top")
fig.subplots_adjust(left=0.07, right=0.98, top=0.80, bottom=0.12, wspace=0.24)
fig.savefig(OUT, facecolor="#fcfcfb")
print("saved", OUT)
