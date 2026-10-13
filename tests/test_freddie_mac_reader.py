from zipfile import ZipFile

import pytest

from cosmic_credit.data.freddie_mac_reader import iter_records


def make_archive(tmp_path, content):
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("sample.txt", content)
    return path


def test_preserves_codes_empty_fields_and_leading_zeros(tmp_path):
    path = make_archive(tmp_path, "0001|00|\n0002|9999|OTHER\n")

    records = list(
        iter_records(path, "sample.txt", ("id", "status", "seller"))
    )

    assert records == [
        {"id": "0001", "status": "00", "seller": ""},
        {"id": "0002", "status": "9999", "seller": "OTHER"},
    ]


def test_reads_valid_record_before_reaching_invalid_record(tmp_path):
    path = make_archive(tmp_path, "A|00\nB|01|extra\n")
    records = iter_records(path, "sample.txt", ("id", "status"))

    try:
        assert next(records) == {"id": "A", "status": "00"}
        with pytest.raises(ValueError, match="sample.txt: record 2"):
            next(records)
    finally:
        records.close()


def test_missing_member_raises_error(tmp_path):
    path = make_archive(tmp_path, "A|00\n")

    with pytest.raises(KeyError):
        list(iter_records(path, "missing.txt", ("id", "status")))