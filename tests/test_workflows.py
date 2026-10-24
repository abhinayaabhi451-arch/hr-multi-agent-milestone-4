import threading
import time

import pytest

from memory.long_term import get_fact
from tools import mock_data
from workflows.definitions import build_engine
from workflows.engine import Step, Workflow, WorkflowEngine


def test_onboarding_runs_all_steps():
    run = build_engine().run("employee_onboarding", {"employee_id": "E001"})
    assert run["status"] == "succeeded"
    assert all(s["status"] == "succeeded" for s in run["steps"].values())
    assert get_fact("E001", "onboarding_workflow") == "complete"
    assert get_fact("E001", "it_accounts") == "provisioned"


def test_unknown_employee_fails_and_cancels_downstream():
    run = build_engine().run("employee_onboarding", {"employee_id": "NOPE"})
    assert run["status"] == "failed"
    assert run["steps"]["verify_employee"]["status"] == "failed"
    assert run["steps"]["record_completion"]["status"] == "cancelled"


def test_offboarding_revokes_access():
    run = build_engine().run("employee_offboarding", {"employee_id": "E003"})
    assert run["status"] == "succeeded"
    assert mock_data.EMPLOYEES["E003"]["status"] == "access_revoked"


def test_leave_approved_when_balance_enough():
    run = build_engine().run("leave_approval", {"employee_id": "E001", "leave_type": "annual", "days": 2})
    assert run["status"] == "succeeded"
    assert run["steps"]["approve_leave"]["status"] == "succeeded"
    assert run["steps"]["notify_manager"]["status"] == "succeeded"
    assert run["steps"]["reject_leave"]["status"] == "skipped"
    assert mock_data.LEAVE_BALANCES["E001"]["annual"] == 10


def test_leave_using_entire_balance_still_notifies():
    # regression: branch must use the recorded balance check, not live data
    run = build_engine().run("leave_approval", {"employee_id": "E001", "leave_type": "casual", "days": 4})
    assert run["steps"]["approve_leave"]["status"] == "succeeded"
    assert run["steps"]["reject_leave"]["status"] == "skipped"
    assert run["steps"]["notify_manager"]["status"] == "succeeded"


def test_leave_rejected_when_balance_short():
    run = build_engine().run("leave_approval", {"employee_id": "E003", "leave_type": "annual", "days": 10})
    assert run["steps"]["approve_leave"]["status"] == "skipped"
    assert run["steps"]["notify_manager"]["status"] == "skipped"
    assert run["steps"]["reject_leave"]["status"] == "succeeded"
    assert mock_data.LEAVE_BALANCES["E003"]["annual"] == 3


def test_missing_inputs_and_unknown_workflow():
    engine = build_engine()
    with pytest.raises(ValueError):
        engine.run("employee_onboarding", {})
    with pytest.raises(KeyError):
        engine.run("nope", {})


def test_independent_steps_run_in_parallel():
    def slow(_):
        time.sleep(0.3)

    wf = Workflow("par", "", (), [
        Step("a", slow), Step("b", slow), Step("c", slow),
        Step("d", lambda c: "x", depends_on=("a", "b", "c")),
    ])
    engine = WorkflowEngine()
    engine.register(wf)
    run = engine.run("par", {})
    assert run["status"] == "succeeded"
    assert run["duration_ms"] < 700  # sequential would be >= 900


def test_retry_then_succeed():
    calls = {"n": 0}

    def flaky(_):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    engine = WorkflowEngine()
    engine.register(Workflow("r", "", (), [Step("s", flaky, retries=2, retry_delay=0.01)]))
    run = engine.run("r", {})
    assert run["status"] == "succeeded"
    assert run["steps"]["s"]["attempts"] == 3


def test_failure_triggers_compensation_in_reverse():
    undone = []
    engine = WorkflowEngine()
    engine.register(Workflow("saga", "", (), [
        Step("one", lambda c: 1, compensate=lambda c: undone.append("one")),
        Step("two", lambda c: 2, depends_on=("one",), compensate=lambda c: undone.append("two")),
        Step("boom", lambda c: 1 / 0, depends_on=("two",)),
    ]))
    run = engine.run("saga", {})
    assert run["status"] == "rolled_back"
    assert undone == ["two", "one"]
    assert run["steps"]["boom"]["status"] == "failed"


def test_cycle_and_unknown_dependency_rejected():
    engine = WorkflowEngine()
    with pytest.raises(ValueError):
        engine.register(Workflow("c", "", (), [Step("a", lambda c: 1, depends_on=("b",)),
                                                Step("b", lambda c: 1, depends_on=("a",))]))
    with pytest.raises(ValueError):
        engine.register(Workflow("u", "", (), [Step("a", lambda c: 1, depends_on=("zzz",))]))


def test_background_start_returns_run_id():
    engine = build_engine()
    run_id = engine.start("employee_onboarding", {"employee_id": "E002"})
    for _ in range(50):
        if engine.get_run(run_id)["status"] != "running":
            break
        time.sleep(0.05)
    assert engine.get_run(run_id)["status"] == "succeeded"


def test_concurrent_runs_are_isolated():
    engine = build_engine()
    results = []
    def go(emp):
        results.append(engine.run("employee_onboarding", {"employee_id": emp})["status"])
    threads = [threading.Thread(target=go, args=(e,)) for e in ("E001", "E002", "E003") * 3]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results == ["succeeded"] * 9
