"""Staged CSV and XLSX end-of-day parsing."""

from __future__ import annotations

import csv
from io import BytesIO, StringIO

from .validate import parse_number, parse_trade_date, valid_symbol, validate_nav, validate_price, validate_volume

HEADER_MAP = {
    "trading code": "symbol",
    "trading_code": "symbol",
    "symbol": "symbol",
    "code": "symbol",
    "scrip": "symbol",
    "date": "trade_date",
    "trade date": "trade_date",
    "trade_date": "trade_date",
    "trading date": "trade_date",
    "open": "open",
    "openp": "open",
    "open price": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "closep": "close",
    "close price": "close",
    "ltp": "ltp",
    "ycp": "ycp",
    "volume": "volume",
    "vol": "volume",
    "value": "value",
    "trade": "trades",
    "trades": "trades",
    "nav": "nav",
    "net asset value": "nav",
    "non_trading": "non_trading",
    "non trading": "non_trading",
    "official_non_trading": "non_trading",
}
PRICE_FIELDS = ("open", "high", "low", "close", "ltp", "ycp")


def _map_header(name: str) -> str | None:
    return HEADER_MAP.get(name.strip().lower())


def _delimiter(header_line: str) -> str:
    counts = {",": header_line.count(","), "\t": header_line.count("\t"), ";": header_line.count(";")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def parse_tabular_text(text: str) -> tuple[list[dict], str | None]:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [], "empty_table"
    reader = csv.reader(StringIO("\n".join(lines)), delimiter=_delimiter(lines[0]))
    try:
        csv.field_size_limit(1_000_000)
        header = next(reader)
    except (StopIteration, csv.Error):
        return [], "empty_table"
    mapped = [_map_header(cell) for cell in header]
    if not any(mapped):
        return [], "empty_table"
    rows = []
    try:
        raw_rows = list(reader)
    except csv.Error:
        return [], "oversized_row"
    for raw in raw_rows:
        if not any(cell.strip() for cell in raw):
            continue
        item = {}
        for index, key in enumerate(mapped):
            if key is None or index >= len(raw):
                continue
            item[key] = raw[index].strip()
        rows.append(item)
    if not rows:
        return [], "empty_table"
    return rows, None


def parse_xlsx(body: bytes) -> tuple[list[dict], str | None]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(BytesIO(body), read_only=True, data_only=True)
    except Exception:
        return [], "corrupt_spreadsheet"
    try:
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        header_row = next(values, None)
        if not header_row:
            return [], "empty_table"
        mapped = [_map_header(str(cell)) if cell is not None else None for cell in header_row]
        if not any(mapped):
            return [], "empty_table"
        rows = []
        for raw in values:
            if raw is None or not any(cell is not None and str(cell).strip() for cell in raw):
                continue
            item = {}
            for index, key in enumerate(mapped):
                if key is None or index >= len(raw) or raw[index] is None:
                    continue
                item[key] = str(raw[index]).strip()
            rows.append(item)
        if not rows:
            return [], "empty_table"
        return rows, None
    finally:
        workbook.close()


def table_kind(rows: list[dict]) -> str:
    has_price = any(field in row and row[field] != "" for row in rows for field in PRICE_FIELDS)
    has_nav = any("nav" in row and row["nav"] != "" for row in rows)
    if has_nav and not has_price:
        return "company_profile"
    return "eod_bar"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "y", "yes", "true", "non_trading", "non-trading"}


def interpret_row(row: dict, kind: str) -> dict:
    errors = []
    symbol_raw = row.get("symbol", "")
    symbol = symbol_raw.strip().upper()
    if not valid_symbol(symbol):
        errors.append({"field": "symbol", "code": "missing" if symbol == "" else "invalid_symbol"})
        symbol = None
    trade_date = None
    if kind == "eod_bar":
        trade_date = parse_trade_date(row.get("trade_date", ""))
        if trade_date is None:
            errors.append({"field": "tradeDate", "code": "invalid_date" if row.get("trade_date") else "missing"})
    prices = {}
    for name in PRICE_FIELDS:
        if name not in row or row[name] == "":
            prices[name] = None
            continue
        number, error = validate_price(name, row[name])
        prices[name] = number
        if error:
            errors.append(error)
    volume, volume_error = validate_volume(row.get("volume"))
    if volume_error:
        errors.append(volume_error)
    if volume == "invalid":
        volume = None
    value = parse_number(row.get("value"))
    trades = parse_number(row.get("trades"))
    if value == "invalid":
        errors.append({"field": "value", "code": "invalid_number"})
        value = None
    if trades == "invalid":
        errors.append({"field": "trades", "code": "invalid_number"})
        trades = None
    nav, nav_error = validate_nav(row.get("nav"))
    if nav_error:
        errors.append(nav_error)
    if nav == "invalid":
        nav = None
    if prices["high"] is not None and prices["low"] is not None and prices["high"] < prices["low"]:
        errors.append({"field": "high", "code": "price_range"})
    non_trading = _truthy(row.get("non_trading"))
    if kind == "eod_bar" and not non_trading and prices["close"] is None and prices["ltp"] is None:
        if not any(error["field"] in {"close", "ltp"} for error in errors):
            errors.append({"field": "close", "code": "missing"})
    return {
        "symbol": symbol,
        "tradeDate": trade_date,
        "open": prices["open"],
        "high": prices["high"],
        "low": prices["low"],
        "close": prices["close"],
        "ltp": prices["ltp"],
        "ycp": prices["ycp"],
        "volume": volume,
        "value": value,
        "trades": trades,
        "nav": nav,
        "fieldErrors": errors,
        "nonTrading": non_trading,
        "recordType": "company_profile" if kind == "company_profile" else "eod_bar",
    }
