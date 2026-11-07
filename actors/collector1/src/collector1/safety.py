"""SSRF, download-size, MIME, and archive-bomb controls."""

from __future__ import annotations

import ipaddress
import socket
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from .models import Limits
from .sources import host_is_allowed, host_is_denied, normalize_host


@dataclass(frozen=True)
class UrlDecision:
    allowed: bool
    reason: str
    host: str
    url: str
    retryable: bool = False


def _deny(url: str, host: str, reason: str, retryable: bool = False) -> UrlDecision:
    return UrlDecision(False, reason, host, url, retryable)


def ip_is_blocked(ip_text: str) -> bool:
    try:
        address = ipaddress.ip_address(ip_text.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def assess_url_policy(url: str, allowed_hosts) -> UrlDecision:
    text = url.strip()
    parts = urlsplit(text)
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"}:
        return _deny(text, host, "scheme_not_allowed")
    if parts.username or parts.password:
        return _deny(text, host, "userinfo_not_allowed")
    if not host:
        return _deny(text, "", "missing_host")
    if "%" in host or "\\" in host:
        return _deny(text, host, "malformed_host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return _deny(text, host, "malformed_host")
    host = normalize_host(host)
    if not host:
        return _deny(text, host, "malformed_host")
    if host_is_denied(host) or host in {"localhost"} or host.endswith(".localhost") or host.endswith(".local"):
        return _deny(text, host, "denied_host")
    try:
        ipaddress.ip_address(host)
        return _deny(text, host, "raw_ip_not_allowed")
    except ValueError:
        pass
    if not host_is_allowed(host, allowed_hosts):
        return _deny(text, host, "host_not_allowlisted")
    return UrlDecision(True, "ok", host, text, False)


def default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    addresses = []
    for info in infos:
        ip_text = info[4][0]
        if ip_text not in addresses:
            addresses.append(ip_text)
    if not addresses:
        raise socket.gaierror(host)
    return addresses


def assess_resolution(host: str, resolver) -> UrlDecision:
    try:
        addresses = resolver(host)
    except Exception:
        return _deny("", host, "dns_failed", retryable=True)
    if not addresses:
        return _deny("", host, "dns_failed", retryable=True)
    for address in addresses:
        if ip_is_blocked(address):
            return _deny("", host, "ssrf_blocked", retryable=False)
    return UrlDecision(True, "ok", host, "", False)


def detect_mime(body: bytes) -> str:
    if body.startswith(b"%PDF"):
        return "application/pdf"
    if body.startswith(b"PK\x03\x04"):
        sample = body[:8000]
        if b"xl/" in sample or b"[Content_Types].xml" in sample:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    head = body[:800].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:400]:
        return "text/html"
    try:
        text = body[:4000].decode("utf-8-sig")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if "\x00" in text:
        return "application/octet-stream"
    if "," in text or "\t" in text or ";" in text:
        return "text/csv"
    return "text/plain"


def header_mime(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def mime_consistent(declared: str | None, detected: str) -> bool:
    declared_name = header_mime(declared)
    if declared_name in {"", "application/octet-stream", "binary/octet-stream"}:
        return detected != "application/octet-stream"
    if declared_name == detected:
        return True
    spreadsheet = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if declared_name in {spreadsheet, "application/vnd.ms-excel"} and detected == spreadsheet:
        return True
    if declared_name in {"application/zip", "application/x-zip-compressed"} and detected in {
        "application/zip",
        spreadsheet,
    }:
        return True
    if declared_name in {"text/plain", "text/csv", "application/csv"} and detected in {"text/csv", "text/plain"}:
        return True
    return False


def _unsafe_member_name(name: str) -> bool:
    if not name or "\x00" in name:
        return True
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../"):
        return True
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        return True
    if parts and ":" in parts[0]:
        return True
    return False


def read_zip_members(data: bytes, limits: Limits) -> tuple[list[tuple[str, bytes]], str | None]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return [], "corrupt_archive"
    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members:
        return [], "empty_archive"
    if len(members) > limits.max_zip_members:
        return [], "archive_too_many_files"
    total = 0
    for info in members:
        if _unsafe_member_name(info.filename):
            return [], "unsafe_path"
        if info.flag_bits & 0x1:
            return [], "encrypted_archive"
        size = info.file_size
        total += size
        if total > limits.max_zip_uncompressed_bytes:
            return [], "archive_too_large"
        compressed = max(info.compress_size, 1)
        if size > 1024 and (size / compressed) > limits.max_zip_ratio:
            return [], "archive_bomb"
    extracted = []
    for info in members:
        with archive.open(info, "r") as handle:
            payload = handle.read(info.file_size + 1)
        if len(payload) != info.file_size:
            return [], "archive_size_mismatch"
        extracted.append((info.filename, payload))
    return extracted, None
