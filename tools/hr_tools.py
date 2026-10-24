"""LangChain tools that give agents access to simulated enterprise
systems (Milestone 2: Tool Integration & Intelligent Action Execution).

Each tool is a plain Python function decorated with @tool, which turns
it into something a Gemini model can choose to call during a chat
response (LangChain's "tool calling" / function-calling support).
Actions taken here also update the long-term memory store, so later
turns and other agents can see what happened.
"""

from langchain_core.tools import tool
from tools.mock_data import (
    EMPLOYEES,
    LEAVE_BALANCES,
    ONBOARDING_CHECKLIST,
    OFFBOARDING_CHECKLIST,
    POLICIES,
)
from memory.long_term import set_fact


@tool
def check_leave_balance(employee_id: str) -> str:
    """Look up an employee's current leave balance by employee ID (e.g. 'E001')."""
    balance = LEAVE_BALANCES.get(employee_id)
    if not balance:
        return f"No leave balance found for employee ID {employee_id}."
    return (
        f"Leave balance for {employee_id}: "
        f"{balance['annual']} annual, {balance['sick']} sick, {balance['casual']} casual days."
    )


@tool
def apply_leave(employee_id: str, leave_type: str, days: int) -> str:
    """Apply for leave for an employee. leave_type must be 'annual', 'sick', or 'casual'."""
    balance = LEAVE_BALANCES.get(employee_id)
    if not balance:
        return f"No record found for employee ID {employee_id}."
    leave_type = leave_type.lower()
    if leave_type not in balance:
        return f"Invalid leave type '{leave_type}'. Must be annual, sick, or casual."
    if balance[leave_type] < days:
        return f"Insufficient {leave_type} leave balance. Available: {balance[leave_type]} days."
    balance[leave_type] -= days
    set_fact(employee_id, "last_leave_request", f"{days} day(s) {leave_type} leave")
    return (
        f"Leave approved: {days} day(s) of {leave_type} leave for {employee_id}. "
        f"Remaining {leave_type} balance: {balance[leave_type]} days."
    )


@tool
def get_onboarding_checklist(employee_id: str) -> str:
    """Get the onboarding document/task checklist for a new employee."""
    set_fact(employee_id, "onboarding_checklist_sent", "yes")
    items = "\n".join(f"- {item}" for item in ONBOARDING_CHECKLIST)
    return f"Onboarding checklist for {employee_id}:\n{items}"


@tool
def get_offboarding_checklist(employee_id: str) -> str:
    """Get the offboarding/exit checklist for a departing employee."""
    set_fact(employee_id, "offboarding_checklist_sent", "yes")
    items = "\n".join(f"- {item}" for item in OFFBOARDING_CHECKLIST)
    return f"Offboarding checklist for {employee_id}:\n{items}"


@tool
def revoke_access(employee_id: str) -> str:
    """Revoke an exiting employee's system and email access."""
    employee = EMPLOYEES.get(employee_id)
    if not employee:
        return f"No employee record found for {employee_id}."
    employee["status"] = "access_revoked"
    set_fact(employee_id, "access_revoked", "yes")
    return f"System and email access revoked for {employee['name']} ({employee_id})."


@tool
def lookup_policy(topic: str) -> str:
    """Look up a general HR policy by topic, e.g. 'working hours', 'leave policy', 'remote work', 'dress code'."""
    topic_key = topic.lower().strip()
    for key, value in POLICIES.items():
        if key in topic_key or topic_key in key:
            return value
    return f"No policy found for '{topic}'. Available topics: {', '.join(POLICIES.keys())}."
