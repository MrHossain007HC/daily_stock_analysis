import zipfile
from io import BytesIO

from conftest import run, staged

CSV = b"TRADING CODE,DATE,CLOSEP\nGP,2024-01-15,10\n"


def _zip(members):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload, flags in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    data = bytearray(buffer.getvalue())
    if any(flags & 0x1 for _name, _payload, flags in members):
        data[6] |= 0x1
        central = data.rfind(b"PK\x01\x02")
        if central != -1:
            data[central + 8] |= 0x1
    return bytes(data)


def test_safe_zip_yields_the_csv_bar():
    result = run(
        files=[
            staged(
                _zip([("eod.csv", CSV, 0)]),
                fileName="eod.zip",
                kind="zip",
                declaredMime="application/zip",
                sourceUrl="https://www.dsebd.org/archive/eod.zip",
            )
        ]
    )
    assert any(row["lane"] == "accepted" and row["symbol"] == "GP" and row["close"] == 10 for row in result.records)


def test_path_traversal_and_absolute_names_are_rejected():
    for name in ("../eod.csv", "/tmp/eod.csv"):
        result = run(
            files=[
                staged(
                    _zip([(name, CSV, 0)]),
                    fileName="bad.zip",
                    kind="zip",
                    declaredMime="application/zip",
                    sourceUrl="https://www.dsebd.org/archive/bad.zip",
                )
            ]
        )
        assert any(row["quarantineReasons"] == ["unsafe_path"] for row in result.records)
        assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in result.records)


def test_archive_bomb_and_encrypted_zip_are_rejected():
    bomb = _zip([("eod.csv", b"0" * 200_000, 0)])
    encrypted = _zip([("eod.csv", CSV, 0x1)])
    for payload, reason in ((bomb, "archive_bomb"), (encrypted, "encrypted_archive")):
        result = run(
            files=[
                staged(
                    payload,
                    fileName="risk.zip",
                    kind="zip",
                    declaredMime="application/zip",
                    sourceUrl="https://www.dsebd.org/archive/risk.zip",
                )
            ]
        )
        assert any(reason in row["quarantineReasons"] for row in result.records)
        assert not any(row["lane"] == "accepted" and row["recordType"] == "eod_bar" for row in result.records)
