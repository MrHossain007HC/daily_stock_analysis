"""Documented public hosts. StockNow and other private sources are denied."""

from __future__ import annotations

DOCUMENTED_PUBLIC_SOURCES = {
    "dsebd.org": "https://www.dsebd.org/",
    "sec.gov.bd": "https://sec.gov.bd/",
}

DEFAULT_ALLOWED_HOSTS = tuple(DOCUMENTED_PUBLIC_SOURCES)
DENY_MARKERS = ("stocknow",)


def normalize_host(host: str) -> str:
    text = host.strip().lower().rstrip(".")
    if text.startswith("http://") or text.startswith("https://"):
        return ""
    if "%" in text or "\\" in text or "/" in text or " " in text:
        return ""
    return text


def host_is_denied(host: str) -> bool:
    candidate = normalize_host(host)
    return any(marker in candidate for marker in DENY_MARKERS)


def host_is_allowed(host: str, allowed_hosts) -> bool:
    candidate = normalize_host(host)
    if not candidate or host_is_denied(candidate):
        return False
    for item in allowed_hosts:
        allowed = normalize_host(item)
        if not allowed or host_is_denied(allowed):
            continue
        if candidate == allowed or candidate.endswith("." + allowed):
            return True
    return False


def ignored_hosts(hosts) -> list[str]:
    ignored = []
    for host in hosts:
        candidate = normalize_host(host)
        if candidate and host_is_denied(candidate) and candidate not in ignored:
            ignored.append(candidate)
    return ignored
