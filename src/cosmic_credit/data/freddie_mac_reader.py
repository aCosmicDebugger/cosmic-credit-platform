import csv
from io import TextIOWrapper
from zipfile import ZipFile

from cosmic_credit.data.freddie_mac_schema import parse_record


def iter_records(zip_path, member_name, columns):
    """Yield mapped records without loading the entire file into memory."""
    with ZipFile(zip_path) as archive:  # noqa: SIM117
        with archive.open(member_name) as binary:
            with TextIOWrapper(
                binary, encoding="utf-8-sig", newline=""
            ) as text:
                reader = csv.reader(text, delimiter="|", strict=True)

                for number, row in enumerate(reader, start=1):
                    try:
                        record = parse_record(row, columns)
                    except ValueError as error:
                        raise ValueError(
                            f"{member_name}: record {number}: {error}"
                        ) from error

                    yield record