"""Fake agents with simulated model latency, enabled with STUB_AGENTS=1.

Lets you load-test the platform itself (API, sessions, metrics,
workflows) without spending Gemini quota. Never use in production.
"""

import os
import random
import time

from agents.coordinator_agent import fast_route


class StubAgent:
    def __init__(self, name, latency=None):
        self.name = name
        self.latency = latency if latency is not None else float(os.getenv("STUB_LATENCY", "0.2"))

    def run(self, query):
        time.sleep(self.latency * random.uniform(0.7, 1.3))
        return f"[stub {self.name}] {query[:80]}"


class StubCoordinator:
    def __init__(self, agents):
        self.agents = agents

    def handle(self, query):
        route = fast_route(query) or "chatbot"
        return route, self.agents[route].run(query)


def stub_factory():
    agents = {n: StubAgent(n) for n in ("chatbot", "onboarding", "offboarding", "maintenance")}
    return {"agents": agents, "coordinator": StubCoordinator(agents)}
