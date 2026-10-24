"""Workflow orchestration engine (Milestone 4).

A workflow is a small DAG of steps. The engine:
  * runs steps whose dependencies are finished, in parallel where it can
  * retries a failing step with backoff
  * skips steps whose `condition` is false (conditional branching)
  * cancels downstream steps when a step fails for good, then runs the
    `compensate` action of already-completed steps in reverse order
    (the "saga" pattern, so a half-finished process gets rolled back)
  * records every step's status, timing and output so the API and the
    dashboard can show exactly what happened

Steps are plain Python callables, so a workflow can combine HR tools,
agent calls and any other service without the engine caring.
"""

import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from threading import Lock, Thread
from typing import Callable, Optional

from core.metrics import metrics


@dataclass
class Step:
    name: str
    fn: Callable[[dict], object]                  # fn(ctx) -> result
    depends_on: tuple = ()
    retries: int = 0
    retry_delay: float = 0.5
    condition: Optional[Callable[[dict], bool]] = None
    compensate: Optional[Callable[[dict], object]] = None


@dataclass
class Workflow:
    name: str
    description: str
    required_inputs: tuple
    steps: list = field(default_factory=list)

    def validate(self) -> None:
        names = {s.name for s in self.steps}
        if len(names) != len(self.steps):
            raise ValueError(f"{self.name}: duplicate step names")
        for s in self.steps:
            for d in s.depends_on:
                if d not in names:
                    raise ValueError(f"{self.name}: step '{s.name}' depends on unknown '{d}'")
        # cycle check (Kahn)
        remaining = {s.name: set(s.depends_on) for s in self.steps}
        while remaining:
            free = [n for n, deps in remaining.items() if not deps]
            if not free:
                raise ValueError(f"{self.name}: dependency cycle")
            for n in free:
                del remaining[n]
            for deps in remaining.values():
                deps.difference_update(free)


class WorkflowEngine:
    def __init__(self, max_workers: int = 8, max_runs_kept: int = 200):
        self._workflows = {}
        self._runs = OrderedDict()
        self._lock = Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="wf-step")
        self._max_runs_kept = max_runs_kept

    # ---- registry -------------------------------------------------
    def register(self, workflow: Workflow) -> None:
        workflow.validate()
        self._workflows[workflow.name] = workflow

    def list_workflows(self) -> list:
        return [
            {
                "name": w.name,
                "description": w.description,
                "required_inputs": list(w.required_inputs),
                "steps": [
                    {"name": s.name, "depends_on": list(s.depends_on), "retries": s.retries}
                    for s in w.steps
                ],
            }
            for w in self._workflows.values()
        ]

    def get_workflow(self, name: str) -> Optional[Workflow]:
        return self._workflows.get(name)

    # ---- run tracking ---------------------------------------------
    def get_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            run = self._runs.get(run_id)
            return _copy_run(run) if run else None

    def list_runs(self, limit: int = 20) -> list:
        with self._lock:
            runs = list(self._runs.values())[-limit:]
            return [_copy_run(r, summary=True) for r in reversed(runs)]

    def _new_run(self, workflow: Workflow, inputs: dict) -> dict:
        run = {
            "run_id": uuid.uuid4().hex[:12],
            "workflow": workflow.name,
            "status": "running",
            "inputs": dict(inputs),
            "started_at": time.time(),
            "finished_at": None,
            "duration_ms": None,
            "steps": {
                s.name: {"status": "pending", "attempts": 0, "output": None,
                         "error": None, "duration_ms": None}
                for s in workflow.steps
            },
        }
        with self._lock:
            self._runs[run["run_id"]] = run
            while len(self._runs) > self._max_runs_kept:
                self._runs.popitem(last=False)
        return run

    # ---- execution ------------------------------------------------
    def start(self, name: str, inputs: dict) -> str:
        """Run in the background; returns the run id immediately."""
        workflow, run = self._prepare(name, inputs)
        Thread(target=self._execute, args=(workflow, run), daemon=True).start()
        return run["run_id"]

    def run(self, name: str, inputs: dict) -> dict:
        """Run to completion and return the finished run record."""
        workflow, run = self._prepare(name, inputs)
        self._execute(workflow, run)
        return self.get_run(run["run_id"])

    def _prepare(self, name: str, inputs: dict):
        workflow = self._workflows.get(name)
        if workflow is None:
            raise KeyError(f"Unknown workflow '{name}'")
        missing = [k for k in workflow.required_inputs if not inputs.get(k)]
        if missing:
            raise ValueError(f"Missing required input(s): {', '.join(missing)}")
        return workflow, self._new_run(workflow, inputs)

    def _set(self, run, step_name, **updates):
        with self._lock:
            run["steps"][step_name].update(updates)

    def _run_step(self, step: Step, run: dict, ctx: dict):
        rec_name = step.name
        start = time.perf_counter()
        attempts = 0
        last_exc = None
        self._set(run, rec_name, status="running")
        for attempt in range(step.retries + 1):
            attempts = attempt + 1
            self._set(run, rec_name, attempts=attempts)
            try:
                output = step.fn(ctx)
                self._set(run, rec_name, status="succeeded", output=_jsonable(output),
                          duration_ms=round((time.perf_counter() - start) * 1000, 1))
                return True, output
            except Exception as exc:  # noqa: BLE001 - step failures are data, not crashes
                last_exc = exc
                if attempt < step.retries:
                    time.sleep(step.retry_delay * (attempt + 1))
        self._set(run, rec_name, status="failed", error=f"{type(last_exc).__name__}: {last_exc}",
                  duration_ms=round((time.perf_counter() - start) * 1000, 1))
        return False, None

    def _execute(self, workflow: Workflow, run: dict) -> None:
        t0 = time.perf_counter()
        ctx = {"inputs": dict(run["inputs"]), "results": {}}
        steps = {s.name: s for s in workflow.steps}
        done = {}            # name -> "succeeded" | "skipped"
        completed_order = []
        failed = False
        in_flight = {}       # future -> step

        def launchable():
            out = []
            for s in workflow.steps:
                st = run["steps"][s.name]["status"]
                if st != "pending" or any(s is x for x in in_flight.values()):
                    continue
                if all(d in done for d in s.depends_on):
                    out.append(s)
            return out

        while True:
            if not failed:
                for s in launchable():
                    # a step downstream of a skipped step is skipped too
                    if any(done[d] == "skipped" for d in s.depends_on):
                        self._set(run, s.name, status="skipped")
                        done[s.name] = "skipped"
                        continue
                    if s.condition is not None:
                        try:
                            go = bool(s.condition(ctx))
                        except Exception:  # noqa: BLE001
                            go = False
                        if not go:
                            self._set(run, s.name, status="skipped")
                            done[s.name] = "skipped"
                            continue
                    self._set(run, s.name, status="running")
                    fut = self._pool.submit(self._run_step, s, run, ctx)
                    in_flight[fut] = s
            if not in_flight:
                # nothing running: either finished, or newly-skipped steps unlocked more work
                if not failed and launchable():
                    continue
                break
            finished, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for fut in finished:
                step = in_flight.pop(fut)
                ok, output = fut.result()
                if ok:
                    ctx["results"][step.name] = output
                    done[step.name] = "succeeded"
                    completed_order.append(step)
                else:
                    failed = True

        status = "succeeded"
        if failed:
            status = "failed"
            for name, rec in run["steps"].items():
                if rec["status"] == "pending":
                    self._set(run, name, status="cancelled")
            for step in reversed(completed_order):
                if step.compensate is not None:
                    try:
                        step.compensate(ctx)
                        self._set(run, step.name, status="compensated")
                    except Exception as exc:  # noqa: BLE001
                        self._set(run, step.name, error=f"compensation failed: {exc}")
            if any(r["status"] == "compensated" for r in run["steps"].values()):
                status = "rolled_back"

        with self._lock:
            run["status"] = status
            run["finished_at"] = time.time()
            run["duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        metrics.record(f"workflow:{workflow.name}", time.perf_counter() - t0,
                       ok=(status == "succeeded"), detail=f"{run['run_id']} {status}")
        metrics.record_workflow(workflow.name, status)


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _copy_run(run: dict, summary: bool = False) -> dict:
    base = {k: v for k, v in run.items() if k != "steps"}
    steps = {n: dict(r) for n, r in run["steps"].items()}
    if summary:
        base["step_status"] = {n: r["status"] for n, r in steps.items()}
    else:
        base["steps"] = steps
    return base
