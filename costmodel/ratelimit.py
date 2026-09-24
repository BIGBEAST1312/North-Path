"""A budget for the Gemini calls, so a public URL can't drain the key.

Two calls go out per page load that uses the assistant: one to parse the
sentence, one to summarise the shortlist. On a free-tier key that is a small
allowance, and a portfolio link is exactly the kind of thing someone reloads
fifty times to see what it does.

The ranking is never rate limited. It reads local JSON and costs nothing, so a
visitor who runs out of assistant calls still gets the actual tool — only the
sentence box and the summary go quiet. That is the same degradation as having
no API key at all, which the app already handles.

Deliberately in-memory: one Render instance, no database, and a counter that
resets on deploy is the right amount of machinery for this. If it ever runs on
more than one instance the limit becomes per-instance, which is stated in
DEPLOY.md rather than solved with Redis nobody needs.
"""
from __future__ import annotations

import os
import threading
import time

PER_VISITOR = int(os.environ.get("ASSISTANT_LIMIT_PER_VISITOR", "12"))
PER_HOUR = int(os.environ.get("ASSISTANT_LIMIT_PER_HOUR", "180"))
WINDOW = 3600.0

_lock = threading.Lock()
_hits: dict = {}      # visitor -> [timestamps]
_all: list = []       # every timestamp, for the global ceiling


def _prune(stamps: list, now: float) -> list:
    return [t for t in stamps if now - t < WINDOW]


def allow(visitor: str) -> bool:
    """True if this visitor may spend an assistant call right now."""
    now = time.time()
    with _lock:
        global _all
        _all = _prune(_all, now)
        if len(_all) >= PER_HOUR:
            return False
        stamps = _prune(_hits.get(visitor, []), now)
        if len(stamps) >= PER_VISITOR:
            _hits[visitor] = stamps
            return False
        stamps.append(now)
        _hits[visitor] = stamps
        _all.append(now)
        if len(_hits) > 5000:                     # keep the dict from growing forever
            for key in [k for k, v in _hits.items() if not _prune(v, now)]:
                _hits.pop(key, None)
        return True


def remaining(visitor: str) -> int:
    now = time.time()
    with _lock:
        return max(0, PER_VISITOR - len(_prune(_hits.get(visitor, []), now)))


def reset() -> None:
    """Tests only."""
    with _lock:
        _hits.clear()
        _all.clear()
