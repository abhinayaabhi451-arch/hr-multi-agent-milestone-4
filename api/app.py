"""REST API for the HR multi-agent platform (Milestone 4).

Endpoints
  GET  /health                       liveness/readiness probe
  POST /api/chat                     auto-routed chat (Coordinator Agent)
  POST /api/agents/{agent}/chat      talk to one agent directly
  GET  /api/workflows                list available workflows
  POST /api/workflows/{name}/run     run a workflow (sync, or ?background=true)
  GET  /api/workflows/runs           recent runs
  GET  /api/workflows/runs/{run_id}  one run, step by step
  GET  /api/stats                    JSON metrics for the dashboard
  GET  /metrics                      Prometheus text format
  GET  /dashboard                    monitoring dashboard (HTML)
  GET  /docs                         interactive OpenAPI docs (FastAPI)

Each `session_id` gets its own agents, so short-term memory stays
per-user. Handlers are plain `def` functions, so FastAPI runs the
blocking LLM calls in its thread pool instead of freezing the server.
"""

import os
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from core.metrics import metrics
from core.safe_call import safe_call
from workflows.definitions import build_engine

AGENT_NAMES = ("chatbot", "onboarding", "offboarding", "maintenance")
DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str = Field("default", min_length=1, max_length=64)


class SessionStore:
    """Per-session agent sets, created lazily and evicted when idle."""

    def __init__(self, factory, ttl_seconds: int = 1800, max_sessions: int = 500):
        self._factory = factory
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._sessions = {}
        self._lock = Lock()

    def get(self, session_id: str):
        now = time.time()
        with self._lock:
            self._evict(now)
            entry = self._sessions.get(session_id)
            if entry is None:
                entry = {"bundle": self._factory(), "last": now}
                self._sessions[session_id] = entry
            entry["last"] = now
            return entry["bundle"]

    def _evict(self, now: float) -> None:
        for sid in [s for s, e in self._sessions.items() if now - e["last"] > self._ttl]:
            del self._sessions[sid]
        if len(self._sessions) >= self._max:
            oldest = min(self._sessions, key=lambda s: self._sessions[s]["last"])
            del self._sessions[oldest]

    def __len__(self):
        return len(self._sessions)


class RateLimiter:
    """Sliding-window limiter per client key (in-memory, per process)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                raise HTTPException(status_code=429, detail="Rate limit exceeded, slow down.")
            q.append(now)


def default_agent_factory():
    """Imported lazily: LangChain/Gemini imports are slow and need an API key."""
    from agents.chatbot_agent import ChatbotAgent
    from agents.onboarding_agent import OnboardingAgent
    from agents.offboarding_agent import OffboardingAgent
    from agents.maintenance_agent import MaintenanceAgent
    from agents.coordinator_agent import CoordinatorAgent

    agents = {
        "chatbot": ChatbotAgent(),
        "onboarding": OnboardingAgent(),
        "offboarding": OffboardingAgent(),
        "maintenance": MaintenanceAgent(),
    }
    return {"agents": agents, "coordinator": CoordinatorAgent(agents)}


def create_app(agent_factory=None, engine=None) -> FastAPI:
    app = FastAPI(title="HR Multi-Agent Platform", version="4.0.0")
    sessions = SessionStore(agent_factory or default_agent_factory)
    engine = engine or build_engine()
    limiter = RateLimiter(int(os.getenv("RATE_LIMIT_PER_MIN", "120")))
    app.state.engine = engine
    app.state.sessions = sessions

    def guard(request: Request, x_api_key: Optional[str] = Header(default=None)):
        required = os.getenv("API_KEY")
        if required and x_api_key != required:
            raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")
        limiter.check(request.client.host if request.client else "unknown")

    @app.get("/health")
    def health():
        return {"status": "ok", "active_sessions": len(sessions),
                "workflows": len(engine.list_workflows())}

    @app.post("/api/chat", dependencies=[Depends(guard)])
    def chat(req: ChatRequest):
        bundle = sessions.get(req.session_id)
        t0 = time.perf_counter()
        result = safe_call(bundle["coordinator"].handle, req.message)
        elapsed = time.perf_counter() - t0
        if isinstance(result, tuple):
            route, response = result
            metrics.record(f"route:{route}", elapsed, ok=True)
            return {"route": route, "response": response, "latency_ms": round(elapsed * 1000, 1)}
        metrics.record("route:error", elapsed, ok=False, detail=str(result))
        return {"route": None, "response": result, "latency_ms": round(elapsed * 1000, 1)}

    @app.post("/api/agents/{agent}/chat", dependencies=[Depends(guard)])
    def agent_chat(agent: str, req: ChatRequest):
        if agent not in AGENT_NAMES:
            raise HTTPException(404, f"Unknown agent '{agent}'. Choose from {AGENT_NAMES}")
        bundle = sessions.get(req.session_id)
        t0 = time.perf_counter()
        response = safe_call(bundle["agents"][agent].run, req.message)
        elapsed = time.perf_counter() - t0
        failed = response.startswith(("Sorry, I couldn't", "The Gemini API"))
        metrics.record(f"agent:{agent}", elapsed, ok=not failed, detail=response if failed else "")
        return {"agent": agent, "response": response, "latency_ms": round(elapsed * 1000, 1)}

    @app.get("/api/workflows", dependencies=[Depends(guard)])
    def list_workflows():
        return engine.list_workflows()

    @app.post("/api/workflows/{name}/run", dependencies=[Depends(guard)])
    def run_workflow(name: str, inputs: dict, background: bool = False):
        try:
            if background:
                return {"run_id": engine.start(name, inputs), "status": "running"}
            return engine.run(name, inputs)
        except KeyError as exc:
            raise HTTPException(404, str(exc).strip("'\""))
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/workflows/runs", dependencies=[Depends(guard)])
    def list_runs(limit: int = 20):
        return engine.list_runs(min(max(limit, 1), 100))

    @app.get("/api/workflows/runs/{run_id}", dependencies=[Depends(guard)])
    def get_run(run_id: str):
        run = engine.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    @app.get("/api/stats", dependencies=[Depends(guard)])
    def stats():
        snap = metrics.snapshot()
        snap["active_sessions"] = len(sessions)
        snap["recent_workflow_runs"] = engine.list_runs(10)
        return snap

    @app.get("/metrics", response_class=PlainTextResponse)
    def prometheus():
        return metrics.prometheus()

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return DASHBOARD_HTML.read_text(encoding="utf-8")

    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn api.app:app_factory --factory`."""
    if os.getenv("STUB_AGENTS") == "1":
        from api.stub import stub_factory
        return create_app(agent_factory=stub_factory)
    return create_app()
