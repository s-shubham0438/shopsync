"""Fixed-window rate limiting for auth endpoints (used from Milestone 5.2).

- Counters live in Redis (`shopsync:v1:rl:{bucket}:{digest}:{window}`), so limits are shared by
  every worker. Identifiers (IP, email, phone) are HMAC'd with the auth secret before they become
  key material: no raw emails in Redis, and unguessable without the secret.
- If Redis fails or is slow, the limiter does NOT open up: it falls back to an in-process
  counter (per worker) for `failure_backoff` seconds, logs once, then retries Redis.
- Fixed windows allow up to 2x the limit across a window boundary; acceptable for abuse
  throttling (tech-debt R1 if a sliding window is ever needed).
"""

import asyncio
import hashlib
import hmac
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.errors import RateLimitedError
from app.services.cache import NAMESPACE

logger = logging.getLogger(__name__)

_MAX_LOCAL_KEYS = 100_000


class CounterBackend(Protocol):
    async def incr(self, name: str) -> Any: ...

    async def expire(self, name: str, time: int) -> Any: ...


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    count: int
    limit: int
    retry_after: int  # seconds until the window resets

    def raise_if_blocked(self) -> None:
        if not self.allowed:
            raise RateLimitedError(headers={"Retry-After": str(self.retry_after)})


class RateLimiter:
    def __init__(
        self,
        backend: CounterBackend | None,
        *,
        secret: str,
        op_timeout: float = 0.25,
        failure_backoff: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._backend = backend
        self._secret = secret.encode()
        self._op_timeout = op_timeout
        self._failure_backoff = failure_backoff
        self._clock = clock
        self._redis_skip_until = 0.0
        self._degraded = False
        self._local: dict[str, int] = {}

    def _key(self, bucket: str, identifier: str, window_index: int) -> str:
        digest = hmac.new(self._secret, identifier.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{NAMESPACE}:rl:{bucket}:{digest}:{window_index}"

    async def hit(
        self, bucket: str, identifier: str, *, limit: int, window: int
    ) -> RateLimitResult:
        """Count one attempt and say whether it is within `limit` per `window` seconds."""
        now = self._clock()
        window_index = int(now // window)
        retry_after = max(1, math.ceil((window_index + 1) * window - now))
        key = self._key(bucket, identifier, window_index)

        count = await self._redis_incr(key, window)
        if count is None:
            count = self._local_incr(key, window_index)
        return RateLimitResult(count <= limit, count, limit, retry_after)

    async def _redis_incr(self, key: str, window: int) -> int | None:
        if self._backend is None or self._clock() < self._redis_skip_until:
            return None
        try:
            async with asyncio.timeout(self._op_timeout):
                count = int(await self._backend.incr(key))
                # Every hit refreshes the TTL; harmless because the key is window-specific.
                await self._backend.expire(key, window + 1)
        except Exception as exc:  # fail to the local limiter, never open
            self._redis_skip_until = self._clock() + self._failure_backoff
            if not self._degraded:
                self._degraded = True
                logger.warning(
                    "rate_limit_redis_unavailable",
                    extra={"error_type": type(exc).__name__, "fallback": "in_process"},
                )
            return None
        if self._degraded:
            self._degraded = False
            logger.info("rate_limit_redis_recovered")
        return count

    def _local_incr(self, key: str, window_index: int) -> int:
        if len(self._local) >= _MAX_LOCAL_KEYS:
            # Keep only the current window; older windows can no longer matter.
            suffix = f":{window_index}"
            self._local = {k: v for k, v in self._local.items() if k.endswith(suffix)}
            if len(self._local) >= _MAX_LOCAL_KEYS:
                self._local.clear()
        self._local[key] = self._local.get(key, 0) + 1
        return self._local[key]
