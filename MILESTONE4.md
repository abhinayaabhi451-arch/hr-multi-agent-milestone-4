# Milestone 4: Workflow Automation & Deployment

## What was added

| Requirement | Where |
|---|---|
| Complex workflow orchestration | `workflows/engine.py` (DAG engine), `workflows/definitions.py` (3 HR workflows) |
| APIs | `api/app.py` (FastAPI, OpenAPI docs at `/docs`) |
| Monitoring dashboard | `api/dashboard.html` at `/dashboard`, `core/metrics.py`, Prometheus text at `/metrics` |
| Cloud deployment | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.github/workflows/ci.yml` |
| Performance testing & optimization | `perf/load_test.py`, `api/stub.py`, caching + fast routing (below) |

## Workflow engine

Each workflow is a DAG of steps. The engine provides:
- **Parallel execution** of independent steps (onboarding sends the checklist, provisions IT and books orientation at the same time)
- **Retries** with backoff per step
- **Conditional branching** (leave approval: approve + notify, or reject, based on the recorded balance check); skips propagate to downstream steps
- **Failure handling**: dependents are cancelled and completed steps' `compensate` actions run in reverse (saga rollback; e.g. offboarding restores access)
- **Run tracking**: every run records per-step status, attempts, output and timing

Workflows: `employee_onboarding`, `employee_offboarding`, `leave_approval`. They use the same tools as the agents but are deterministic (no LLM), so they cost no model quota.

## Run locally

```bash
pip install -r requirements.txt
uvicorn api.app:app_factory --factory --reload
# http://localhost:8000/docs  (try the API)
# http://localhost:8000/dashboard  (monitoring)
```

Examples:
```bash
curl -X POST localhost:8000/api/chat -H "Content-Type: application/json" \
     -d '{"message":"What is my leave balance for E001?","session_id":"demo"}'
curl -X POST localhost:8000/api/workflows/leave_approval/run -H "Content-Type: application/json" \
     -d '{"employee_id":"E001","leave_type":"annual","days":2}'
curl -X POST "localhost:8000/api/workflows/employee_onboarding/run?background=true" \
     -H "Content-Type: application/json" -d '{"employee_id":"E002"}'   # returns run_id; poll /api/workflows/runs/{id}
```

If `API_KEY` is set, add `-H "X-API-Key: <key>"` (the dashboard has a key field).

## Deploy

**Docker (any cloud VM / Cloud Run / ECS / Azure Container Apps):**
```bash
docker compose up --build        # uses .env, persists memory in a volume
```
**Render (simplest free option):** push the repo to GitHub, then *New > Blueprint*; `render.yaml` configures it. Set `GOOGLE_API_KEY` in the dashboard. Free instances sleep when idle and have no persistent disk, so long-term memory resets on redeploy (use a paid disk mounted at `/data`, or a database).

Never commit `.env`; keys go in the platform's secret settings.

## Performance testing

```bash
STUB_AGENTS=1 RATE_LIMIT_PER_MIN=0 uvicorn api.app:app_factory --factory --port 8000
python perf/load_test.py --url http://localhost:8000 --users 20 --requests 200 --scenario mixed --max-p95-ms 1500
```
`STUB_AGENTS=1` replaces Gemini with fake 200 ms agents, so you measure the platform itself without spending quota.

Results from the sandbox (stub agents, 200 ms simulated model latency, no errors in any run):

| Scenario | Users | Throughput | p50 | p95 |
|---|---|---|---|---|
| chat | 20 | 91 req/s | 206 ms | 258 ms |
| workflow | 20 | 202 req/s | 91 ms | 180 ms |
| mixed | 40 | 256 req/s | 149 ms | 260 ms |

Platform overhead on chat is about 6 to 60 ms on top of the simulated model time, so real latency will be dominated by Gemini.

## Optimizations made

1. **Keyword fast-routing** in the Coordinator: unambiguous requests ("I want to resign", "leave balance") skip the LLM routing call, saving one model round-trip and one unit of API quota per message. Ambiguous ones still go to the LLM.
2. **Long-term memory cache**: the JSON store is re-read only when the file changes, and written atomically. 5,000 lookups: 18 ms vs 132 ms (about 7x).
3. **Parallel workflow steps** on a shared thread pool.
4. **Per-session agents with idle eviction** and thread-pool request handling, so slow LLM calls don't block other users.
5. **Rate limiting and API-key auth** to protect model quota.

## Known limits (honest notes)

- Sessions, metrics and workflow run history live in process memory: run **one worker** per container, and expect them to reset on restart. Scaling out needs Redis/a database for that state.
- The knowledge store is a JSON file; use a real database for production.
- The Docker image and Render blueprint were written but not built/deployed in the authoring sandbox (no Docker there); test the first deploy.
