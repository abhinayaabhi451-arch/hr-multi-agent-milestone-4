import workflows.definitions as defs
from memory.long_term import get_fact
from tools import mock_data
from tools.workflow_tools import run_offboarding_workflow, run_onboarding_workflow


def test_onboarding_workflow_tool_succeeds():
    out = run_onboarding_workflow.invoke({"employee_id": "E001"})
    assert "employee_onboarding' succeeded" in out
    for step in ("verify_employee", "send_checklist", "provision_it_accounts",
                 "schedule_orientation", "record_completion"):
        assert f"- {step}: succeeded" in out
    assert "Submit government ID proof" in out          # checklist shown under Details
    assert get_fact("E001", "onboarding_workflow") == "complete"
    assert get_fact("E001", "it_accounts") == "provisioned"


def test_onboarding_accepts_lowercase_id():
    assert "succeeded" in run_onboarding_workflow.invoke({"employee_id": " e002 "})


def test_onboarding_unknown_employee_fails_and_cancels_rest():
    out = run_onboarding_workflow.invoke({"employee_id": "NOPE"})
    assert "failed" in out and "Unknown employee NOPE" in out
    assert "- record_completion: cancelled" in out


def test_empty_employee_id_is_reported_not_raised():
    out = run_onboarding_workflow.invoke({"employee_id": "  "})
    assert out.startswith("Could not run the employee_onboarding workflow")


def test_offboarding_workflow_tool_succeeds():
    out = run_offboarding_workflow.invoke({"employee_id": "E003"})
    assert "employee_offboarding' succeeded" in out
    assert "revoked for Kavya Nair" in out and "Final settlement processed" in out
    assert mock_data.EMPLOYEES["E003"]["status"] == "access_revoked"
    assert get_fact("E003", "final_settlement") == "processed"


def test_offboarding_unknown_employee_fails():
    out = run_offboarding_workflow.invoke({"employee_id": "E999"})
    assert "failed" in out and "Unknown employee E999" in out
    assert "- process_settlement: cancelled" in out


def test_offboarding_failure_rolls_back_access(monkeypatch):
    real_set_fact = defs.set_fact

    def failing(emp, key, value):
        if key == "final_settlement":
            raise RuntimeError("payroll system down")
        return real_set_fact(emp, key, value)

    monkeypatch.setattr(defs, "set_fact", failing)
    out = run_offboarding_workflow.invoke({"employee_id": "E003"})
    assert "rolled_back" in out and "- revoke_access: compensated" in out
    assert "payroll system down" in out
    assert mock_data.EMPLOYEES["E003"]["status"] == "exiting"
