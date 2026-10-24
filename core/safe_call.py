"""Wraps a call to an agent/coordinator so transient failures (brief
rate-limit bursts, timeouts, brief network errors) don't crash the
whole program. A DAILY quota exhaustion (Google's free-tier cap on
total requests per day) is detected separately and NOT retried --
retrying every few seconds against a multi-hour cooldown just wastes
time and still fails.
"""

import re
import time

TRANSIENT_HINTS = ("timeout", "timed out", "503", "502", "connection")

# Any retry delay at or above this many seconds is treated as a hard
# quota wall (daily cap), not a short burst limit -- don't retry.
DAILY_QUOTA_THRESHOLD_SECONDS = 120


def _extract_retry_seconds(message: str):
    """Pull a retry delay out of Google's error text, in whichever
    form it appears ('retryDelay': '56073s' or 'retry in 15h34m33s')."""
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", message)
    if m:
        return int(m.group(1))

    m = re.search(r"retry in\s+(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:[\d.]+s)?", message, re.IGNORECASE)
    if m and (m.group(1) or m.group(2)):
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        return hours * 3600 + minutes * 60

    return None


def _format_wait(seconds: int) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return f"about {hours}h {minutes}m"
    if minutes:
        return f"about {minutes} minute(s)"
    return f"about {seconds} second(s)"


def safe_call(fn, *args, retries=2, base_delay=3, **kwargs):
    """Call fn(*args, **kwargs). Returns the real result, or -- on
    failure -- an error message string. Never raises.
    """
    last_error = None

    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            message = str(exc)
            lower = message.lower()

            is_quota_exhausted = "resource_exhausted" in lower or "quota" in lower
            retry_seconds = _extract_retry_seconds(message) if is_quota_exhausted else None

            if is_quota_exhausted and retry_seconds and retry_seconds >= DAILY_QUOTA_THRESHOLD_SECONDS:
                return (
                    "The Gemini API's free daily request quota has been used up for this model. "
                    f"Google says to retry in {_format_wait(retry_seconds)}. "
                    "This resets automatically -- it isn't a bug in the code. "
                    "In the meantime: use Manual mode instead of Auto-routing (it uses fewer "
                    "requests per question), or switch to a different model/API key if you need "
                    "to keep testing today. See https://ai.google.dev/gemini-api/docs/rate-limits"
                )

            is_transient = any(h in lower for h in TRANSIENT_HINTS) or (
                "429" in message and not is_quota_exhausted
            )

            if not is_transient or attempt == retries:
                break

            wait = base_delay * (attempt + 1)
            print(f"[temporary error hit, retrying in {wait}s... ({attempt + 1}/{retries})]")
            time.sleep(wait)

    return (
        "Sorry, I couldn't get a response just now "
        f"({type(last_error).__name__}: {last_error})."
    )
