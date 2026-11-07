from conftest import PUBLIC, failure, ok, run, staged

from collector1.documents import extract_public_links
from collector1.models import Limits


ANNUAL = (
    b"%PDF-1.4\nAnnual Report 2024\nDhaka Stock Exchange\nTrading Code: GP\nBangladesh\n"
)


def test_declared_pdf_that_is_html_is_quarantined():
    result = run(
        files=[
            staged(
                b"<html><body>not a report</body></html>",
                fileName="report.pdf",
                kind="financial_document",
                declaredMime="application/pdf",
                symbol="GP",
                expectedPeriod="FY2024",
                title="Annual Report 2024",
            )
        ]
    )
    assert any("content_mime_mismatch" in row["quarantineReasons"] for row in result.records)
    assert not any(row["verifiedAnnualReport"] for row in result.records)
    assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in result.records)


def test_octet_stream_pdf_can_be_verified():
    result = run(
        files=[
            staged(
                ANNUAL,
                fileName="GP_Annual_Report_2024.pdf",
                kind="financial_document",
                declaredMime="application/octet-stream",
                symbol="GP",
                expectedPeriod="FY2024",
                sourceUrl="https://www.dsebd.org/reports/GP_Annual_Report_2024.pdf",
            )
        ]
    )
    verified = [row for row in result.records if row["verifiedAnnualReport"] is True]
    assert len(verified) == 1
    assert verified[0]["documentClaim"] == "verified_annual_report"
    assert verified[0]["detectedMime"] == "application/pdf"
    assert verified[0]["mimeConsistent"] is True


def test_csv_labeled_as_html_is_not_parsed_as_prices():
    result = run(
        files=[
            staged(
                "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n",
                declaredMime="text/html",
            )
        ]
    )
    assert any("content_mime_mismatch" in row["quarantineReasons"] for row in result.records)
    assert not any(row["recordType"] == "eod_bar" and row["lane"] == "accepted" for row in result.records)


def test_document_html_discovers_only_public_files():
    page = "https://www.dsebd.org/company/GP"
    html = """
    <html><body>
      <a href="/reports/gp.pdf">annual</a>
      <a href="https://stocknow.com.bd/private/gp.csv">private</a>
      <a href="http://127.0.0.1/hidden.csv">local</a>
    </body></html>
    """.encode()
    pdf_url = "https://www.dsebd.org/reports/gp.pdf"
    fetcher = __import__("conftest").ScriptedFetcher(
        [
            ok(page, html, "text/html"),
            ok(pdf_url, ANNUAL, "application/pdf"),
        ]
    )
    result = run(
        mode="fetch_public",
        document_urls=[page],
        fetcher=fetcher,
        limits=Limits(max_requests=5, max_runtime_seconds=30),
    )
    assert fetcher.urls == [page, pdf_url]
    assert extract_public_links(html, page, ["dsebd.org"]) == [pdf_url]
    assert any(row["sourceUrl"] == pdf_url for row in result.records)
    assert PUBLIC
