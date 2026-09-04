"""Bounded per-process throttling for repeated login failures."""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Lock

from app.core.config import Settings, get_settings


@dataclass
class _AttemptState:
    failures: deque[datetime] = field(default_factory=deque)
    blocked_until: datetime | None = None


class LoginThrottle:
    _MAX_TRACKED_KEYS = 10_000

    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or get_settings()
        self._attempt_limit = config.login_rate_limit_attempts
        self._window = timedelta(seconds=config.login_rate_limit_window_seconds)
        self._cooldown = timedelta(seconds=config.login_rate_limit_cooldown_seconds)
        self._states: dict[str, _AttemptState] = {}
        self._lock = Lock()

    @staticmethod
    def _key(source: str, email: str) -> str:
        normalized = f"{source.strip().casefold()}\0{email.strip().casefold()}"
        return sha256(normalized.encode("utf-8")).hexdigest()

    def is_blocked(
        self, source: str, email: str, now: datetime | None = None
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        key = self._key(source, email)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return False
            self._prune(state, current)
            if state.blocked_until is not None and state.blocked_until > current:
                return True
            if not state.failures:
                self._states.pop(key, None)
            return False

    def record_failure(
        self, source: str, email: str, now: datetime | None = None
    ) -> None:
        current = now or datetime.now(timezone.utc)
        key = self._key(source, email)
        with self._lock:
            if len(self._states) >= self._MAX_TRACKED_KEYS and key not in self._states:
                self._discard_inactive(current)
            state = self._states.setdefault(key, _AttemptState())
            self._prune(state, current)
            state.failures.append(current)
            if len(state.failures) >= self._attempt_limit:
                state.blocked_until = current + self._cooldown

    def record_success(self, source: str, email: str) -> None:
        with self._lock:
            self._states.pop(self._key(source, email), None)

    def clear(self) -> None:
        with self._lock:
            self._states.clear()

    def _prune(self, state: _AttemptState, now: datetime) -> None:
        cutoff = now - self._window
        while state.failures and state.failures[0] <= cutoff:
            state.failures.popleft()
        if state.blocked_until is not None and state.blocked_until <= now:
            state.blocked_until = None
            state.failures.clear()

    def _discard_inactive(self, now: datetime) -> None:
        for key, state in list(self._states.items()):
            self._prune(state, now)
            if not state.failures and state.blocked_until is None:
                self._states.pop(key, None)
        if len(self._states) >= self._MAX_TRACKED_KEYS:
            self._states.pop(next(iter(self._states)))


login_throttle = LoginThrottle()
