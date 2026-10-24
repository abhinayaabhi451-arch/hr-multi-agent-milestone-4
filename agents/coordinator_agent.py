"""Coordinator Agent (Milestone 3: Agent Coordination & Memory
Management).

This is the piece that turns four separate agents into a coordinated
system: it reads an incoming employee message, decides which
specialized agent owns that kind of request, and hands the message
off to it. This is the project's "communication mechanism for agent
collaboration" -- the Coordinator never answers HR questions itself,
it only routes.
"""

from langchain_core.prompts import ChatPromptTemplate
from core.llm_client import get_llm, extract_text

ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a routing classifier for an HR multi-agent system.
Given an employee's message, decide which single agent should handle it.
Respond with ONLY one word, exactly one of:
chatbot, onboarding, offboarding, maintenance

Routing guide:
- chatbot: general questions, FAQs, company policy questions not tied to a specific process
- onboarding: new hire document submission, training schedules, joining steps
- offboarding: resignation, exit interviews, access revocation, final settlement
- maintenance: leave requests, payroll queries, performance updates

Respond with only the one word, nothing else."""),
    ("human", "{query}")
])


# Milestone 4 optimization: obvious requests are routed by keyword
# without an LLM call (saves ~1 model round-trip and API quota per
# message). Anything ambiguous -- zero or several categories matched --
# still goes to the LLM classifier.
FAST_ROUTE_KEYWORDS = {
    "onboarding": ("onboard", "new hire", "joining", "orientation", "joining documents"),
    "offboarding": ("resign", "offboard", "exit interview", "last working day", "final settlement", "revoke access"),
    "maintenance": ("leave balance", "apply leave", "apply for leave", "take leave", "sick leave",
                    "annual leave", "casual leave", "payroll", "salary", "payslip"),
}


def fast_route(query: str):
    q = query.lower()
    hits = [route for route, words in FAST_ROUTE_KEYWORDS.items() if any(w in q for w in words)]
    return hits[0] if len(hits) == 1 else None


class CoordinatorAgent:
    VALID_ROUTES = ("chatbot", "onboarding", "offboarding", "maintenance")

    def __init__(self, agents: dict):
        """agents: dict mapping route name -> agent instance exposing .run(query)."""
        self.llm = get_llm()
        self.chain = ROUTER_PROMPT | self.llm
        self.agents = agents

    def route(self, query: str) -> str:
        quick = fast_route(query)
        if quick:
            return quick
        response = self.chain.invoke({"query": query})
        decision = extract_text(response.content).strip().lower()
        for valid in self.VALID_ROUTES:
            if valid in decision:
                return valid
        return "chatbot"  # safe fallback if the model answers oddly

    def handle(self, query: str):
        """Routes the query and returns (agent_name, response_text)."""
        route = self.route(query)
        agent = self.agents[route]
        return route, agent.run(query)
