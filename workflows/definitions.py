"""Concrete HR workflows built on the engine (Milestone 4).

These call the same simulated enterprise tools the agents use, but
deterministically (no LLM), so a multi-step HR process runs the same
way every time and doesn't spend any model quota.
"""

from tools.mock_data import EMPLOYEES, LEAVE_BALANCES
from tools.hr_tools import (
    get_onboarding_checklist,
    get_offboarding_checklist,
    revoke_access,
    check_leave_balance,
    apply_leave,
)
from memory.long_term import set_fact
from workflows.engine import Step, Workflow, WorkflowEngine


def _employee(ctx) -> dict:
    emp_id = ctx["inputs"]["employee_id"]
    emp = EMPLOYEES.get(emp_id)
    if not emp:
        raise ValueError(f"Unknown employee {emp_id}")
    return emp


# ---------------- onboarding ----------------
def _build_onboarding() -> Workflow:
    emp_id = lambda ctx: ctx["inputs"]["employee_id"]  # noqa: E731
    return Workflow(
        name="employee_onboarding",
        description="Verify the new hire, then in parallel send the checklist, provision IT and book orientation; finally record completion.",
        required_inputs=("employee_id",),
        steps=[
            Step("verify_employee", lambda ctx: {"name": _employee(ctx)["name"]}),
            Step("send_checklist", lambda ctx: get_onboarding_checklist.invoke({"employee_id": emp_id(ctx)}),
                 depends_on=("verify_employee",), retries=1),
            Step("provision_it_accounts",
                 lambda ctx: (set_fact(emp_id(ctx), "it_accounts", "provisioned"), "IT accounts provisioned")[1],
                 depends_on=("verify_employee",), retries=1),
            Step("schedule_orientation",
                 lambda ctx: (set_fact(emp_id(ctx), "orientation", "scheduled"), "HR orientation scheduled")[1],
                 depends_on=("verify_employee",)),
            Step("record_completion",
                 lambda ctx: (set_fact(emp_id(ctx), "onboarding_workflow", "complete"), "Onboarding recorded")[1],
                 depends_on=("send_checklist", "provision_it_accounts", "schedule_orientation")),
        ],
    )


# ---------------- offboarding ----------------
def _build_offboarding() -> Workflow:
    emp_id = lambda ctx: ctx["inputs"]["employee_id"]  # noqa: E731

    def _restore_access(ctx):
        _employee(ctx)["status"] = "exiting"
        set_fact(emp_id(ctx), "access_revoked", "no")

    return Workflow(
        name="employee_offboarding",
        description="Send the exit checklist and revoke access in parallel, then process final settlement. A failure rolls back access revocation.",
        required_inputs=("employee_id",),
        steps=[
            Step("verify_employee", lambda ctx: {"name": _employee(ctx)["name"]}),
            Step("send_checklist", lambda ctx: get_offboarding_checklist.invoke({"employee_id": emp_id(ctx)}),
                 depends_on=("verify_employee",)),
            Step("revoke_access", lambda ctx: revoke_access.invoke({"employee_id": emp_id(ctx)}),
                 depends_on=("verify_employee",), compensate=_restore_access),
            Step("process_settlement",
                 lambda ctx: (set_fact(emp_id(ctx), "final_settlement", "processed"), "Final settlement processed")[1],
                 depends_on=("send_checklist", "revoke_access"), retries=1),
        ],
    )


# ---------------- leave approval ----------------
def _build_leave() -> Workflow:
    emp_id = lambda ctx: ctx["inputs"]["employee_id"]  # noqa: E731

    def _check(ctx) -> dict:
        i = ctx["inputs"]
        bal = LEAVE_BALANCES.get(i["employee_id"], {})
        enough = bal.get(str(i["leave_type"]).lower(), 0) >= int(i["days"])
        summary = check_leave_balance.invoke({"employee_id": i["employee_id"]})
        return {"sufficient": enough, "summary": summary}

    # Branch on the *recorded* result of check_balance, not live data, so
    # the decision can't change mid-run (approving leave lowers the balance).
    def _sufficient(ctx) -> bool:
        return bool(ctx["results"]["check_balance"]["sufficient"])

    def _reject(ctx):
        set_fact(emp_id(ctx), "last_leave_request", "rejected: insufficient balance")
        return "Leave rejected: insufficient balance"

    return Workflow(
        name="leave_approval",
        description="Check the balance; approve and notify if enough days remain, otherwise reject (conditional branch).",
        required_inputs=("employee_id", "leave_type", "days"),
        steps=[
            Step("verify_employee", lambda ctx: {"name": _employee(ctx)["name"]}),
            Step("check_balance", _check, depends_on=("verify_employee",)),
            Step("approve_leave",
                 lambda ctx: apply_leave.invoke({
                     "employee_id": emp_id(ctx),
                     "leave_type": ctx["inputs"]["leave_type"],
                     "days": int(ctx["inputs"]["days"]),
                 }),
                 depends_on=("check_balance",), condition=_sufficient),
            Step("notify_manager",
                 lambda ctx: "Manager notified of approved leave",
                 depends_on=("approve_leave",)),
            Step("reject_leave", _reject, depends_on=("check_balance",),
                 condition=lambda ctx: not _sufficient(ctx)),
        ],
    )


def build_engine() -> WorkflowEngine:
    engine = WorkflowEngine()
    for build in (_build_onboarding, _build_offboarding, _build_leave):
        engine.register(build())
    return engine
