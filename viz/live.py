"""Run the simulator in a worker process and collect its hourly frames for the live site.

One run at a time. The worker sends events back through a queue:
  ("start", header)   trace header plus run id, settings and the episode length
  ("frame", frame)    one simulated hour, the same fields as a trace.json row plus its time
  ("done", metrics)   after results/<run-id>/ has been written
  ("failed", message) the worker failed; nothing is saved
The server appends ("stopped", ...) itself when Stop ends a run; nothing is saved then either.

A separate process keeps the simulator's hourly stdout prints and its random seeding out of
the server, and lets Stop end a run at once.
"""

import json
import multiprocessing
import os
import queue
import re
import threading
import traceback
from typing import Dict, List, Optional, Tuple

import yaml

from viz.trace import (
    default_run_id,
    episode_hours,
    make_policy,
    provenance,
    record,
    with_hours,
    write_run,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "configs")
RESULTS_DIR = os.path.join(ROOT, "results")
LENGTHS = [("1 day", 24), ("1 week", 168)]
FINAL = ("done", "failed", "stopped")
RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunError(ValueError):
    """A request the page made that cannot be run."""


def runnable_configs(config_dir: str = CONFIG_DIR, root: str = ROOT) -> Dict[str, Dict]:
    """Configs whose map and demand files exist, by name, with their episode length in hours."""
    found = {}
    for filename in sorted(os.listdir(config_dir)):
        name, ext = os.path.splitext(filename)
        if ext != ".yaml":
            continue
        with open(os.path.join(config_dir, filename)) as fp:
            config = yaml.safe_load(fp)
        if all(os.path.isfile(os.path.join(root, config[key])) for key in ("city", "demand")):
            found[name] = {"path": os.path.relpath(os.path.join(config_dir, filename), root), "hours": episode_hours(config)}
    return found


def weight_files(root: str = ROOT) -> List[str]:
    """DNN policy weights (.pt) in the repo, skipping hidden folders, data and results."""
    skip = {"data", "results", "node_modules"}
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip]
        found += [os.path.relpath(os.path.join(folder, f), root) for f in files if f.endswith(".pt")]
    return sorted(found)


def options() -> Dict:
    configs = runnable_configs()
    weights = weight_files()
    return {
        "configs": [{"name": n, **c} for n, c in configs.items()],
        "policies": [
            {"name": "EIGHTYTWENTY", "label": "80-20 rule", "available": True},
            {
                "name": "DNN",
                "label": "Trained policy (DNN)",
                "available": bool(weights),
                "weights": weights,
                "reason": None if weights else "No .pt weights file in the repo",
            },
        ],
        "lengths": [{"label": label, "hours": hours} for label, hours in LENGTHS],
    }


def saved_runs(results_dir: str = RESULTS_DIR) -> List[Dict]:
    """Recorded runs in results/, newest first, with the metrics the list shows."""
    runs = []
    if not os.path.isdir(results_dir):
        return runs
    for run_id in os.listdir(results_dir):
        folder = os.path.join(results_dir, run_id)
        if not (RUN_ID.match(run_id) and os.path.isfile(os.path.join(folder, "trace.json"))):
            continue
        try:
            with open(os.path.join(folder, "metrics.json")) as fp:
                metrics = json.load(fp)
        except (OSError, ValueError):
            continue
        runs.append({"run_id": run_id, **metrics})
    return sorted(runs, key=lambda r: (r.get("created") or "", r["run_id"]), reverse=True)


def saved_run_dir(run_id: str, results_dir: str = RESULTS_DIR) -> str:
    """The folder of a saved run, looked up in the listing, never built from the id alone."""
    if run_id not in {r["run_id"] for r in saved_runs(results_dir)}:
        raise KeyError(run_id)
    return os.path.join(results_dir, run_id)


def _worker(config: Dict, policy: str, weights: Optional[str], run_dir: str, source: Dict, events) -> None:
    os.chdir(ROOT)
    try:
        result = record(
            config,
            make_policy(policy, weights),
            on_start=lambda header: events.put(("start", header)),
            on_hour=lambda time, frame: events.put(("frame", {"time": time, **frame})),
        )
        write_run(result, config, run_dir, source)
        events.put(("done", {**source, **result["metrics"]}))
    except Exception as exc:  # reported to the page; the traceback goes to the server's stderr
        traceback.print_exc()
        events.put(("failed", f"{type(exc).__name__}: {exc}"))


class LiveRun:
    """One run: its worker process and every event it has sent, kept for late listeners."""

    def __init__(self, run_id: str, settings: Dict, process, events) -> None:
        self.run_id = run_id
        self.settings = settings
        self.process = process
        self._queue = events
        self.events: List[Tuple[str, Dict]] = []
        self._cond = threading.Condition()
        threading.Thread(target=self._pump, daemon=True).start()

    @property
    def finished(self) -> bool:
        with self._cond:
            return bool(self.events) and self.events[-1][0] in FINAL

    def _append(self, kind: str, data) -> None:
        with self._cond:
            if self.events and self.events[-1][0] in FINAL:
                return
            self.events.append((kind, data))
            self._cond.notify_all()

    def _pump(self) -> None:
        while not self.finished:
            try:
                kind, data = self._queue.get(timeout=0.5)
            except queue.Empty:
                if not self.process.is_alive() and not self.finished:
                    self._append("failed", f"The simulator stopped without finishing (exit code {self.process.exitcode})")
                continue
            if kind == "start":
                data = {**data, **self.settings}
            self._append(kind, data)

    def wait(self, since: int, timeout: float) -> Tuple[List[Tuple[str, Dict]], bool]:
        """Events from index <since> on, waiting up to <timeout> s for one; and whether the run is over."""
        with self._cond:
            self._cond.wait_for(lambda: len(self.events) > since, timeout=timeout)
            over = bool(self.events) and self.events[-1][0] in FINAL
            return self.events[since:], over

    def stop(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(5)
        self._append("stopped", {"run_id": self.run_id})


class RunManager:
    def __init__(self, results_dir: str = RESULTS_DIR) -> None:
        self.results_dir = results_dir
        self.current: Optional[LiveRun] = None
        self._lock = threading.Lock()
        self._ctx = multiprocessing.get_context("spawn")

    def start(self, config_name: str, policy: str, hours: Optional[int], weights: Optional[str] = None) -> LiveRun:
        configs = runnable_configs()
        if config_name not in configs:
            raise RunError(f"Unknown config {config_name!r}; choose one of {', '.join(configs)}")
        policy = str(policy).upper()
        if policy == "EIGHTYTWENTY":
            weights = None
        elif policy == "DNN":
            if weights not in weight_files():
                raise RunError("The DNN policy needs one of the .pt weights files in the repo")
        else:
            raise RunError(f"Unknown policy {policy!r}")
        path = configs[config_name]["path"]
        with open(os.path.join(ROOT, path)) as fp:
            config = yaml.safe_load(fp)
        full = episode_hours(config)
        if hours is not None:
            if not isinstance(hours, int) or isinstance(hours, bool) or not 1 <= hours <= full:
                raise RunError(f"Length must be a whole number of hours from 1 to {full}")
            if hours < full:
                config = with_hours(config, hours)
        total = episode_hours(config)

        with self._lock:
            if self.current and not self.current.finished:
                raise RuntimeError(f"Run {self.current.run_id} is still going; stop it first")
            run_id = default_run_id(path, policy) + ("" if total == full else f"-{total}h")
            source = provenance(run_id, path, policy, weights)
            events = self._ctx.Queue()
            process = self._ctx.Process(
                target=_worker,
                args=(config, policy, weights, os.path.join(self.results_dir, run_id), source, events),
                daemon=True,
            )
            process.start()
            settings = {"run_id": run_id, "config": path, "policy": policy, "weights": weights, "total_hours": total}
            self.current = LiveRun(run_id, settings, process, events)
            return self.current

    def get(self, run_id: str) -> Optional[LiveRun]:
        run = self.current
        return run if run and run.run_id == run_id else None

    def shutdown(self) -> None:
        if self.current and not self.current.finished:
            self.current.stop()
