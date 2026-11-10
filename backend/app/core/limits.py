"""Limits that keep one visitor from taking the server down (pre-pilot review 10.11.2026, pp. 1 and 3).

- The size of a request body, checked before FastAPI parses a form: a multipart body is spooled to disk before
  the token is checked, so without it anyone could fill the disk. Caddy limits it too (deploy/Caddyfile).
- Signing in: argon2 takes 64 MiB per check, so the number of checks at once is bounded, and failed attempts
  per email and per address are counted — the eleventh in 15 minutes waits.
"""

import logging
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from contextlib import contextmanager
from typing import Any

from app.core.errors import RuleError

log = logging.getLogger(__name__)

UPLOAD_PATHS = ("/api/imports",)  # files: up to 20 MB (imports/service.py MAX_BYTES), with the form around it
UPLOAD_LIMIT = 21 * 1024 * 1024
BODY_LIMIT = 1024 * 1024  # anything else is JSON


class TooManyError(RuleError):
    status_code = 429


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class BodyLimit:
    """Refuses a body over the limit with 413 — by its Content-Length before reading it, and while reading a
    body sent without one."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        limit = UPLOAD_LIMIT if path.startswith(UPLOAD_PATHS) else BODY_LIMIT
        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            await _too_large(send)
            return
        seen = 0
        over = False

        async def counted() -> Message:
            nonlocal seen, over
            if over:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:  # stop reading: the app sees a client gone, its answer is replaced
                    over = True
                    return {"type": "http.disconnect"}
            return message

        replaced = False

        async def answered(message: Message) -> None:
            nonlocal replaced
            if not over:
                await send(message)
            elif not replaced:  # whatever the app made of a cut body, the visitor hears «too large»
                replaced = True
                await _too_large(send)

        await self.app(scope, counted, answered)


async def _too_large(send: Send) -> None:
    body = '{"detail":"Файл слишком большой — до 20 МБ. Разбейте выгрузку на несколько периодов"}'.encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
HASHES_AT_ONCE = 4  # × 64 MiB of argon2 per API process
WAIT_FOR_HASH = 10.0


class LoginGuard:
    """Failed sign-ins per email and per address in a sliding window, and a bound on argon2 checks at once.
    Kept in the process: the stand runs two API processes, so the bound is per process (≤ 2 × the limit)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._hashing = threading.BoundedSemaphore(HASHES_AT_ONCE)

    def _recent(self, key: str, now: float) -> deque[float]:
        times = self._failures.setdefault(key, deque())
        while times and now - times[0] > WINDOW_SECONDS:
            times.popleft()
        return times

    def check(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            if any(len(self._recent(k, now)) >= MAX_FAILURES for k in keys):
                raise TooManyError("Слишком много неудачных попыток входа — подождите 15 минут")

    def failed(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for k in keys:
                self._recent(k, now).append(now)
            if len(self._failures) > 100_000:  # old keys go, so the table never grows without end
                for k in [k for k, t in self._failures.items() if not t or now - t[-1] > WINDOW_SECONDS]:
                    del self._failures[k]
        log.warning("failed sign-in for %s", keys[0] if keys else "?")

    def succeeded(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._failures.pop(k, None)

    @contextmanager
    def hashing(self) -> Any:
        if not self._hashing.acquire(timeout=WAIT_FOR_HASH):
            raise TooManyError("Сервер занят — попробуйте войти через минуту")
        try:
            yield
        finally:
            self._hashing.release()


login_guard = LoginGuard()


def client_address(headers: dict[str, str], peer: str | None) -> str:
    """The visitor's address: Caddy puts it first in X-Forwarded-For (it replaces what the visitor sent)."""
    forwarded = headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or peer or "?"
