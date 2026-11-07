from conftest import run, staged


FOREIGN = (
    b"%PDF-1.4\nForm 10-K\nUnited States Securities and Exchange Commission\nNASDAQ\nAnnual Report 2024\n"
)


def test_foreign_report_is_quarantined_and_retained():
    result = run(
        files=[
            staged(
                FOREIGN,
                fileName="issuer_10k.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                title="Form 10-K",
                sourceUrl="https://www.dsebd.org/inbox/issuer_10k.pdf",
            )
        ]
    )
    rows = [row for row in result.records if row["recordType"] == "financial_document"]
    assert rows
    assert all(row["deleted"] is False and row["retained"] is True for row in rows)
    quarantined = [row for row in rows if row["lane"] == "quarantine"]
    assert quarantined
    assert quarantined[0]["foreignReport"] is True
    assert "foreign_or_misclassified" in quarantined[0]["quarantineReasons"]
    assert quarantined[0]["verifiedAnnualReport"] is False
    assert quarantined[0]["symbol"] == "GP"


def test_filename_conflict_does_not_rename_symbol():
    body = b"%PDF-1.4\nAnnual Report 2024\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
    result = run(
        files=[
            staged(
                body,
                fileName="GP_Annual_Report_2024.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="NRBBANK",
                expectedPeriod="FY2024",
                sourceUrl="https://www.dsebd.org/reports/GP_Annual_Report_2024.pdf",
            )
        ]
    )
    documents = [row for row in result.records if row["recordType"] == "financial_document"]
    assert documents
    assert all(row["symbol"] in {None, "NRBBANK"} for row in documents)
    assert any(row["detectedSymbol"] == "GP" and row["companyMatch"] == "mismatch" for row in documents)
    assert not any(row["symbol"] == "GP" and row["lane"] == "accepted" for row in documents)
    assert all(row["verifiedAnnualReport"] is False for row in documents)


def test_metadata_only_is_never_a_verified_annual_report():
    result = run(
        files=[
            {
                "sourceUrl": "https://www.dsebd.org/reports/GP_Annual_Report_2024.pdf",
                "fileName": "GP_Annual_Report_2024.pdf",
                "kind": "document_metadata",
                "title": "Annual Report 2024",
                "symbol": "GP",
                "expectedPeriod": "FY2024",
            }
        ]
    )
    claims = [row for row in result.records if row["documentClaim"] == "metadata_only"]
    assert claims
    assert all(row["verifiedAnnualReport"] is False for row in result.records)
    assert all(row["documentClaim"] != "verified_annual_report" for row in result.records)


def test_sample_pdf_cannot_become_verified():
    body = b"%PDF-1.4\nAnnual Report 2024\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
    result = run(
        files=[
            staged(
                body,
                fileName="GP_Annual_Report_2024.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                sample=True,
                sourceUrl="https://www.dsebd.org/reports/GP_Annual_Report_2024.pdf",
            )
        ]
    )
    assert any(row["sample"] is True for row in result.records)
    assert all(row["verifiedAnnualReport"] is False for row in result.records)
