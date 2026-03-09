"""Token bucket rate limiter for API calls."""

import threading
import time


class RateLimiter:
    def __init__(self, calls_per_minute: int = 200):
        self._interval = 60.0 / calls_per_minute
        self._last_call = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a call is allowed."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()
