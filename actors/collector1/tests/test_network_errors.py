from conftest import ScriptedFetcher, failure, ok, run

from collector1.models import Limits


CSV = b"TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"
URL = "https://www.dsebd.org/prices.csv"


def test_http_500_timeout_and_429_stay_retryable_failures():
    for status in (500, 429):
        fetcher = ScriptedFetcher([failure(status, True)])
        result = run(mode="fetch_public", eod_urls=[URL], fetcher=fetcher, limits=Limits(max_requests=3))
        assert fetcher.urls == [URL]
        assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in result.records)
        failed = result.failure_manifest["rows"]
        assert failed and failed[0]["retryable"] is True and failed[0]["promoted"] is False
        assert result.checkpoint["items"][next(iter(result.checkpoint["items"]))]["state"] == "failed"

    fetcher = ScriptedFetcher([TimeoutError("timed out")])
    result = run(mode="fetch_public", eod_urls=[URL], fetcher=fetcher)
    assert result.failure_manifest["rows"][0]["reason"] == "network_error"
    assert result.failure_manifest["rows"][0]["retryable"] is True
    assert result.failure_manifest["rows"][0]["promoted"] is False


def test_http_404_is_terminal_and_not_promoted():
    fetcher = ScriptedFetcher([failure(404, False)])
    result = run(mode="fetch_public", eod_urls=[URL], fetcher=fetcher)
    row = result.failure_manifest["rows"][0]
    assert row["retryable"] is False
    assert row["promoted"] is False
    assert row["reason"] == "http_404"


def test_retryable_failure_can_succeed_later_without_promoting_the_failure():
    url = "https://www.dsebd.org/retry.csv"
    first = run(
        mode="fetch_public",
        eod_urls=[url],
        fetcher=ScriptedFetcher([failure(500, True)]),
        limits=Limits(max_attempts=3),
    )
    second = run(
        mode="fetch_public",
        eod_urls=[url],
        fetcher=ScriptedFetcher([ok(url, CSV, "text/csv")]),
        checkpoint=first.checkpoint,
        limits=Limits(max_attempts=3),
    )
    assert any(row["lane"] == "accepted" and row["close"] == 10 for row in second.records)
    assert second.failure_manifest["rows"] == []
    assert all(row["promoted"] is False for row in second.records)


def test_attempt_cap_does_not_call_the_network_again():
    url = "https://www.dsebd.org/capped.csv"
    first = run(
        mode="fetch_public",
        eod_urls=[url],
        fetcher=ScriptedFetcher([failure(500, True)]),
        limits=Limits(max_attempts=1),
    )
    follow = ScriptedFetcher([ok(url, CSV, "text/csv")])
    second = run(
        mode="fetch_public",
        eod_urls=[url],
        fetcher=follow,
        checkpoint=first.checkpoint,
        limits=Limits(max_attempts=1),
    )
    assert follow.urls == []
    assert second.failure_manifest["rows"][0]["reason"] == "attempts_exhausted"
    assert second.failure_manifest["rows"][0]["promoted"] is False
    assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in second.records)
