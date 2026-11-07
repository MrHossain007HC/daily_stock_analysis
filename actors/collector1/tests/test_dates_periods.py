from conftest import run, staged


def test_dse_date_formats_and_invalid_dates_are_per_row():
    text = "\n".join(
        [
            "TRADING CODE,DATE,CLOSEP",
            "GP,15-01-2024,10",
            "GP,2024/01/16,11",
            "GP,17/01/2024,12",
            "GP,18-Jan-2024,13",
            "GP,31-02-2024,14",
            "GP,2024-13-01,15",
        ]
    )
    result = run(files=[staged(text)])
    accepted = {
        row["tradeDate"]: row["close"]
        for row in result.records
        if row["lane"] == "accepted" and row["recordType"] == "eod_bar"
    }
    assert accepted == {
        "2024-01-15": 10,
        "2024-01-16": 11,
        "2024-01-17": 12,
        "2024-01-18": 13,
    }
    invalid = [row for row in result.records if row["lane"] == "quarantine" and row["recordType"] == "eod_bar"]
    assert len(invalid) == 2
    assert all(any(error["field"] == "tradeDate" for error in row["fieldErrors"]) for row in invalid)


def test_price_range_keeps_other_fields():
    text = "TRADING CODE,DATE,HIGH,LOW,CLOSEP\nGP,2024-01-15,1,2,1.5\n"
    result = run(files=[staged(text)])
    row = next(row for row in result.records if row["lane"] == "quarantine" and row["recordType"] == "eod_bar")
    assert row["close"] == 1.5
    assert any(error["code"] == "price_range" for error in row["fieldErrors"])


def test_period_match_mismatch_and_unresolved():
    matched = (
        b"%PDF-1.4\nAnnual Report 2024\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
    )
    mismatch = (
        b"%PDF-1.4\nAnnual Report 2023\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
    )
    unresolved = b"%PDF-1.4\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
    result = run(
        files=[
            staged(
                matched,
                fileName="GP_Annual_Report_2024.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                sourceUrl="https://www.dsebd.org/reports/matched.pdf",
            ),
            staged(
                mismatch,
                fileName="GP_Annual_Report_2023.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                sourceUrl="https://www.dsebd.org/reports/mismatch.pdf",
            ),
            staged(
                unresolved,
                fileName="GP_statement.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                sourceUrl="https://www.dsebd.org/reports/unresolved.pdf",
            ),
        ]
    )
    by_url = {
        row["sourceUrl"]: row
        for row in result.records
        if row["recordType"] == "financial_document" and row["lane"] in {"accepted", "quarantine"}
    }
    assert by_url["https://www.dsebd.org/reports/matched.pdf"]["verifiedAnnualReport"] is True
    assert by_url["https://www.dsebd.org/reports/matched.pdf"]["period"] == "FY2024"
    mismatched = by_url["https://www.dsebd.org/reports/mismatch.pdf"]
    assert mismatched["verifiedAnnualReport"] is False
    assert mismatched["periodStatus"] == "mismatch"
    assert "period_mismatch" in mismatched["quarantineReasons"]
    unresolved_row = by_url["https://www.dsebd.org/reports/unresolved.pdf"]
    assert unresolved_row["verifiedAnnualReport"] is False
    assert unresolved_row["periodStatus"] == "unresolved"
    assert unresolved_row["documentClaim"] != "verified_annual_report"


def test_rows_outside_requested_range_are_not_treated_as_missing_sessions():
    text = "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\nGP,2024-02-01,11\n"
    result = run(
        files=[staged(text)],
        symbols=["GP"],
        sessions=["2024-01-15", "2024-02-01"],
        date_from="2024-01-01",
        date_to="2024-01-31",
    )
    assert any(row["tradeDate"] == "2024-02-01" and "outside_requested_range" in row["quarantineReasons"] for row in result.records)
    feb = next(row for row in result.coverage_manifest["rows"] if row["tradeDate"] == "2024-02-01")
    jan = next(row for row in result.coverage_manifest["rows"] if row["tradeDate"] == "2024-01-15")
    assert jan["absenceStatus"] == "observed"
    assert feb["absenceStatus"] == "unknown"
    assert feb["provenMissing"] is False
