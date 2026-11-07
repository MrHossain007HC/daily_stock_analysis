from conftest import run, staged

from collector1.checkpoint import empty_checkpoint, idempotency_key


class Crash(BaseException):
    pass


def test_idempotency_key_is_stable():
    assert idempotency_key("fetch_eod", url="https://www.dsebd.org/a.csv") == idempotency_key(
        "fetch_eod", url="https://www.dsebd.org/a.csv"
    )


def test_resume_skips_done_and_retries_in_progress():
    done_url = "https://www.dsebd.org/done.csv"
    pending_url = "https://www.dsebd.org/pending.csv"
    done_key = idempotency_key("fetch_eod", url=done_url)
    checkpoint = empty_checkpoint()
    checkpoint["items"][done_key] = {
        "state": "done",
        "outcome": "accepted",
        "retryable": False,
        "attempts": 1,
        "payload": {"type": "fetch_eod", "url": done_url, "depth": 0},
        "contentSha256": "abc",
        "error": None,
    }
    body = b"TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"
    fetcher = __import__("conftest").ScriptedFetcher([__import__("conftest").ok(pending_url, body, "text/csv")])
    result = run(
        mode="fetch_public",
        eod_urls=[done_url, pending_url],
        fetcher=fetcher,
        checkpoint=checkpoint,
    )
    assert fetcher.urls == [pending_url]
    assert result.resume_skipped if False else result.run_summary["resumeSkipped"] >= 1
    accepted = [row for row in result.records if row["lane"] == "accepted" and row["recordType"] == "eod_bar"]
    assert accepted and accepted[0]["symbol"] == "GP"


def test_crash_leaves_checkpoint_in_progress_and_resume_completes():
    url = "https://www.dsebd.org/live.csv"
    checkpoint = empty_checkpoint()
    fetcher = __import__("conftest").ScriptedFetcher([Crash()])
    try:
        run(mode="fetch_public", eod_urls=[url], fetcher=fetcher, checkpoint=checkpoint)
        raise AssertionError("crash should propagate")
    except Crash:
        pass
    item = next(iter(checkpoint["items"].values()))
    assert item["state"] == "in_progress"
    body = b"TRADING CODE,DATE,CLOSEP\nGP,2024-01-16,11\n"
    follow = __import__("conftest").ScriptedFetcher([__import__("conftest").ok(url, body, "text/csv")])
    result = run(mode="fetch_public", eod_urls=[url], fetcher=follow, checkpoint=checkpoint)
    assert follow.urls == [url]
    assert any(row["lane"] == "accepted" and row["close"] == 11 for row in result.records)


def test_second_run_does_not_reemit_completed_staged_file():
    first = run(files=[staged("TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n")])
    second = run(
        files=[staged("TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n")],
        checkpoint=first.checkpoint,
    )
    assert second.records == []
    assert second.run_summary["resumeSkipped"] >= 1


def test_quarantine_is_not_promoted_on_resume():
    text = "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,-2\n"
    first = run(files=[staged(text)])
    assert any(row["lane"] == "quarantine" and row["close"] == -2 for row in first.records)
    second = run(files=[staged(text)], checkpoint=first.checkpoint)
    assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in second.records)
