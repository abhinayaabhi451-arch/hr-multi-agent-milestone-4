"""Simulated enterprise data stores for Milestone 2 (Tool Integration).

In a real deployment these would be replaced by calls to actual HR
systems (HRIS, payroll, document management, access control, etc.).
For this project they are simple in-memory dictionaries that behave
like a lightweight enterprise database, so the agents have something
real to call through LangChain tools.
"""

EMPLOYEES = {
    "E001": {"name": "Riya Sharma", "department": "Engineering", "status": "active"},
    "E002": {"name": "Arjun Mehta", "department": "Sales", "status": "active"},
    "E003": {"name": "Kavya Nair", "department": "Design", "status": "exiting"},
}

LEAVE_BALANCES = {
    "E001": {"annual": 12, "sick": 6, "casual": 4},
    "E002": {"annual": 8, "sick": 5, "casual": 2},
    "E003": {"annual": 3, "sick": 2, "casual": 1},
}

ONBOARDING_CHECKLIST = [
    "Submit government ID proof",
    "Submit educational certificates",
    "Complete bank account details form",
    "Attend HR orientation session",
    "Complete IT security & compliance training",
]

OFFBOARDING_CHECKLIST = [
    "Schedule exit interview with HR",
    "Return company laptop and ID badge",
    "Revoke system and email access",
    "Process full and final settlement",
    "Complete knowledge transfer / handover",
]

POLICIES = {
    "working hours": "Standard working hours are 9:00 AM to 5:00 PM, Monday to Friday, with a one-hour lunch break.",
    "leave policy": "Employees accrue 12 annual leave days, 6 sick leave days, and 4 casual leave days per year.",
    "remote work": "Employees may work remotely up to 2 days per week with manager approval.",
    "dress code": "Business casual is expected in the office; client-facing roles should dress formally.",
}
