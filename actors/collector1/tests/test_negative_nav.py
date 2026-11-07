from io import BytesIO

from openpyxl import Workbook

from conftest import encode, run, staged


def test_negative_nav_is_accepted_on_eod_and_profile():
    eod = "TRADING CODE,DATE,CLOSEP,NAV\nGP,2024-01-15,10,-3.5\n"
    profile = "TRADING CODE,NAV\nSQURPHARMA,-12.25\n"
    result = run(
        files=[
            staged(eod),
            staged(
                profile,
                sourceUrl="https://www.dsebd.org/profiles.csv",
                fileName="profiles.csv",
            ),
        ]
    )
    bar = next(row for row in result.records if row["recordType"] == "eod_bar" and row["lane"] == "accepted")
    company = next(
        row for row in result.records if row["recordType"] == "company_profile" and row["lane"] == "accepted"
    )
    assert bar["nav"] == -3.5
    assert bar["fieldErrors"] == []
    assert company["nav"] == -12.25
    assert company["symbol"] == "SQURPHARMA"


def test_negative_close_quarantines_without_blaming_nav():
    text = "TRADING CODE,DATE,CLOSEP,NAV\nNRBBANK,2024-01-15,-1,-4\n"
    result = run(files=[staged(text)])
    row = next(row for row in result.records if row["lane"] == "quarantine" and row["symbol"] == "NRBBANK")
    assert row["close"] == -1
    assert row["nav"] == -4
    assert {error["field"] for error in row["fieldErrors"]} == {"close"}
    assert "nav" not in {error["field"] for error in row["fieldErrors"]}
    assert row["promoted"] is False


def test_invalid_nav_is_its_own_field_error():
    text = "TRADING CODE,DATE,CLOSEP,NAV\nGP,2024-01-15,10,n/a\n"
    result = run(files=[staged(text)])
    row = next(row for row in result.records if row["lane"] == "quarantine" and row["recordType"] == "eod_bar")
    assert row["close"] == 10
    assert any(error["field"] == "nav" and error["code"] == "nav_not_numeric" for error in row["fieldErrors"])


def test_xlsx_negative_nav_and_negative_volume_are_separate():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["TRADING CODE", "DATE", "CLOSEP", "NAV", "VOLUME"])
    sheet.append(["GP", "2024-01-15", 10, -2, 100])
    sheet.append(["ACI", "2024-01-15", 8, 1, -5])
    buffer = BytesIO()
    workbook.save(buffer)
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    result = run(
        files=[
            staged(
                buffer.getvalue(),
                fileName="book.xlsx",
                declaredMime=mime,
                sourceUrl="https://www.dsebd.org/book.xlsx",
            )
        ]
    )
    accepted = next(row for row in result.records if row["lane"] == "accepted" and row["symbol"] == "GP")
    quarantined = next(row for row in result.records if row["lane"] == "quarantine" and row["symbol"] == "ACI")
    assert accepted["nav"] == -2
    assert quarantined["close"] == 8
    assert quarantined["volume"] == -5
    assert any(error["field"] == "volume" for error in quarantined["fieldErrors"])
    assert encode(buffer.getvalue())
