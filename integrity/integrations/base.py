"""Shared machinery for external source adapters (docs/DATA_SOURCES.md).

Every outbound call goes through :meth:`SourceClient.call`, which in order:

1. **Policy**: loads the provider's row in ``external_sources``. If the source is
   not enabled, not authorised, or a permission the operation needs is not
   explicitly ``True``, *no network call is made* and the outcome is
   ``blocked_by_policy``. Unknown (NULL) means not allowed.
2. **Circuit breaker**: after repeated failures the source is skipped for a
   cool-down period (``circuit_open``) instead of piling up timeouts.
3. **Transport**: HTTPS only, to the adapter's single allowed host, no
   redirects, bounded response size, timeout.
4. **Retries**: only for timeouts, 429 and 5xx, with exponential backoff and a
   bounded ``Retry-After``.
5. **Record**: one ``api_requests`` row per logical call with outcome, status,
   latency, response hash and result count. The query itself is never stored,
   only a keyed fingerprint of it (queries may contain confidential text).

Adapters (e.g. ``crossref.py``) only build URLs and normalise responses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrity.domain.enums import ApiOutcome, SourceAuthorization
from integrity.infrastructure.db.models import ApiRequest, ExternalSource

# Permissions an operation may require, by ExternalSource column name.
PERMISSION_COLUMNS = (
    "allows_commercial_use", "allows_storage", "allows_vector_indexing",
    "allows_ai_processing", "allows_excerpt_display", "allows_redistribution",
)


# --------------------------------------------------------------------------- transport

@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class TransportTimeout(Exception):
    pass


class TransportError(Exception):
    pass


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout_s: float, max_bytes: int) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib API
        return None  # a 3xx is returned to the caller as-is, never followed


class UrllibTransport:
    """Standard-library HTTPS transport. No redirects, bounded body."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect())

    def get(self, url: str, headers: dict[str, str], timeout_s: float, max_bytes: int) -> HttpResponse:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(req, timeout=timeout_s) as resp:
                body = resp.read(max_bytes + 1)
                status, hdrs = resp.status, {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as exc:  # 4xx/5xx/3xx with a response
            body = exc.read(max_bytes + 1) if exc.fp else b""
            status, hdrs = exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}
        except (socket.timeout, TimeoutError) as exc:
            raise TransportTimeout(str(exc)) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise TransportTimeout(str(exc.reason)) from None
            raise TransportError(type(exc.reason).__name__) from None
        except OSError as exc:
            raise TransportError(type(exc).__name__) from None
        if len(body) > max_bytes:
            raise TransportError("response too large")
        return HttpResponse(status=status, headers=hdrs, body=body)


# --------------------------------------------------------------------------- circuit breaker

class CircuitBreaker:
    """In-process breaker per source. Shared across requests of one worker process."""

    def __init__(self, failure_threshold: int = 5, cooldown_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            opened = self._opened_at.get(key)
            if opened is None:
                return True
            if self._clock() - opened >= self.cooldown_s:
                # half-open: let one call through; a failure re-opens immediately
                del self._opened_at[key]
                self._failures[key] = self.failure_threshold - 1
                return True
            return False

    def record(self, key: str, success: bool) -> None:
        with self._lock:
            if success:
                self._failures.pop(key, None)
                return
            n = self._failures.get(key, 0) + 1
            self._failures[key] = n
            if n >= self.failure_threshold:
                self._opened_at[key] = self._clock()


# --------------------------------------------------------------------------- client

@dataclass(frozen=True)
class CallSettings:
    timeout_s: float = 10.0
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    max_retry_after_s: float = 5.0
    max_response_bytes: int = 2 * 1024 * 1024


@dataclass
class CallResult:
    outcome: ApiOutcome
    api_request_id: str
    http_status: int | None = None
    data: Any = None             # parsed JSON body when outcome is OK
    reason: str | None = None    # why it was blocked / failed (safe to show)
    attempts: int = 0


class PolicyBlocked(Exception):
    pass


@dataclass
class SourceClient:
    """Base for one provider. Subclasses set the class attributes."""

    transport: Transport
    fingerprint_key: bytes
    breaker: CircuitBreaker
    settings: CallSettings = field(default_factory=CallSettings)
    user_agent: str = "xplagiax-integrity"
    sleep: Callable[[float], None] = time.sleep

    # Per-adapter constants (ClassVar: not constructor fields, so subclasses cannot be overridden by defaults).
    code: ClassVar[str] = ""                 # external_sources.code
    allowed_host: ClassVar[str] = ""         # the only host this adapter may contact
    adapter_version: ClassVar[str] = "1"
    # Permissions every call of this adapter needs (ExternalSource column names).
    required_permissions: ClassVar[tuple[str, ...]] = ("allows_commercial_use",)

    # -- policy -----------------------------------------------------------------
    def _source(self, session: Session) -> ExternalSource | None:
        return session.scalar(select(ExternalSource).where(ExternalSource.code == self.code))

    def _policy_problem(self, source: ExternalSource | None, extra: tuple[str, ...]) -> str | None:
        if source is None:
            return f"source '{self.code}' is not registered"
        if not source.enabled:
            return f"source '{self.code}' is disabled"
        if source.authorization not in (SourceAuthorization.AUTHORIZED, SourceAuthorization.RESTRICTED):
            return f"source '{self.code}' terms are {source.authorization.value}"
        for perm in self.required_permissions + extra:
            if getattr(source, perm) is not True:
                return f"source '{self.code}': {perm} is not confirmed"
        return None

    # -- helpers ------------------------------------------------------------------
    def fingerprint(self, operation: str, params: dict[str, Any]) -> str:
        """Keyed hash of the request. Keyed, so a stored fingerprint cannot be
        used to confirm a guessed confidential query offline."""
        canonical = json.dumps({"op": operation, "p": params}, sort_keys=True, ensure_ascii=False)
        return hmac.new(self.fingerprint_key, f"{self.code}:{canonical}".encode(), hashlib.sha256).hexdigest()

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"https://{self.allowed_host}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != self.allowed_host:
            raise ValueError("adapter attempted to contact a non-allowed host")  # SSRF guard
        return url

    def _record(self, session: Session, source: ExternalSource | None, *, organization_id: str | None,
                evaluation_id: str | None, operation: str, fingerprint: str, outcome: ApiOutcome,
                http_status: int | None = None, latency_ms: int | None = None, body: bytes | None = None,
                result_count: int | None = None) -> str:
        if source is None:  # unregistered sources cannot be recorded (FK); nothing was sent
            return ""
        row = ApiRequest(
            organization_id=organization_id, evaluation_id=evaluation_id, external_source_id=source.id,
            operation=operation, request_fingerprint=fingerprint, outcome=outcome, http_status=http_status,
            latency_ms=latency_ms, cache_hit=False,
            response_sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
            result_count=result_count, adapter_version=self.adapter_version)
        session.add(row)
        session.flush()
        return row.id

    @staticmethod
    def _classify(status: int) -> ApiOutcome:
        if 200 <= status < 300:
            return ApiOutcome.OK
        if status == 404:
            return ApiOutcome.NOT_FOUND
        if status == 429:
            return ApiOutcome.RATE_LIMITED
        if status >= 500:
            return ApiOutcome.SERVER_ERROR
        return ApiOutcome.CLIENT_ERROR  # includes unfollowed 3xx

    def _retry_delay(self, attempt: int, resp: HttpResponse | None) -> float:
        if resp is not None and "retry-after" in resp.headers:
            try:
                return min(float(resp.headers["retry-after"]), self.settings.max_retry_after_s)
            except ValueError:
                pass
        return self.settings.backoff_base_s * (2 ** (attempt - 1))

    # -- the one entry point --------------------------------------------------------
    def call(self, session: Session, *, operation: str, path: str, query: dict[str, Any] | None,
             fingerprint_params: dict[str, Any], organization_id: str | None = None,
             evaluation_id: str | None = None, count_results: Callable[[Any], int] | None = None,
             extra_permissions: tuple[str, ...] = ()) -> CallResult:
        fp = self.fingerprint(operation, fingerprint_params)
        source = self._source(session)
        problem = self._policy_problem(source, extra_permissions)
        rec = dict(organization_id=organization_id, evaluation_id=evaluation_id, operation=operation, fingerprint=fp)
        if problem:
            rid = self._record(session, source, outcome=ApiOutcome.BLOCKED_BY_POLICY, **rec)
            return CallResult(ApiOutcome.BLOCKED_BY_POLICY, rid, reason=problem)
        if not self.breaker.allow(self.code):
            rid = self._record(session, source, outcome=ApiOutcome.CIRCUIT_OPEN, **rec)
            return CallResult(ApiOutcome.CIRCUIT_OPEN, rid, reason="source temporarily unavailable")

        url = self._url(path, query)
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        started = time.perf_counter()
        resp: HttpResponse | None = None
        outcome = ApiOutcome.SERVER_ERROR
        attempt = 0
        for attempt in range(1, self.settings.max_attempts + 1):
            resp = None
            try:
                resp = self.transport.get(url, headers, self.settings.timeout_s, self.settings.max_response_bytes)
                outcome = self._classify(resp.status)
            except TransportTimeout:
                outcome = ApiOutcome.TIMEOUT
            except TransportError:
                outcome = ApiOutcome.SERVER_ERROR
            retryable = outcome in (ApiOutcome.TIMEOUT, ApiOutcome.RATE_LIMITED, ApiOutcome.SERVER_ERROR)
            if not retryable or attempt == self.settings.max_attempts:
                break
            self.sleep(self._retry_delay(attempt, resp))

        latency_ms = int((time.perf_counter() - started) * 1000)
        # Only provider-side failures count against the breaker; a 404 is a valid answer.
        self.breaker.record(self.code, outcome in (ApiOutcome.OK, ApiOutcome.NOT_FOUND, ApiOutcome.CLIENT_ERROR))

        data, count = None, None
        if outcome == ApiOutcome.OK and resp is not None:
            try:
                data = json.loads(resp.body)
            except ValueError:
                outcome = ApiOutcome.SERVER_ERROR  # malformed provider response
            else:
                count = count_results(data) if count_results else None
        rid = self._record(session, source, outcome=outcome, http_status=resp.status if resp else None,
                           latency_ms=latency_ms, body=resp.body if resp else None, result_count=count, **rec)
        return CallResult(outcome, rid, http_status=resp.status if resp else None, data=data, attempts=attempt,
                          reason=None if outcome == ApiOutcome.OK else outcome.value)
