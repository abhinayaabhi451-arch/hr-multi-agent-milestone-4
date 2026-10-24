import pytest
from fastapi.testclient import TestClient

from agents.coordinator_agent import fast_route
from api.app import create_app


class StubAgent:
    def __init__(self, name): self.name = name
    def run(self, q): return f"{self.name} says: {q}"


class StubCoordinator:
    def __init__(self, agents): self.agents = agents
    def handle(self, q):
        route = "maintenance" if "leave" in q else "chatbot"
        return route, self.agents[route].run(q)


def stub_factory():
    agents = {n: StubAgent(n) for n in ("chatbot", "onboarding", "offboarding", "maintenance")}
    return {"agents": agents, "coordinator": StubCoordinator(agents)}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    return TestClient(create_app(agent_factory=stub_factory))


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_auto_routed_chat(client):
    r = client.post("/api/chat", json={"message": "check my leave", "session_id": "s1"})
    assert r.status_code == 200
    assert r.json()["route"] == "maintenance"


def test_direct_agent_chat_and_unknown_agent(client):
    assert client.post("/api/agents/onboarding/chat", json={"message": "hi"}).json()["agent"] == "onboarding"
    assert client.post("/api/agents/bogus/chat", json={"message": "hi"}).status_code == 404


def test_validation_rejects_empty_message(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_workflow_endpoints(client):
    assert {w["name"] for w in client.get("/api/workflows").json()} >= {"employee_onboarding", "leave_approval"}
    r = client.post("/api/workflows/employee_onboarding/run", json={"employee_id": "E001"})
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    run_id = r.json()["run_id"]
    assert client.get(f"/api/workflows/runs/{run_id}").json()["workflow"] == "employee_onboarding"
    assert client.get("/api/workflows/runs").json()[0]["run_id"] == run_id
    assert client.post("/api/workflows/nope/run", json={}).status_code == 404
    assert client.post("/api/workflows/employee_onboarding/run", json={}).status_code == 422
    assert client.get("/api/workflows/runs/missing").status_code == 404


def test_stats_metrics_and_dashboard(client):
    client.post("/api/chat", json={"message": "hello"})
    stats = client.get("/api/stats").json()
    assert stats["total_requests"] >= 1 and "by_key" in stats
    assert "hr_requests_total" in client.get("/metrics").text
    page = client.get("/dashboard")
    assert page.status_code == 200 and "HR Platform Monitor" in page.text


def test_api_key_enforced(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "0")
    c = TestClient(create_app(agent_factory=stub_factory))
    assert c.get("/health").status_code == 200            # probes stay open
    assert c.get("/api/stats").status_code == 401
    assert c.get("/api/stats", headers={"X-API-Key": "secret"}).status_code == 200


def test_rate_limit(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    c = TestClient(create_app(agent_factory=stub_factory))
    codes = [c.get("/api/workflows").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_sessions_are_separate(client):
    client.post("/api/chat", json={"message": "a", "session_id": "one"})
    client.post("/api/chat", json={"message": "b", "session_id": "two"})
    assert client.get("/health").json()["active_sessions"] == 2


@pytest.mark.parametrize("text,expected", [
    ("I want to resign", "offboarding"),
    ("what is my leave balance", "maintenance"),
    ("onboarding documents please", "onboarding"),
    ("what are the working hours", None),
    ("resign and check my salary", None),   # ambiguous -> LLM decides
])
def test_fast_route(text, expected):
    assert fast_route(text) == expected
