"""Input config and dataset record shape for Collector1."""

from __future__ import annotations

from dataclasses import dataclass, field

from .sources import DEFAULT_ALLOWED_HOSTS, ignored_hosts, normalize_host
from .validate import parse_trade_date, valid_symbol

RECORD_KEYS = (
    "recordType",
    "lane",
    "recordId",
    "idempotencyKey",
    "symbol",
    "detectedSymbol",
    "tradeDate",
    "open",
    "high",
    "low",
    "close",
    "ltp",
    "ycp",
    "volume",
    "value",
    "trades",
    "nav",
    "sourceUrl",
    "sourceHost",
    "retrievedAt",
    "contentSha256",
    "contentLength",
    "declaredMime",
    "detectedMime",
    "mimeConsistent",
    "documentClaim",
    "verifiedAnnualReport",
    "period",
    "periodStatus",
    "companyMatch",
    "dedupStatus",
    "canonicalRecordId",
    "isCanonical",
    "absenceStatus",
    "provenMissing",
    "foreignReport",
    "fieldErrors",
    "quarantineReasons",
    "failureReason",
    "retryable",
    "httpStatus",
    "retained",
    "deleted",
    "promoted",
    "sample",
    "provenance",
    "title",
)

MODES = ("ingest_staged", "fetch_public", "both")
HARD_LIMITS = {
    "max_requests": (1, 200),
    "max_bytes": (1, 50_000_000),
    "max_runtime_seconds": (1, 300),
    "max_download_bytes": (1, 15_000_000),
    "max_concurrency": (1, 4),
    "max_attempts": (1, 5),
    "max_redirects": (0, 5),
}


@dataclass
class Limits:
    max_requests: int = 20
    max_bytes: int = 20_000_000
    max_runtime_seconds: float = 120.0
    max_download_bytes: int = 8_000_000
    max_redirects: int = 3
    min_concurrency: int = 1
    max_concurrency: int = 2
    max_zip_members: int = 200
    max_zip_uncompressed_bytes: int = 32_000_000
    max_zip_ratio: float = 100.0
    max_attempts: int = 3
    request_timeout_seconds: float = 20.0


@dataclass
class CollectorConfig:
    mode: str = "ingest_staged"
    document_urls: list[str] = field(default_factory=list)
    eod_urls: list[str] = field(default_factory=list)
    staged_files: list[dict] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_HOSTS))
    limits: Limits = field(default_factory=Limits)
    resume: bool = True
    retrieved_at: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sample: bool = False
    ignored_hosts: list[str] = field(default_factory=list)


def _require_int(payload: dict, key: str, default: int, low: int, high: int) -> int:
    raw = payload.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    if raw < low or raw > high:
        raise ValueError(f"{key} must be between {low} and {high}")
    return raw


def _string_list(payload: dict, key: str) -> list[str]:
    raw = payload.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{key} must be an array of strings")
    return raw


def config_from_input(payload: dict) -> tuple[CollectorConfig, dict | None]:
    """Parse actor input. Rejects over-cap limits instead of silently shrinking them."""
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    mode = payload.get("mode", "ingest_staged")
    if mode not in MODES:
        raise ValueError("mode must be ingest_staged, fetch_public, or both")

    limits = Limits(
        max_requests=_require_int(payload, "maxRequests", 20, *HARD_LIMITS["max_requests"]),
        max_bytes=_require_int(payload, "maxBytes", 20_000_000, *HARD_LIMITS["max_bytes"]),
        max_runtime_seconds=float(
            _require_int(payload, "maxRuntimeSecs", 120, *HARD_LIMITS["max_runtime_seconds"])
        ),
        max_download_bytes=_require_int(
            payload, "maxDownloadBytes", 8_000_000, *HARD_LIMITS["max_download_bytes"]
        ),
        max_redirects=_require_int(payload, "maxRedirects", 3, *HARD_LIMITS["max_redirects"]),
        max_concurrency=_require_int(payload, "maxConcurrency", 2, *HARD_LIMITS["max_concurrency"]),
        max_attempts=_require_int(payload, "maxAttempts", 3, *HARD_LIMITS["max_attempts"]),
    )
    min_concurrency = _require_int(payload, "minConcurrency", 1, 1, limits.max_concurrency)
    limits.min_concurrency = min_concurrency

    host_source = payload.get("allowedHosts", list(DEFAULT_ALLOWED_HOSTS))
    if not isinstance(host_source, list) or not all(isinstance(item, str) for item in host_source):
        raise ValueError("allowedHosts must be an array of strings")
    ignored = ignored_hosts(host_source)
    allowed = []
    for host in host_source:
        candidate = normalize_host(host)
        if candidate and candidate not in ignored and candidate not in allowed:
            allowed.append(candidate)
    if not allowed:
        raise ValueError("allowedHosts is empty after removing denied hosts")

    symbols = []
    for symbol in _string_list(payload, "symbols"):
        if not valid_symbol(symbol):
            raise ValueError(f"invalid symbol: {symbol}")
        normalized = symbol.strip().upper()
        if normalized not in symbols:
            symbols.append(normalized)

    sessions = []
    for session in _string_list(payload, "sessions"):
        parsed = parse_trade_date(session)
        if parsed is None:
            raise ValueError(f"invalid session date: {session}")
        if parsed not in sessions:
            sessions.append(parsed)

    date_from = _optional_date(payload.get("dateFrom"), "dateFrom")
    date_to = _optional_date(payload.get("dateTo"), "dateTo")
    if date_from and date_to and date_from > date_to:
        raise ValueError("dateFrom is after dateTo")

    staged = payload.get("stagedFiles", [])
    if staged is None:
        staged = []
    if not isinstance(staged, list) or not all(isinstance(item, dict) for item in staged):
        raise ValueError("stagedFiles must be an array of objects")

    resume = payload.get("resume", True)
    if not isinstance(resume, bool):
        raise ValueError("resume must be a boolean")
    sample = payload.get("sample", False)
    if not isinstance(sample, bool):
        raise ValueError("sample must be a boolean")

    checkpoint = payload.get("checkpoint")
    if checkpoint is not None and not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be an object")
    if not resume:
        checkpoint = None

    config = CollectorConfig(
        mode=mode,
        document_urls=_string_list(payload, "documentUrls"),
        eod_urls=_string_list(payload, "eodUrls"),
        staged_files=staged,
        symbols=symbols,
        sessions=sessions,
        allowed_hosts=allowed,
        limits=limits,
        resume=resume,
        date_from=date_from,
        date_to=date_to,
        sample=sample,
        ignored_hosts=ignored,
    )
    return config, checkpoint


def _optional_date(value, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a date string")
    parsed = parse_trade_date(value)
    if parsed is None:
        raise ValueError(f"invalid {name}")
    return parsed


def blank_record(**overrides) -> dict:
    record = {key: None for key in RECORD_KEYS}
    record.update(
        {
            "verifiedAnnualReport": False,
            "provenMissing": False,
            "foreignReport": False,
            "isCanonical": False,
            "retryable": False,
            "retained": True,
            "deleted": False,
            "promoted": False,
            "sample": False,
            "fieldErrors": [],
            "quarantineReasons": [],
            "documentClaim": "not_applicable",
            "dedupStatus": "not_applicable",
            "periodStatus": "not_applicable",
            "companyMatch": "not_applicable",
        }
    )
    record.update(overrides)
    record["provenMissing"] = False
    record["deleted"] = False
    record["promoted"] = False
    return record
