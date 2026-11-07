"""Idempotent checkpoint queue. Done work is not reset or promoted."""

from __future__ import annotations

import hashlib
import json


def idempotency_key(kind: str, **parts) -> str:
    payload = {"kind": kind, **parts}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def empty_checkpoint() -> dict:
    return {
        "version": 1,
        "items": {},
        "canonicalBySha": {},
        "acceptedBars": {},
        "nonTrading": {},
        "coverage": {},
    }


class Checkpoint:
    def __init__(self, data: dict | None):
        if data is None:
            data = empty_checkpoint()
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("unsupported checkpoint version")
        data.setdefault("items", {})
        data.setdefault("canonicalBySha", {})
        data.setdefault("acceptedBars", {})
        data.setdefault("nonTrading", {})
        data.setdefault("coverage", {})
        self.data = data

    def item(self, key: str) -> dict | None:
        found = self.data["items"].get(key)
        return found if isinstance(found, dict) else None

    def ensure_pending(self, key: str, payload: dict) -> dict:
        current = self.item(key)
        if current is None:
            current = {
                "state": "pending",
                "outcome": None,
                "retryable": False,
                "attempts": 0,
                "payload": payload,
                "contentSha256": None,
                "error": None,
            }
            self.data["items"][key] = current
        return current

    def runnable(self, key: str) -> bool:
        current = self.item(key)
        if current is None:
            return False
        if current["state"] in {"pending", "in_progress"}:
            return True
        return current["state"] == "failed" and bool(current.get("retryable"))

    def mark_in_progress(self, key: str) -> None:
        current = self.item(key)
        if current is None:
            return
        current["state"] = "in_progress"
        current["attempts"] = int(current.get("attempts") or 0) + 1
        current["retryable"] = False

    def mark_done(self, key: str, outcome: str, content_sha: str | None = None) -> None:
        current = self.item(key)
        if current is None:
            return
        current["state"] = "done"
        current["outcome"] = outcome
        current["retryable"] = False
        current["error"] = None
        if content_sha:
            current["contentSha256"] = content_sha

    def mark_failed(self, key: str, error: str, retryable: bool) -> None:
        current = self.item(key)
        if current is None:
            return
        current["state"] = "failed"
        current["outcome"] = "failure"
        current["retryable"] = retryable
        current["error"] = error
