from conftest import run, staged


def test_unknown_and_non_trading_absences_are_not_proven_missing():
    text = "\n".join(
        [
            "TRADING CODE,DATE,CLOSEP,NON_TRADING",
            "GP,2024-01-15,10,",
            "ABCD,2024-01-16,,yes",
        ]
    )
    result = run(
        files=[staged(text)],
        symbols=["GP", "ABCD"],
        sessions=["2024-01-15", "2024-01-16", "2024-01-17"],
    )
    assert all(row["provenMissing"] is False for row in result.records)
    assert all(row["provenMissing"] is False for row in result.coverage_manifest["rows"])
    status = {(row["symbol"], row["tradeDate"]): row["absenceStatus"] for row in result.coverage_manifest["rows"]}
    assert status[("GP", "2024-01-15")] == "observed"
    assert status[("ABCD", "2024-01-16")] == "non_trading"
    assert status[("GP", "2024-01-16")] == "unknown"
    assert status[("GP", "2024-01-17")] == "unknown"
    assert status[("ABCD", "2024-01-15")] == "unknown"
    assert status[("ABCD", "2024-01-17")] == "unknown"
    assert not any(row["recordType"] == "eod_bar" and row["symbol"] == "ABCD" and row["lane"] == "accepted" for row in result.records)


def test_input_cannot_force_a_proven_missing_flag():
    config_text = {
        "symbols": ["GP"],
        "sessions": ["2024-01-15"],
        "provenMissing": True,
        "markMissing": True,
    }
    result = run(files=[], symbols=config_text["symbols"], sessions=config_text["sessions"])
    assert result.coverage_manifest["rows"][0]["absenceStatus"] == "unknown"
    assert result.coverage_manifest["rows"][0]["provenMissing"] is False
    assert all(row.get("provenMissing") is False for row in result.records)
