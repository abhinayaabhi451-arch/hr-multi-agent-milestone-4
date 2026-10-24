"""Long-term knowledge store (Milestone 3: Agent Coordination & Memory
Management).

A lightweight, file-backed store that persists facts learned about
each employee across runs of the program, so agents can make
context-aware decisions instead of starting from zero every session.
A real deployment would swap this for a proper database; the JSON
file here keeps the concept visible and easy to inspect for the
project demo.
"""

import json
import os
from threading import Lock

# Override with KNOWLEDGE_STORE_PATH to point at a mounted persistent
# volume in cloud deployments (container disks are wiped on redeploy).
_STORE_PATH = os.getenv(
    "KNOWLEDGE_STORE_PATH",
    os.path.join(os.path.dirname(__file__), "knowledge_store.json"),
)
_lock = Lock()


_cache = None
_cache_mtime = None


def _load() -> dict:
    """Return the store, re-reading the file only when it changed on
    disk (Milestone 4 optimization: avoids a file read + JSON parse on
    every lookup)."""
    global _cache, _cache_mtime
    if not os.path.exists(_STORE_PATH):
        _cache, _cache_mtime = {}, None
        return _cache
    mtime = os.path.getmtime(_STORE_PATH)
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    with open(_STORE_PATH, "r", encoding="utf-8") as f:
        try:
            _cache = json.load(f)
        except json.JSONDecodeError:
            _cache = {}
    _cache_mtime = mtime
    return _cache


def _save(data: dict) -> None:
    """Atomic write (temp file + replace) so a crash or a concurrent
    reader never sees a half-written file."""
    global _cache, _cache_mtime
    tmp = _STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _STORE_PATH)
    _cache = data
    _cache_mtime = os.path.getmtime(_STORE_PATH)


def set_fact(employee_id: str, key: str, value: str) -> None:
    """Persist a fact about an employee, e.g. set_fact('E001', 'onboarding_checklist_sent', 'yes')."""
    with _lock:
        data = _load()
        data.setdefault(employee_id, {})[key] = value
        _save(data)


def get_fact(employee_id: str, key: str, default=None):
    with _lock:
        data = _load()
        return data.get(employee_id, {}).get(key, default)


def get_all_facts(employee_id: str) -> dict:
    with _lock:
        data = _load()
        return data.get(employee_id, {})
