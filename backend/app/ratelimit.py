"""Limite simples, em memória, de tentativas de login erradas (força bruta).

O serviço roda com um único worker (ver deploy/gohorses-api.service), então um
dicionário no processo basta. A chave é (IP, e-mail): quem erra muitas vezes a
senha de UMA conta a partir de UM endereço precisa esperar, sem bloquear os
demais usuários que saem pelo mesmo IP (NAT).
"""
from __future__ import annotations

import time
from collections import deque

from .config import LOGIN_FAILURE_WINDOW_SECONDS, LOGIN_MAX_FAILURES

_MAX_TRACKED_KEYS = 50_000


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = {}

    def _recent(self, key: tuple[str, str], now: float) -> deque[float]:
        entries = self._failures.get(key)
        if entries is None:
            return deque()
        while entries and now - entries[0] > self.window:
            entries.popleft()
        if not entries:
            self._failures.pop(key, None)
        return entries

    def retry_after(self, key: tuple[str, str]) -> int:
        """Segundos até poder tentar de novo; 0 = liberado."""
        now = time.monotonic()
        entries = self._recent(key, now)
        if len(entries) < self.max_failures:
            return 0
        return max(1, int(self.window - (now - entries[0])) + 1)

    def record_failure(self, key: tuple[str, str]) -> None:
        now = time.monotonic()
        if len(self._failures) >= _MAX_TRACKED_KEYS:
            for stale in [k for k in self._failures if not self._recent(k, now)]:
                self._failures.pop(stale, None)
            if len(self._failures) >= _MAX_TRACKED_KEYS:
                self._failures.clear()
        self._failures.setdefault(key, deque()).append(now)

    def reset(self, key: tuple[str, str]) -> None:
        self._failures.pop(key, None)


login_failures = FailureLimiter(LOGIN_MAX_FAILURES, LOGIN_FAILURE_WINDOW_SECONDS)
