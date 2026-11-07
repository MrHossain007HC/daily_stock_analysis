"""Per-field validation. A negative NAV is a real value, not a rejected record."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,19}$")
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%B-%Y",
    "%d %B %Y",
)

FILENAME_STOPLIST = {
    "ANNUAL",
    "REPORT",
    "PDF",
    "FY",
    "THE",
    "AND",
    "FOR",
    "YEAR",
    "HALF",
    "YEARLY",
    "FINANCIAL",
    "STATEMENT",
    "STATEMENTS",
    "UNAUDITED",
    "AUDITED",
    "DSE",
    "DHAKA",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "CSV",
    "XLSX",
    "ZIP",
}

FOREIGN_PHRASES = (
    "form 10-k",
    "form 10-q",
    "form 20-f",
    "nasdaq",
    "nyse",
    "united states securities and exchange commission",
    "u.s. securities and exchange commission",
)
LOCAL_PHRASES = ("dhaka", "bangladesh", "dsebd", "dse", "bdt", "taka")
PERIOD_FY = re.compile(r"\bFY\s*([12]\d{3})\b", re.IGNORECASE)
PERIOD_ANNUAL = re.compile(
    r"\b(?:annual report|for the year|year ended\s+\d{1,2}\s+[A-Za-z]+)\s+([12]\d{3})\b",
    re.IGNORECASE,
)
PERIOD_QUARTER = re.compile(r"\bQ([1-4])\s*[-/ ]?\s*([12]\d{3})\b", re.IGNORECASE)
PERIOD_HALF = re.compile(r"\bhalf[-\s]?yearly\s+([12]\d{3})\b", re.IGNORECASE)
EXPECTED_PERIOD = re.compile(r"^(FY|Q[1-4]|HY)([12]\d{3})$", re.IGNORECASE)
TRADING_CODE = re.compile(r"trading code\s*[:\-]\s*([A-Za-z][A-Za-z0-9]{1,11})", re.IGNORECASE)
FILENAME_CODE = re.compile(r"(?:^|[_\-.])([A-Z][A-Z0-9]{1,11})(?=[_\-.]|$)")


@dataclass(frozen=True)
class Period:
    kind: str
    year: int
    label: str


def valid_symbol(value: str) -> bool:
    return bool(SYMBOL_RE.match(value.strip().upper()))


def parse_trade_date(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_number(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = text.replace(",", "")
    if text.startswith("-"):
        negative = True
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    try:
        number = float(text)
    except ValueError:
        return "invalid"
    if negative:
        number = -number
    if not math.isfinite(number):
        return "invalid"
    return number


def field_error(field_name: str, code: str) -> dict:
    return {"field": field_name, "code": code}


def validate_price(field_name: str, value):
    number = parse_number(value)
    if number is None:
        return None, None
    if number == "invalid":
        return None, field_error(field_name, "invalid_number")
    if number < 0:
        return number, field_error(field_name, "negative_price")
    return number, None


def validate_volume(value):
    number = parse_number(value)
    if number is None:
        return None, None
    if number == "invalid":
        return None, field_error("volume", "invalid_number")
    if number < 0:
        return number, field_error("volume", "negative_volume")
    return number, None


def validate_nav(value):
    """Negative NAV is legitimate and is not itself a field error."""
    number = parse_number(value)
    if number is None:
        return None, None
    if number == "invalid":
        return None, field_error("nav", "nav_not_numeric")
    return number, None


def parse_period_text(text: str) -> Period | None:
    if not text:
        return None
    quarters = {(int(year), int(quarter)) for quarter, year in PERIOD_QUARTER.findall(text)}
    halves = {int(year) for year in PERIOD_HALF.findall(text)}
    annuals = {int(year) for year in PERIOD_FY.findall(text)}
    annuals.update(int(year) for year in PERIOD_ANNUAL.findall(text))
    found = []
    if len(quarters) == 1 and not halves and not annuals:
        year, quarter = next(iter(quarters))
        found.append(Period("quarter", year, f"Q{quarter}{year}"))
    if len(halves) == 1 and not quarters and not annuals:
        year = next(iter(halves))
        found.append(Period("half", year, f"HY{year}"))
    if len(annuals) == 1 and not quarters and not halves:
        year = next(iter(annuals))
        found.append(Period("annual", year, f"FY{year}"))
    if len(found) == 1:
        return found[0]
    return None


def parse_expected_period(value: str | None) -> Period | None:
    if not value:
        return None
    match = EXPECTED_PERIOD.match(value.strip().upper())
    if not match:
        return None
    kind_token, year_text = match.group(1).upper(), int(match.group(2))
    if kind_token == "FY":
        return Period("annual", year_text, f"FY{year_text}")
    if kind_token == "HY":
        return Period("half", year_text, f"HY{year_text}")
    return Period("quarter", year_text, f"{kind_token}{year_text}")


def compare_periods(expected: Period | None, found: Period | None) -> str:
    if expected and found and (expected.kind != found.kind or expected.year != found.year):
        return "mismatch"
    if expected and found:
        return "matched"
    if found:
        return "resolved"
    return "unresolved"


def filename_codes(file_name: str) -> set[str]:
    stem = file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()
    return {code for code in FILENAME_CODE.findall(stem) if code not in FILENAME_STOPLIST}


def trading_codes_in_text(text: str) -> set[str]:
    return {code.upper() for code in TRADING_CODE.findall(text)}


def is_foreign_report(text: str) -> bool:
    lowered = text.lower()
    foreign = any(phrase in lowered for phrase in FOREIGN_PHRASES)
    local = any(phrase in lowered for phrase in LOCAL_PHRASES)
    return foreign and not local


def contains_annual_phrase(text: str) -> bool:
    return "annual report" in text.lower()


def symbol_in_text(symbol: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(symbol)}\b", text, re.IGNORECASE) is not None
