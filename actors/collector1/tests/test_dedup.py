from conftest import run, staged


def test_identical_bytes_keep_one_canonical_bar():
    text = "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"
    result = run(
        files=[
            staged(text, sourceUrl="https://www.dsebd.org/one.csv", fileName="one.csv"),
            staged(text, sourceUrl="https://www.dsebd.org/two.csv", fileName="two.csv"),
        ]
    )
    canonical = [
        row
        for row in result.records
        if row["recordType"] == "eod_bar" and row["lane"] == "accepted" and row["isCanonical"]
    ]
    duplicates = [row for row in result.records if row["dedupStatus"] == "duplicate"]
    assert len(canonical) == 1
    assert duplicates
    assert duplicates[0]["canonicalRecordId"] in result.checkpoint["canonicalBySha"].values()
    assert duplicates[0]["isCanonical"] is False
    assert len(result.checkpoint["canonicalBySha"]) == 1
    assert result.checkpoint["acceptedBars"]["GP|2024-01-15"]["close"] == 10


def test_conflicting_bar_does_not_overwrite_canonical_close():
    first = "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"
    second = "TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,99\n"
    result = run(
        files=[
            staged(first, sourceUrl="https://www.dsebd.org/one.csv", fileName="one.csv"),
            staged(second, sourceUrl="https://www.dsebd.org/two.csv", fileName="two.csv"),
        ]
    )
    assert result.checkpoint["acceptedBars"]["GP|2024-01-15"]["close"] == 10
    conflict = [
        row for row in result.records if "conflicting_bar" in row["quarantineReasons"] and row["close"] == 99
    ]
    assert conflict
    assert conflict[0]["lane"] == "quarantine"
    assert conflict[0]["promoted"] is False
