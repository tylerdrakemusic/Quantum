from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock


class RateLimiter:
    """Bounded fixed-window request limiter for one service token."""

    def __init__(self, max_per_minute: int = 10, max_per_hour: int = 1024 * 1024) -> None:
        self.max_per_minute = max_per_minute
        self.max_per_hour = max_per_hour
        self._requests: dict[str, deque[tuple[datetime, int]]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, token: str, now: datetime | None = None, units: int = 1) -> bool:
        current = now or datetime.now(timezone.utc)
        if units < 1:
            raise ValueError("units must be positive")
        with self._lock:
            requests = self._requests[token]
            while requests and current - requests[0][0] >= timedelta(hours=1):
                requests.popleft()
            minute_count = sum(current - item[0] < timedelta(minutes=1) for item in requests)
            hourly_units = sum(item[1] for item in requests)
            if minute_count >= self.max_per_minute or hourly_units + units > self.max_per_hour:
                return False
            requests.append((current, units))
            return True
