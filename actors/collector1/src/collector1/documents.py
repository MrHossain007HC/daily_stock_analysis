"""Financial-document classification. Metadata is never a verified annual report."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .safety import assess_url_policy, detect_mime, header_mime, mime_consistent
from .validate import (
    compare_periods,
    contains_annual_phrase,
    filename_codes,
    is_foreign_report,
    parse_expected_period,
    parse_period_text,
    symbol_in_text,
    trading_codes_in_text,
)

DOCUMENT_EXTENSIONS = (".pdf", ".csv", ".xlsx", ".zip", ".txt")


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def extract_public_links(html: bytes, base_url: str, allowed_hosts, limit: int = 20) -> list[str]:
    parser = _LinkExtractor()
    parser.feed(html.decode("utf-8", errors="ignore"))
    found = []
    for href in parser.hrefs:
        absolute = urljoin(base_url, href.strip())
        path = urlsplit(absolute).path.lower()
        if not path.endswith(DOCUMENT_EXTENSIONS):
            continue
        decision = assess_url_policy(absolute, allowed_hosts)
        if not decision.allowed:
            continue
        if absolute not in found:
            found.append(absolute)
        if len(found) >= limit:
            break
    return found


def classify_document(
    body: bytes | None,
    *,
    title: str = "",
    file_name: str = "",
    declared_symbol: str | None = None,
    expected_period: str | None = None,
    declared_mime: str | None = None,
) -> dict:
    text_parts = [title or "", file_name or ""]
    detected = ""
    consistent = None
    reasons = []
    if body is None:
        claim = "metadata_only"
        text = "\n".join(text_parts)
    else:
        detected = detect_mime(body)
        consistent = mime_consistent(declared_mime, detected)
        if not consistent:
            reasons.append("content_mime_mismatch")
        sample = body[:200_000].decode("latin-1", errors="ignore")
        text_parts.append(sample)
        text = "\n".join(text_parts)
        claim = "unverified_document"

    foreign = is_foreign_report(text)
    if foreign:
        reasons.append("foreign_or_misclassified")

    expected = parse_expected_period(expected_period)
    found = parse_period_text(text)
    period_status = compare_periods(expected, found) if body is not None else "unresolved"
    if body is None:
        period_status = "unresolved"
    if period_status == "mismatch":
        reasons.append("period_mismatch")

    declared = declared_symbol.strip().upper() if declared_symbol else None
    labeled = trading_codes_in_text(text)
    named = filename_codes(file_name or title)
    detected_symbol = next(iter(labeled)) if len(labeled) == 1 else None
    company_match = "unresolved"
    symbol = declared
    if declared and detected_symbol and declared != detected_symbol:
        company_match = "mismatch"
        reasons.append("company_mismatch")
    elif declared and named and declared not in named and len(named) == 1:
        detected_symbol = next(iter(named))
        company_match = "mismatch"
        reasons.append("company_mismatch")
    elif declared and (symbol_in_text(declared, text) or detected_symbol == declared):
        company_match = "matched"
        detected_symbol = declared
    elif not declared and detected_symbol:
        company_match = "matched"
        symbol = detected_symbol
    elif declared:
        company_match = "unresolved"

    period = found.label if found else (expected.label if expected and period_status != "mismatch" else None)
    verified = False
    if (
        body is not None
        and detected == "application/pdf"
        and consistent
        and company_match == "matched"
        and found is not None
        and found.kind == "annual"
        and period_status in {"matched", "resolved"}
        and contains_annual_phrase(text)
        and not foreign
        and not reasons
    ):
        verified = True
        claim = "verified_annual_report"
    if body is None:
        claim = "metadata_only"
        verified = False

    return {
        "symbol": symbol,
        "detectedSymbol": detected_symbol,
        "title": title or None,
        "declaredMime": header_mime(declared_mime) or None,
        "detectedMime": detected or None,
        "mimeConsistent": consistent,
        "documentClaim": claim,
        "verifiedAnnualReport": verified,
        "period": period,
        "periodStatus": period_status,
        "companyMatch": company_match,
        "foreignReport": foreign,
        "quarantineReasons": list(dict.fromkeys(reasons)),
        "recordType": "financial_document",
    }
