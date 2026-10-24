"""Load test for the HR platform API (Milestone 4).

Usage:
  python perf/load_test.py --url http://localhost:8000 --users 20 --requests 200
  python perf/load_test.py --url ... --scenario workflow
  python perf/load_test.py --url ... --api-key secret --max-p95-ms 1500   # exits 1 if SLO missed

Scenarios: chat (auto-routed chat), workflow (run workflows), mixed.
Reports throughput, error rate and latency percentiles.
"""

import argparse
import itertools
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

CHAT_MESSAGES = [
    "What are the working hours?",
    "What is my leave balance for E001?",
    "I want to resign, what is the process?",
    "Send me the onboarding checklist for E002",
    "Tell me about the remote work policy",
]
WORKFLOWS = [
    ("employee_onboarding", {"employee_id": "E001"}),
    ("leave_approval", {"employee_id": "E002", "leave_type": "casual", "days": 1}),
    ("employee_offboarding", {"employee_id": "E003"}),
]


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))] if vals else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=10, help="concurrent virtual users")
    ap.add_argument("--requests", type=int, default=100, help="total requests")
    ap.add_argument("--scenario", choices=["chat", "workflow", "mixed"], default="chat")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--max-p95-ms", type=float, default=None, help="fail (exit 1) if p95 exceeds this")
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    args = ap.parse_args()

    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    counter = itertools.count()

    def one(i):
        kind = args.scenario if args.scenario != "mixed" else ("chat" if i % 2 == 0 else "workflow")
        t0 = time.perf_counter()
        try:
            if kind == "chat":
                r = client.post("/api/chat", headers=headers, json={
                    "message": CHAT_MESSAGES[i % len(CHAT_MESSAGES)], "session_id": f"load-{i % args.users}"})
            else:
                name, body = WORKFLOWS[i % len(WORKFLOWS)]
                r = client.post(f"/api/workflows/{name}/run", headers=headers, json=body)
            ok = r.status_code == 200
        except Exception:
            ok = False
        return kind, time.perf_counter() - t0, ok

    limits = httpx.Limits(max_connections=args.users * 2)
    with httpx.Client(base_url=args.url, timeout=60, limits=limits) as client:
        client.get("/health").raise_for_status()
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.users) as pool:
            results = list(pool.map(one, range(args.requests)))
        wall = time.perf_counter() - start

    lat = [r[1] * 1000 for r in results]
    errors = sum(1 for r in results if not r[2])
    print(f"\nscenario={args.scenario} users={args.users} requests={args.requests}")
    print(f"  wall time     {wall:.2f}s")
    print(f"  throughput    {args.requests / wall:.1f} req/s")
    print(f"  errors        {errors} ({errors / args.requests:.1%})")
    print(f"  latency ms    avg {statistics.mean(lat):.0f} | p50 {pct(lat, 50):.0f} | "
          f"p95 {pct(lat, 95):.0f} | p99 {pct(lat, 99):.0f} | max {max(lat):.0f}")
    for kind in sorted({r[0] for r in results}):
        k = [r[1] * 1000 for r in results if r[0] == kind]
        print(f"    {kind:<9} n={len(k):<4} p50 {pct(k, 50):.0f} ms  p95 {pct(k, 95):.0f} ms")

    failed = errors / args.requests > args.max_error_rate or (
        args.max_p95_ms is not None and pct(lat, 95) > args.max_p95_ms)
    print("  RESULT        " + ("FAIL" if failed else "PASS"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
