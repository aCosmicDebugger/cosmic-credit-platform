import argparse
import json
import sqlite3
from contextlib import closing
from itertools import islice
from pathlib import Path

from cosmic_credit.data.freddie_mac_reader import iter_records
from cosmic_credit.data.freddie_mac_schema import (
    ORIGINATION_COLUMNS,
    PERFORMANCE_COLUMNS,
    SCHEMA_VERSION,
)

BATCH_SIZE = 50_000


def insert_batches(connection, records, statement, columns, label):
    count = 0

    while batch := list(islice(records, BATCH_SIZE)):
        rows = [
            tuple(record[column] for column in columns)
            for record in batch
        ]
        with connection:
            connection.executemany(statement, rows)

        count += len(rows)
        print(f"{label}: {count:,} records indexed", flush=True)

    return count


def scalar(connection, query):
    return connection.execute(query).fetchone()[0]


def main():
    parser = argparse.ArgumentParser(
        description="Audit Freddie Mac origination and performance keys"
    )
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if not args.zip.is_file():
        raise FileNotFoundError(args.zip)

    paths = [args.zip, args.database, args.report]
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("Input and output paths must be distinct")

    for path in [args.database, args.report]:
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    orig_member = f"orig_{args.quarter}.txt"
    perf_member = f"perf_{args.quarter}.txt"

    with closing(sqlite3.connect(args.database)) as connection:
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute("PRAGMA cache_size = -65536")

        connection.executescript(
            """
            CREATE TABLE origination (
                loan_id TEXT PRIMARY KEY,
                n_records INTEGER NOT NULL
            ) WITHOUT ROWID;

            CREATE TABLE performance (
                loan_id TEXT NOT NULL,
                period TEXT NOT NULL,
                n_records INTEGER NOT NULL,
                PRIMARY KEY (loan_id, period)
            ) WITHOUT ROWID;
            """
        )

        with closing(
            iter_records(args.zip, orig_member, ORIGINATION_COLUMNS)
        ) as records:
            orig_count = insert_batches(
                connection,
                records,
                """
                INSERT INTO origination VALUES (?, 1)
                ON CONFLICT(loan_id)
                DO UPDATE SET n_records = n_records + 1
                """,
                ["loan_id"],
                "Origination",
            )

        with closing(
            iter_records(args.zip, perf_member, PERFORMANCE_COLUMNS)
        ) as records:
            perf_count = insert_batches(
                connection,
                records,
                """
                INSERT INTO performance VALUES (?, ?, 1)
                ON CONFLICT(loan_id, period)
                DO UPDATE SET n_records = n_records + 1
                """,
                ["loan_id", "period"],
                "Performance",
            )

        print("Computing audit results...", flush=True)

        queries = {
            "origination_distinct_nonempty_ids": """
                SELECT COUNT(*) FROM origination
                WHERE TRIM(loan_id) <> ''
            """,
            "origination_empty_id_records": """
                SELECT COALESCE(SUM(n_records), 0) FROM origination
                WHERE TRIM(loan_id) = ''
            """,
            "origination_duplicate_nonempty_ids": """
                SELECT COUNT(*) FROM origination
                WHERE TRIM(loan_id) <> '' AND n_records > 1
            """,
            "origination_excess_duplicate_records": """
                SELECT COALESCE(SUM(n_records - 1), 0) FROM origination
                WHERE TRIM(loan_id) <> '' AND n_records > 1
            """,
            "performance_empty_id_records": """
                SELECT COALESCE(SUM(n_records), 0) FROM performance
                WHERE TRIM(loan_id) = ''
            """,
            "performance_empty_period_records": """
                SELECT COALESCE(SUM(n_records), 0) FROM performance
                WHERE TRIM(period) = ''
            """,
            "performance_duplicate_nonempty_keys": """
                SELECT COUNT(*) FROM performance
                WHERE TRIM(loan_id) <> '' AND TRIM(period) <> ''
                  AND n_records > 1
            """,
            "performance_excess_duplicate_records": """
                SELECT COALESCE(SUM(n_records - 1), 0)
                FROM performance
                WHERE TRIM(loan_id) <> '' AND TRIM(period) <> ''
                  AND n_records > 1
            """,
            "performance_distinct_nonempty_ids": """
                SELECT COUNT(DISTINCT loan_id) FROM performance
                WHERE TRIM(loan_id) <> ''
            """,
            "performance_ids_without_origination": """
                SELECT COUNT(DISTINCT p.loan_id)
                FROM performance AS p
                WHERE TRIM(p.loan_id) <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM origination AS o
                      WHERE o.loan_id = p.loan_id
                  )
            """,
            "performance_records_without_origination": """
                SELECT COALESCE(SUM(p.n_records), 0)
                FROM performance AS p
                WHERE TRIM(p.loan_id) <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM origination AS o
                      WHERE o.loan_id = p.loan_id
                  )
            """,
            "origination_ids_without_performance": """
                SELECT COUNT(*) FROM origination AS o
                WHERE TRIM(o.loan_id) <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM performance AS p
                      WHERE p.loan_id = o.loan_id
                  )
            """,
        }

        checks = {
            name: scalar(connection, query)
            for name, query in queries.items()
        }

    report = {
        "schema_version": 1,
        "source_schema": SCHEMA_VERSION,
        "source_zip": str(args.zip),
        "quarter": args.quarter,
        "origination_records": orig_count,
        "performance_records": perf_count,
        "checks": checks,
        "scope": (
            "Key completeness, uniqueness and cross-file linkage. "
            "Does not validate dates, field domains or target maturity. "
            "Duplicate keys are counted, not resolved."
        ),
    }

    args.report.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    print(f"Saved report: {args.report}")


if __name__ == "__main__":
    main()