"""In-process metrics for the monitoring dashboard (Milestone 4).

Thread-safe counters, latency samples and a ring buffer of recent
events. A production deployment would export the same numbers to
Prometheus/CloudWatch; the /metrics endpoint already emits them in
Prometheus text format so that swap needs no code changes here.
"""

import time
from collections import Counter, deque
from threading import Lock


class Metrics:
    def __init__(self, max_samples: int = 2000, max_events: int = 100):
        self._lock = Lock()
        self.started_at = time.time()
        self.requests = Counter()          # key: "route" or "agent:<name>"
        self.errors = Counter()
        self.latencies = {}                # key -> deque of seconds
        self.events = deque(maxlen=max_events)
        self.workflow_runs = Counter()     # key: "<workflow>:<status>"
        self._max_samples = max_samples

    def record(self, key: str, seconds: float, ok: bool = True, detail: str = "") -> None:
        with self._lock:
            self.requests[key] += 1
            if not ok:
                self.errors[key] += 1
            self.latencies.setdefault(key, deque(maxlen=self._max_samples)).append(seconds)
            self.events.appendleft({
                "time": time.strftime("%H:%M:%S"),
                "key": key,
                "ms": round(seconds * 1000, 1),
                "ok": ok,
                "detail": detail[:120],
            })

    def record_workflow(self, name: str, status: str) -> None:
        with self._lock:
            self.workflow_runs[f"{name}:{status}"] += 1

    @staticmethod
    def _percentile(sorted_vals, p):
        if not sorted_vals:
            return 0.0
        idx = min(len(sorted_vals) - 1, int(round(p / 100 * (len(sorted_vals) - 1))))
        return sorted_vals[idx]

    def snapshot(self) -> dict:
        with self._lock:
            per_key = {}
            for key, samples in self.latencies.items():
                vals = sorted(samples)
                per_key[key] = {
                    "count": self.requests[key],
                    "errors": self.errors[key],
                    "avg_ms": round(sum(vals) / len(vals) * 1000, 1),
                    "p50_ms": round(self._percentile(vals, 50) * 1000, 1),
                    "p95_ms": round(self._percentile(vals, 95) * 1000, 1),
                    "max_ms": round(vals[-1] * 1000, 1),
                }
            total = sum(self.requests.values())
            total_err = sum(self.errors.values())
            return {
                "uptime_seconds": round(time.time() - self.started_at, 1),
                "total_requests": total,
                "total_errors": total_err,
                "error_rate": round(total_err / total, 4) if total else 0.0,
                "by_key": per_key,
                "workflow_runs": dict(self.workflow_runs),
                "recent_events": list(self.events)[:25],
            }

    def prometheus(self) -> str:
        snap = self.snapshot()
        lines = [
            "# TYPE hr_uptime_seconds gauge",
            f"hr_uptime_seconds {snap['uptime_seconds']}",
            "# TYPE hr_requests_total counter",
        ]
        for key, s in snap["by_key"].items():
            lines.append(f'hr_requests_total{{key="{key}"}} {s["count"]}')
        lines.append("# TYPE hr_errors_total counter")
        for key, s in snap["by_key"].items():
            lines.append(f'hr_errors_total{{key="{key}"}} {s["errors"]}')
        lines.append("# TYPE hr_latency_p95_ms gauge")
        for key, s in snap["by_key"].items():
            lines.append(f'hr_latency_p95_ms{{key="{key}"}} {s["p95_ms"]}')
        lines.append("# TYPE hr_workflow_runs_total counter")
        for key, n in snap["workflow_runs"].items():
            name, status = key.rsplit(":", 1)
            lines.append(f'hr_workflow_runs_total{{workflow="{name}",status="{status}"}} {n}')
        return "\n".join(lines) + "\n"


metrics = Metrics()
