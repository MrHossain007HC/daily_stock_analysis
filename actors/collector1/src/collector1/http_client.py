"""Public HTTP fetch with redirect, SSRF, and size checks. No proxy and no auth."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Limits
from .safety import assess_resolution, assess_url_policy, default_resolver


@dataclass
class FetchResult:
    ok: bool
    status_code: int | None
    final_url: str
    headers: dict
    body: bytes
    error: str | None = None
    retryable: bool = False
    blocked: bool = False


@dataclass
class TransportResponse:
    status_code: int
    headers: dict
    body: bytes = b""
    error: str | None = None
    retryable: bool = False


def _result_blocked(url: str, reason: str, retryable: bool = False) -> FetchResult:
    return FetchResult(False, None, url, {}, b"", reason, retryable, True)


class GuardedFetcher:
    """Follow redirects manually so every hop is allowlisted and publicly resolved."""

    def __init__(self, transport, allowed_hosts, limits: Limits, resolver=None):
        self.transport = transport
        self.allowed_hosts = allowed_hosts
        self.limits = limits
        self.resolver = resolver or default_resolver

    def fetch(self, url: str) -> FetchResult:
        current = url
        seen = set()
        for _hop in range(self.limits.max_redirects + 1):
            policy = assess_url_policy(current, self.allowed_hosts)
            if not policy.allowed:
                return _result_blocked(current, policy.reason, policy.retryable)
            if current in seen:
                return FetchResult(False, None, current, {}, b"", "redirect_loop", False, True)
            seen.add(current)
            resolution = assess_resolution(policy.host, self.resolver)
            if not resolution.allowed:
                return _result_blocked(current, resolution.reason, resolution.retryable)
            try:
                response = self.transport(current)
            except TimeoutError:
                return FetchResult(False, None, current, {}, b"", "timeout", True, False)
            except Exception:
                return FetchResult(False, None, current, {}, b"", "network_error", True, False)
            if response.error:
                return FetchResult(
                    False,
                    response.status_code,
                    current,
                    _lower_headers(response.headers),
                    b"",
                    response.error,
                    response.retryable,
                    False,
                )
            headers = _lower_headers(response.headers)
            status = response.status_code
            if status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    return FetchResult(False, status, current, headers, b"", "missing_redirect", False, False)
                from urllib.parse import urljoin

                current = urljoin(current, location)
                continue
            if status == 429 or status >= 500:
                reason = "http_429" if status == 429 else f"http_{status}"
                return FetchResult(False, status, current, headers, b"", reason, True, False)
            if status < 200 or status >= 300:
                return FetchResult(False, status, current, headers, b"", f"http_{status}", False, False)
            length_header = headers.get("content-length")
            if length_header and length_header.isdigit() and int(length_header) > self.limits.max_download_bytes:
                return FetchResult(False, status, current, headers, b"", "download_too_large", False, False)
            body = response.body
            if len(body) > self.limits.max_download_bytes:
                return FetchResult(False, status, current, headers, b"", "download_too_large", False, False)
            return FetchResult(True, status, current, headers, body, None, False, False)
        return FetchResult(False, None, current, {}, b"", "too_many_redirects", False, False)


def _lower_headers(headers: dict | None) -> dict:
    return {str(key).lower(): value for key, value in (headers or {}).items()}


def httpx_transport(limits: Limits):
    import httpx

    timeout = httpx.Timeout(limits.request_timeout_seconds)

    def send(url: str) -> TransportResponse:
        try:
            with httpx.Client(follow_redirects=False, trust_env=False, timeout=timeout) as client:
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": (
                            "text/csv, application/pdf, "
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, "
                            "application/zip, text/html;q=0.5"
                        ),
                        "User-Agent": "Collector1/0.1 (public DSE research; +https://www.dsebd.org/)",
                    },
                ) as response:
                    headers = dict(response.headers)
                    status = response.status_code
                    if status in {301, 302, 303, 307, 308, 429} or status >= 400:
                        return TransportResponse(status, headers, b"")
                    chunks = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > limits.max_download_bytes:
                            return TransportResponse(status, headers, b"", "download_too_large", False)
                        chunks.append(chunk)
                    return TransportResponse(status, headers, b"".join(chunks))
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc)) from exc
        except httpx.TransportError as exc:
            raise ConnectionError(str(exc)) from exc

    return send


def default_fetcher(allowed_hosts, limits: Limits) -> GuardedFetcher:
    return GuardedFetcher(httpx_transport(limits), allowed_hosts, limits)


@dataclass
class HostState:
    limit: int
    in_flight: int = 0
    success_streak: int = 0
    backoff_until: float = 0.0
    backoff_seconds: float = 0.0


@dataclass
class DomainLimiter:
    """Sequential runs stay at one in-flight request. The limit scales delay and backoff."""

    minimum: int
    maximum: int
    hosts: dict = field(default_factory=dict)

    def state(self, host: str) -> HostState:
        if host not in self.hosts:
            self.hosts[host] = HostState(limit=self.minimum)
        return self.hosts[host]

    def before_request(self, host: str, now: float) -> tuple[bool, float]:
        state = self.state(host)
        if now < state.backoff_until:
            return False, state.backoff_until - now
        if state.in_flight >= state.limit:
            return False, 0.0
        state.in_flight += 1
        return True, 0.0

    def on_success(self, host: str) -> None:
        state = self.state(host)
        state.in_flight = max(0, state.in_flight - 1)
        state.success_streak += 1
        state.backoff_seconds = 0.0
        if state.success_streak >= 3 and state.limit < self.maximum:
            state.limit += 1
            state.success_streak = 0

    def on_throttle(self, host: str, now: float) -> None:
        state = self.state(host)
        state.in_flight = max(0, state.in_flight - 1)
        state.success_streak = 0
        state.limit = max(self.minimum, state.limit // 2 or self.minimum)
        state.backoff_seconds = 0.5 if state.backoff_seconds <= 0 else min(30.0, state.backoff_seconds * 2)
        state.backoff_until = now + state.backoff_seconds

    def on_failure(self, host: str) -> None:
        state = self.state(host)
        state.in_flight = max(0, state.in_flight - 1)
        state.success_streak = 0

    def politeness_delay(self, host: str) -> float:
        state = self.state(host)
        return 0.2 / state.limit
