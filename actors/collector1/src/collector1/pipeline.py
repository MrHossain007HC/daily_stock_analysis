"""Resumable collection pipeline. Failed rows are never promoted to accepted."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .version import __version__
from .checkpoint import Checkpoint, idempotency_key
from .documents import classify_document, extract_public_links
from .eod import interpret_row, parse_tabular_text, parse_xlsx, table_kind
from .http_client import DomainLimiter, FetchResult, default_fetcher
from .models import CollectorConfig, blank_record
from .safety import assess_url_policy, detect_mime, header_mime, mime_consistent, read_zip_members

SPREADSHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class CollectorResult:
    records: list
    checkpoint: dict
    coverage_manifest: dict
    failure_manifest: dict
    run_summary: dict


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_id(key: str, lane: str) -> str:
    return hashlib.sha256(f"{lane}|{key}".encode("utf-8")).hexdigest()[:32]


class Runner:
    def __init__(self, config: CollectorConfig, fetcher, checkpoint: dict | None, clock, sleeper):
        self.config = config
        self.fetcher = fetcher
        self.store = Checkpoint(checkpoint)
        self.clock = clock
        self.sleeper = sleeper
        self.started = clock()
        self.records = []
        self.requests = 0
        self.bytes_used = 0
        self.stopped = None
        self.resume_skipped = 0
        self.limiter = DomainLimiter(config.limits.min_concurrency, config.limits.max_concurrency)
        self.retrieved_at = config.retrieved_at or datetime.now(timezone.utc).isoformat()
        self.extra_work = []

    def run(self) -> CollectorResult:
        work = self._seed_work()
        index = 0
        while index < len(work):
            if self._runtime_exceeded():
                self.stopped = "max_runtime"
                break
            key = work[index]
            item = self.store.item(key)
            if item is None or not self.store.runnable(key):
                self.resume_skipped += 1
                index += 1
                continue
            if self._attempts_exhausted(key, item):
                index += 1
                continue
            if self._over_request_budget(item):
                self.stopped = "max_requests"
                break
            if self._defer_for_backoff(item):
                index += 1
                continue
            if self._defer_for_bytes(item):
                self.stopped = "max_bytes"
                break
            self.store.mark_in_progress(key)
            self._process(key, item)
            work.extend(self.extra_work)
            self.extra_work = []
            index += 1
            if self.stopped:
                break
            if self.bytes_used >= self.config.limits.max_bytes:
                self.stopped = "max_bytes"
                break
        if self.stopped is None and any(self.store.runnable(key) for key in work):
            self.stopped = "backoff"
        coverage = self._coverage()
        failures = self._failures()
        summary = self._summary()
        return CollectorResult(self.records, self.store.data, coverage, failures, summary)

    def _seed_work(self) -> list[str]:
        work = []
        seen = set()

        def add(key: str, payload: dict) -> None:
            if key in seen:
                return
            seen.add(key)
            self.store.ensure_pending(key, payload)
            work.append(key)

        for staged in self.config.staged_files:
            identity = staged.get("contentBase64") or staged.get("title") or ""
            key = idempotency_key(
                "staged",
                url=staged.get("sourceUrl"),
                file=staged.get("fileName"),
                file_kind=staged.get("kind"),
                identity=_sha(str(identity).encode("utf-8")),
            )
            add(key, {"type": "staged", "file": staged})
        if self.config.mode in {"fetch_public", "both"}:
            for url in self.config.eod_urls:
                add(idempotency_key("fetch_eod", url=url), {"type": "fetch_eod", "url": url, "depth": 0})
            for url in self.config.document_urls:
                add(
                    idempotency_key("fetch_document", url=url),
                    {"type": "fetch_document", "url": url, "depth": 0},
                )
        return work

    def _runtime_exceeded(self) -> bool:
        return self.clock() - self.started >= self.config.limits.max_runtime_seconds

    def _attempts_exhausted(self, key: str, item: dict) -> bool:
        if item["state"] in {"failed", "in_progress"} and int(item.get("attempts") or 0) >= self.config.limits.max_attempts:
            item["state"] = "failed"
            item["retryable"] = False
            item["outcome"] = "failure"
            item["error"] = "attempts_exhausted"
            self._emit_failure(key, item, "attempts_exhausted", False)
            return True
        return False

    def _over_request_budget(self, item: dict) -> bool:
        return item["payload"].get("type") != "staged" and self.requests >= self.config.limits.max_requests

    def _defer_for_backoff(self, item: dict) -> bool:
        if item["payload"].get("type") == "staged":
            return False
        url = item["payload"].get("url") or ""
        policy = assess_url_policy(url, self.config.allowed_hosts)
        if not policy.allowed:
            return False
        state = self.limiter.state(policy.host)
        now = self.clock()
        if now >= state.backoff_until:
            return False
        delay = state.backoff_until - now
        remaining = self.config.limits.max_runtime_seconds - (now - self.started)
        if delay <= remaining:
            self.sleeper(delay)
        return True

    def _defer_for_bytes(self, item: dict) -> bool:
        if item["payload"].get("type") != "staged":
            return False
        body, problem = self._decode_staged(item["payload"]["file"])
        if problem or body is None:
            return False
        if self.bytes_used + len(body) <= self.config.limits.max_bytes:
            return False
        return self.bytes_used > 0

    def _process(self, key: str, item: dict) -> None:
        kind = item["payload"].get("type")
        if kind == "staged":
            self._process_staged(key, item["payload"]["file"])
        else:
            self._process_fetch(key, item["payload"])

    def _process_staged(self, key: str, staged: dict) -> None:
        url = str(staged.get("sourceUrl") or "")
        policy = assess_url_policy(url, self.config.allowed_hosts)
        sample = self.config.sample or bool(staged.get("sample"))
        if not policy.allowed:
            self.store.mark_failed(key, policy.reason, False)
            self._emit_failure(key, {"payload": {"url": url}}, policy.reason, False)
            return
        body, problem = self._decode_staged(staged)
        if problem == "download_too_large" or (
            body is not None and self.bytes_used == 0 and len(body) > self.config.limits.max_bytes
        ):
            self._terminal_quarantine(key, url, policy.host, "download_too_large", sample, staged)
            return
        if problem:
            self._terminal_quarantine(key, url, policy.host, problem, sample, staged)
            return
        if body is None:
            self._emit_metadata(key, url, policy.host, sample, staged)
            return
        self.bytes_used += len(body)
        self._ingest_bytes(
            key,
            body,
            url,
            policy.host,
            staged.get("declaredMime"),
            staged.get("fileName") or "",
            staged.get("kind") or self._infer_kind(staged.get("fileName") or "", body),
            staged.get("title") or "",
            staged.get("symbol"),
            staged.get("expectedPeriod"),
            sample,
            None,
            int(staged.get("depth") or 0),
        )

    def _process_fetch(self, key: str, payload: dict) -> None:
        url = payload.get("url") or ""
        policy = assess_url_policy(url, self.config.allowed_hosts)
        if not policy.allowed:
            self.store.mark_failed(key, policy.reason, policy.retryable)
            self._emit_failure(key, {"payload": payload}, policy.reason, policy.retryable)
            return
        self.sleeper(self.limiter.politeness_delay(policy.host))
        acquired, _delay = self.limiter.before_request(policy.host, self.clock())
        if not acquired:
            item = self.store.item(key)
            if item and item["state"] == "in_progress":
                item["state"] = "pending"
                item["attempts"] = max(0, int(item.get("attempts") or 1) - 1)
            return
        self.requests += 1
        try:
            result = self.fetcher.fetch(url)
        except Exception:
            self.limiter.on_failure(policy.host)
            self.store.mark_failed(key, "network_error", True)
            self._emit_failure(key, {"payload": payload}, "network_error", True)
            return
        if result.status_code == 429 or result.error == "http_429":
            self.limiter.on_throttle(policy.host, self.clock())
        elif result.ok:
            self.limiter.on_success(policy.host)
        else:
            self.limiter.on_failure(policy.host)
        if not result.ok:
            reason = result.error or "network_error"
            retryable = bool(result.retryable) and not result.blocked
            self.store.mark_failed(key, reason, retryable)
            self._emit_failure(key, {"payload": payload}, reason, retryable, result.status_code)
            return
        body = result.body
        if self.bytes_used + len(body) > self.config.limits.max_bytes and self.bytes_used > 0:
            item = self.store.item(key)
            if item:
                item["state"] = "pending"
                item["attempts"] = max(0, int(item.get("attempts") or 1) - 1)
            self.stopped = "max_bytes"
            return
        self.bytes_used += len(body)
        kind = "fetch_eod" if payload.get("type") == "fetch_eod" else "financial_document"
        declared = header_mime(result.headers.get("content-type"))
        self._ingest_bytes(
            key,
            body,
            result.final_url or url,
            policy.host,
            declared,
            url.rsplit("/", 1)[-1],
            kind,
            "",
            None,
            None,
            self.config.sample,
            result.status_code,
            int(payload.get("depth") or 0),
        )

    def _ingest_bytes(
        self,
        key,
        body,
        url,
        host,
        declared_mime,
        file_name,
        kind,
        title,
        symbol,
        expected_period,
        sample,
        http_status,
        depth,
    ) -> None:
        digest = _sha(body)
        detected = detect_mime(body)
        if declared_mime and not mime_consistent(declared_mime, detected):
            self._emit(
                self._base(
                    key, "raw", "raw_receipt", url, host, sample, http_status, digest, len(body), declared_mime, detected
                )
            )
            self._terminal_quarantine_done(key, url, host, "content_mime_mismatch", sample, digest, detected)
            return
        canonical = self.store.data["canonicalBySha"].get(digest)
        self._emit(
            self._base(
                key,
                "raw",
                "raw_receipt",
                url,
                host,
                sample,
                http_status,
                digest,
                len(body),
                declared_mime,
                detected,
            )
        )
        if canonical:
            duplicate = self._base(
                key,
                "accepted",
                "duplicate_receipt",
                url,
                host,
                sample,
                http_status,
                digest,
                len(body),
                declared_mime,
                detected,
            )
            duplicate["dedupStatus"] = "duplicate"
            duplicate["canonicalRecordId"] = canonical
            duplicate["isCanonical"] = False
            self._emit(duplicate)
            self.store.mark_done(key, "duplicate", digest)
            return
        file_record = _record_id(key, "raw")
        self.store.data["canonicalBySha"][digest] = file_record
        if detected == "text/html" or (kind == "fetch_eod" and detected == "text/html"):
            self._emit_html(key, url, host, body, declared_mime, detected, sample, http_status, digest, depth, kind)
            return
        if kind in {"zip", "fetch_eod"} and detected == "application/zip":
            self._emit_zip(key, body, url, host, sample, http_status, digest, depth)
            return
        if kind in {"financial_document", "fetch_document"} or detected == "application/pdf":
            self._emit_document(
                key, body, url, host, file_name, title, symbol, expected_period, declared_mime, sample, http_status, digest
            )
            return
        if detected in {"text/csv", "text/plain", SPREADSHEET} or kind in {"eod", "fetch_eod"}:
            self._emit_table(key, body, detected, url, host, sample, http_status, digest, declared_mime)
            return
        self._terminal_quarantine_done(key, url, host, "content_kind_mismatch", sample, digest, detected)

    def _emit_html(self, key, url, host, body, declared, detected, sample, http_status, digest, depth, kind) -> None:
        if kind == "fetch_eod":
            self._terminal_quarantine_done(key, url, host, "content_mime_mismatch", sample, digest, detected)
            return
        record = self._base(key, "accepted", "financial_document", url, host, sample, http_status, digest, len(body), declared, detected)
        record["documentClaim"] = "unverified_document"
        record["verifiedAnnualReport"] = False
        self._emit(record)
        self.store.mark_done(key, "accepted", digest)
        if depth >= 1:
            return
        for link in extract_public_links(body, url, self.config.allowed_hosts):
            link_kind = "fetch_eod" if link.lower().endswith((".csv", ".xlsx", ".zip", ".txt")) else "fetch_document"
            child = idempotency_key(link_kind, url=link)
            self.store.ensure_pending(child, {"type": link_kind, "url": link, "depth": depth + 1})
            self.extra_work.append(child)

    def _emit_zip(self, key, body, url, host, sample, http_status, digest, depth) -> None:
        members, problem = read_zip_members(body, self.config.limits)
        if problem:
            self._terminal_quarantine_done(key, url, host, problem, sample, digest, "application/zip")
            return
        any_accepted = False
        for name, payload in members:
            member_key = idempotency_key("zip_member", parent=key, name=name, sha=_sha(payload))
            detected = detect_mime(payload)
            if name.lower().endswith(".pdf") or detected == "application/pdf":
                accepted = self._emit_document(
                    member_key, payload, url, host, name, "", None, None, detected, sample, http_status, _sha(payload)
                )
            elif detected in {"text/csv", "text/plain", SPREADSHEET} or name.lower().endswith((".csv", ".txt", ".xlsx")):
                accepted = self._emit_table(
                    member_key, payload, detected, url, host, sample, http_status, _sha(payload), detected
                )
            else:
                self._terminal_quarantine_done(
                    member_key, url, host, "unsupported_member", sample, _sha(payload), detected
                )
                accepted = False
            any_accepted = any_accepted or accepted
        self.store.mark_done(key, "accepted" if any_accepted else "quarantine", digest)

    def _emit_table(self, key, body, detected, url, host, sample, http_status, digest, declared) -> None:
        consistent = mime_consistent(declared, detected)
        if declared and not consistent:
            self._terminal_quarantine_done(key, url, host, "content_mime_mismatch", sample, digest, detected)
            return
        if detected == SPREADSHEET:
            rows, problem = parse_xlsx(body)
        else:
            try:
                text = body.decode("utf-8-sig")
            except UnicodeDecodeError:
                self._terminal_quarantine_done(key, url, host, "undecodable", sample, digest, detected)
                return
            rows, problem = parse_tabular_text(text)
        if problem:
            self._terminal_quarantine_done(key, url, host, problem, sample, digest, detected)
            return
        kind = table_kind(rows)
        any_accepted = False
        for index, row in enumerate(rows):
            parsed = interpret_row(row, kind)
            row_key = idempotency_key("row", parent=key, index=index, symbol=parsed["symbol"], date=parsed["tradeDate"])
            existing = self.store.item(row_key)
            if existing and existing["state"] == "done":
                any_accepted = any_accepted or existing.get("outcome") == "accepted"
                continue
            self.store.ensure_pending(row_key, {"type": "row"})
            record = self._base(
                row_key,
                "accepted",
                parsed["recordType"],
                url,
                host,
                sample,
                http_status,
                digest,
                len(body),
                declared,
                detected,
            )
            for field in ("symbol", "tradeDate", "open", "high", "low", "close", "ltp", "ycp", "volume", "value", "trades", "nav"):
                record[field] = parsed[field]
            record["fieldErrors"] = parsed["fieldErrors"]
            reasons = []
            if parsed["fieldErrors"]:
                reasons.append("field_errors")
            if parsed["tradeDate"] and not self._in_range(parsed["tradeDate"]):
                reasons.append("outside_requested_range")
            bar_key = None
            if parsed["symbol"] and parsed["tradeDate"]:
                bar_key = f"{parsed['symbol']}|{parsed['tradeDate']}"
            if parsed["nonTrading"] and not reasons:
                if bar_key and bar_key in self.store.data["acceptedBars"]:
                    reasons.append("conflicting_bar")
                else:
                    record["lane"] = "accepted"
                    record["recordType"] = "coverage_gap"
                    record["absenceStatus"] = "non_trading"
                    record["close"] = None
                    record["ltp"] = None
                    record["open"] = None
                    record["high"] = None
                    record["low"] = None
                    if bar_key:
                        self.store.data["nonTrading"][bar_key] = True
                    any_accepted = True
                    self._emit(record)
                    self.store.mark_done(row_key, "accepted")
                    continue
            if bar_key and bar_key in self.store.data["nonTrading"]:
                reasons.append("conflicting_bar")
            if parsed["recordType"] == "eod_bar" and bar_key and not reasons:
                previous = self.store.data["acceptedBars"].get(bar_key)
                identity = {"close": parsed["close"], "ltp": parsed["ltp"]}
                if previous and (previous.get("close") != identity["close"] or previous.get("ltp") != identity["ltp"]):
                    reasons.append("conflicting_bar")
                elif previous:
                    record["dedupStatus"] = "duplicate"
                    record["isCanonical"] = False
                    record["canonicalRecordId"] = previous["recordId"]
                else:
                    record["dedupStatus"] = "canonical"
                    record["isCanonical"] = True
            if parsed["recordType"] == "company_profile" and parsed["symbol"] and not reasons:
                profiles = self.store.data.setdefault("profiles", {})
                previous = profiles.get(parsed["symbol"])
                if previous and previous.get("nav") != parsed["nav"]:
                    reasons.append("conflicting_profile")
                elif previous:
                    record["dedupStatus"] = "duplicate"
                    record["isCanonical"] = False
                    record["canonicalRecordId"] = previous["recordId"]
                else:
                    record["dedupStatus"] = "canonical"
                    record["isCanonical"] = True
            if reasons:
                record["lane"] = "quarantine"
                record["quarantineReasons"] = reasons
                record["isCanonical"] = False
                self.store.mark_done(row_key, "quarantine")
            else:
                record["lane"] = "accepted"
                if record["isCanonical"] and parsed["recordType"] == "eod_bar" and bar_key:
                    self.store.data["acceptedBars"][bar_key] = {
                        "recordId": record["recordId"],
                        "close": parsed["close"],
                        "ltp": parsed["ltp"],
                    }
                if record["isCanonical"] and parsed["recordType"] == "company_profile" and parsed["symbol"]:
                    self.store.data.setdefault("profiles", {})[parsed["symbol"]] = {
                        "recordId": record["recordId"],
                        "nav": parsed["nav"],
                    }
                any_accepted = True
                self.store.mark_done(row_key, "accepted")
            self._emit(record)
        self.store.mark_done(key, "accepted" if any_accepted else "quarantine", digest)
        return any_accepted

    def _emit_document(
        self, key, body, url, host, file_name, title, symbol, expected_period, declared, sample, http_status, digest
    ) -> None:
        classified = classify_document(
            body,
            title=title,
            file_name=file_name,
            declared_symbol=symbol,
            expected_period=expected_period,
            declared_mime=declared,
        )
        lane = "quarantine" if classified["quarantineReasons"] else "accepted"
        record = self._base(
            key,
            lane,
            "financial_document",
            url,
            host,
            sample,
            http_status,
            digest,
            len(body) if body is not None else 0,
            declared,
            classified.get("detectedMime"),
        )
        record.update(classified)
        record["lane"] = lane
        if sample and record["documentClaim"] == "verified_annual_report":
            record["documentClaim"] = "unverified_document"
            record["verifiedAnnualReport"] = False
        record["contentSha256"] = digest
        self._force_claim_flags(record)
        self._emit(record)
        self.store.mark_done(key, "quarantine" if lane == "quarantine" else "accepted", digest)
        return lane == "accepted"

    def _emit_metadata(self, key, url, host, sample, staged) -> None:
        classified = classify_document(
            None,
            title=staged.get("title") or "",
            file_name=staged.get("fileName") or "",
            declared_symbol=staged.get("symbol"),
            expected_period=staged.get("expectedPeriod"),
            declared_mime=staged.get("declaredMime"),
        )
        lane = "quarantine" if classified["quarantineReasons"] else "accepted"
        raw = self._base(key, "raw", "financial_document", url, host, sample, None, None, 0, None, None)
        raw["documentClaim"] = "metadata_only"
        raw["verifiedAnnualReport"] = False
        raw["title"] = staged.get("title")
        self._emit(raw)
        record = self._base(key, lane, "financial_document", url, host, sample, None, None, 0, None, None)
        record.update(classified)
        record["lane"] = lane
        record["documentClaim"] = "metadata_only"
        record["verifiedAnnualReport"] = False
        self._emit(record)
        self.store.mark_done(key, "quarantine" if lane == "quarantine" else "accepted")

    def _emit_failure(self, key, item, reason, retryable, http_status=None, detail=None) -> None:
        url = item.get("payload", {}).get("url") or item.get("payload", {}).get("file", {}).get("sourceUrl")
        host = ""
        if isinstance(url, str):
            host = assess_url_policy(url, self.config.allowed_hosts).host
        record = self._base(key, "failure", "fetch_failure", url or "", host, self.config.sample, http_status, None, 0, None, None)
        record["failureReason"] = reason if detail is None else f"{reason}:{detail}"
        record["retryable"] = retryable
        record["promoted"] = False
        self._emit(record)

    def _terminal_quarantine(self, key, url, host, reason, sample, staged) -> None:
        record = self._base(key, "quarantine", "raw_receipt", url, host, sample, None, None, 0, staged.get("declaredMime"), None)
        record["quarantineReasons"] = [reason]
        record["title"] = staged.get("title")
        self._emit(record)
        self.store.mark_done(key, "quarantine")

    def _terminal_quarantine_done(self, key, url, host, reason, sample, digest, detected) -> None:
        record = self._base(key, "quarantine", "raw_receipt", url, host, sample, None, digest, None, None, detected)
        record["quarantineReasons"] = [reason]
        self._emit(record)
        self.store.mark_done(key, "quarantine", digest)

    def _base(self, key, lane, record_type, url, host, sample, http_status, digest, length, declared, detected) -> dict:
        record = blank_record(
            recordType=record_type,
            lane=lane,
            recordId=_record_id(key, lane),
            idempotencyKey=key,
            sourceUrl=url,
            sourceHost=host,
            retrievedAt=self.retrieved_at,
            contentSha256=digest,
            contentLength=length,
            declaredMime=header_mime(declared) or None,
            detectedMime=detected or None,
            mimeConsistent=mime_consistent(declared, detected) if detected else None,
            httpStatus=http_status,
            sample=bool(sample),
        )
        record["provenance"] = {
            "sourceUrl": url,
            "sourceHost": host,
            "retrievedAt": self.retrieved_at,
            "httpStatus": http_status,
            "contentSha256": digest,
            "contentLength": length,
            "declaredMime": record["declaredMime"],
            "detectedMime": detected or None,
            "actor": "collector1",
            "actorVersion": __version__,
            "publicSource": True,
            "sample": bool(sample),
        }
        return record

    def _emit(self, record: dict) -> None:
        self._force_claim_flags(record)
        record["provenMissing"] = False
        record["deleted"] = False
        record["promoted"] = False
        record["retained"] = True
        self.records.append(record)

    def _force_claim_flags(self, record: dict) -> None:
        if record.get("documentClaim") == "metadata_only":
            record["verifiedAnnualReport"] = False
        if record.get("verifiedAnnualReport") is not True:
            record["verifiedAnnualReport"] = False
        if record.get("sample") and record.get("documentClaim") == "verified_annual_report":
            record["documentClaim"] = "unverified_document"
            record["verifiedAnnualReport"] = False

    def _in_range(self, trade_date: str) -> bool:
        if self.config.date_from and trade_date < self.config.date_from:
            return False
        if self.config.date_to and trade_date > self.config.date_to:
            return False
        return True

    def _decode_staged(self, staged: dict) -> tuple[bytes | None, str | None]:
        raw = staged.get("contentBase64")
        if raw is None:
            return None, None
        if not isinstance(raw, str):
            return None, "invalid_base64"
        compact = "".join(raw.split())
        estimated = (len(compact) * 3) // 4
        if estimated > self.config.limits.max_download_bytes + 4:
            return None, "download_too_large"
        try:
            body = base64.b64decode(compact, validate=True)
        except Exception:
            return None, "invalid_base64"
        if len(body) > self.config.limits.max_download_bytes:
            return None, "download_too_large"
        return body, None

    def _infer_kind(self, file_name: str, body: bytes) -> str:
        detected = detect_mime(body)
        if detected == "application/pdf":
            return "financial_document"
        if detected == "application/zip":
            return "zip"
        return "eod"

    def _coverage(self) -> dict:
        rows = []
        for symbol in self.config.symbols:
            for session in self.config.sessions:
                key = f"{symbol}|{session}"
                accepted = self.store.data["acceptedBars"].get(key)
                if accepted:
                    status = "observed"
                    accepted_id = accepted.get("recordId")
                elif key in self.store.data["nonTrading"]:
                    status = "non_trading"
                    accepted_id = None
                else:
                    status = "unknown"
                    accepted_id = None
                rows.append(
                    {
                        "symbol": symbol,
                        "tradeDate": session,
                        "absenceStatus": status,
                        "provenMissing": False,
                        "acceptedRecordId": accepted_id,
                    }
                )
                if self.store.data["coverage"].get(key) == status:
                    continue
                record = self._base(
                    idempotency_key("coverage", symbol=symbol, session=session, status=status),
                    "accepted",
                    "coverage_gap",
                    "",
                    "",
                    self.config.sample,
                    None,
                    None,
                    0,
                    None,
                    None,
                )
                record["symbol"] = symbol
                record["tradeDate"] = session
                record["absenceStatus"] = status
                record["provenMissing"] = False
                record["canonicalRecordId"] = accepted_id
                self._emit(record)
                self.store.data["coverage"][key] = status
        return {"generatedAt": self.retrieved_at, "rows": rows}

    def _failures(self) -> dict:
        rows = []
        for key, item in self.store.data["items"].items():
            if item.get("state") != "failed":
                continue
            payload = item.get("payload") or {}
            url = payload.get("url") or (payload.get("file") or {}).get("sourceUrl")
            rows.append(
                {
                    "idempotencyKey": key,
                    "sourceUrl": url,
                    "reason": item.get("error"),
                    "retryable": bool(item.get("retryable")),
                    "promoted": False,
                }
            )
        return {"generatedAt": self.retrieved_at, "rows": rows}

    def _summary(self) -> dict:
        def count(lane: str) -> int:
            return sum(1 for record in self.records if record["lane"] == lane)

        return {
            "requests": self.requests,
            "bytes": self.bytes_used,
            "runtimeSeconds": self.clock() - self.started,
            "accepted": count("accepted"),
            "quarantine": count("quarantine"),
            "failures": count("failure"),
            "raw": count("raw"),
            "stoppedReason": self.stopped,
            "resumeSkipped": self.resume_skipped,
            "ignoredHosts": list(self.config.ignored_hosts),
            "sample": self.config.sample,
            "actor": "collector1",
            "actorVersion": __version__,
        }


def run_collector(
    config: CollectorConfig,
    *,
    fetcher=None,
    checkpoint: dict | None = None,
    clock=None,
    sleeper=None,
) -> CollectorResult:
    if fetcher is None and config.mode in {"fetch_public", "both"} and (config.eod_urls or config.document_urls):
        fetcher = default_fetcher(config.allowed_hosts, config.limits)
    if fetcher is None:
        fetcher = _RefusingFetcher()
    return Runner(
        config,
        fetcher,
        checkpoint,
        clock or _monotonic,
        sleeper if sleeper is not None else (lambda _seconds: None),
    ).run()


def _monotonic() -> float:
    import time

    return time.monotonic()


class _RefusingFetcher:
    def fetch(self, url: str) -> FetchResult:
        return FetchResult(False, None, url, {}, b"", "fetcher_unavailable", False, True)
