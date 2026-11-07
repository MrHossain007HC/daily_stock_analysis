import base64

from conftest import Clock, ScriptedFetcher, ok, run, staged

from collector1.http_client import DomainLimiter
from collector1.models import HARD_LIMITS, Limits, config_from_input


def test_request_byte_and_runtime_limits_leave_work_pending():
    urls = [
        "https://www.dsebd.org/a.csv",
        "https://www.dsebd.org/b.csv",
        "https://www.dsebd.org/c.csv",
    ]
    body = b"TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"
    fetcher = ScriptedFetcher([ok(url, body, "text/csv") for url in urls])
    limited = run(
        mode="fetch_public",
        eod_urls=urls,
        fetcher=fetcher,
        limits=Limits(max_requests=1, max_runtime_seconds=30),
    )
    assert fetcher.urls == [urls[0]]
    assert limited.run_summary["stoppedReason"] == "max_requests"
    pending = [item for item in limited.checkpoint["items"].values() if item["state"] == "pending"]
    assert len(pending) == 2

    clock = Clock()

    def slow_fetch(url):
        clock.advance(50)
        return ok(url, body, "text/csv")

    fetcher = type("F", (), {"fetch": staticmethod(slow_fetch), "urls": []})()
    original = fetcher.fetch

    def recording(url):
        fetcher.urls.append(url)
        return original(url)

    fetcher.fetch = recording
    timed = run(
        mode="fetch_public",
        eod_urls=urls[:2],
        fetcher=fetcher,
        clock=clock,
        limits=Limits(max_requests=5, max_runtime_seconds=10),
    )
    assert fetcher.urls == [urls[0]]
    assert timed.run_summary["stoppedReason"] == "max_runtime"

    first = b"a" * 30
    second = b"b" * 30
    sized = run(
        files=[
            staged(first, sourceUrl="https://www.dsebd.org/a.csv", fileName="a.csv"),
            staged(second, sourceUrl="https://www.dsebd.org/b.csv", fileName="b.csv"),
        ],
        limits=Limits(max_bytes=50, max_download_bytes=1000),
    )
    assert sized.run_summary["bytes"] == 30
    assert sized.run_summary["stoppedReason"] == "max_bytes"
    assert any(item["state"] == "pending" for item in sized.checkpoint["items"].values())


def test_download_cap_rejects_one_oversized_staged_file():
    payload = b"x" * 200
    result = run(
        files=[staged(payload, fileName="big.csv")],
        limits=Limits(max_download_bytes=100, max_bytes=1000),
    )
    assert any("download_too_large" in row["quarantineReasons"] for row in result.records)
    assert result.run_summary["bytes"] == 0
    assert all(item["state"] != "pending" for item in result.checkpoint["items"].values())


def test_domain_limiter_backs_off_and_adapts():
    limiter = DomainLimiter(1, 4)
    for _ in range(3):
        allowed, delay = limiter.before_request("dsebd.org", 0)
        assert allowed and delay == 0
        limiter.on_success("dsebd.org")
    assert limiter.state("dsebd.org").limit == 2
    allowed, _delay = limiter.before_request("dsebd.org", 10)
    assert allowed
    limiter.on_throttle("dsebd.org", 10)
    assert limiter.state("dsebd.org").limit == 1
    assert limiter.state("dsebd.org").backoff_until > 10
    allowed, delay = limiter.before_request("dsebd.org", 10)
    assert allowed is False
    assert delay > 0
    assert limiter.politeness_delay("dsebd.org") == 0.2


def test_input_limits_reject_values_outside_the_hard_ceiling():
    ceiling = HARD_LIMITS["max_requests"][1]
    try:
        config_from_input({"maxRequests": ceiling + 1})
        raise AssertionError("over-cap request limit should fail")
    except ValueError as exc:
        assert "maxRequests" in str(exc)
    try:
        config_from_input({"maxRuntimeSecs": 0})
        raise AssertionError("zero runtime should fail")
    except ValueError as exc:
        assert "maxRuntimeSecs" in str(exc)
    try:
        config_from_input({"allowedHosts": ["stocknow.com.bd"]})
        raise AssertionError("stocknow-only allowlist should fail")
    except ValueError as exc:
        assert "allowedHosts" in str(exc)
    config, _checkpoint = config_from_input({"allowedHosts": ["dsebd.org", "stocknow.com.bd"]})
    assert "stocknow.com.bd" in config.ignored_hosts
    assert "stocknow.com.bd" not in config.allowed_hosts
    assert base64.b64encode(b"ok")
