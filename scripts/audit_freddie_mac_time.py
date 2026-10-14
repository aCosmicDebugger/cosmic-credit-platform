import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cosmic_credit.data.freddie_mac_reader import iter_records
from cosmic_credit.data.freddie_mac_schema import (
    ORIGINATION_COLUMNS,
    PERFORMANCE_COLUMNS,
    SCHEMA_VERSION,
)


def month_index(value):
    """Convert YYYYMM into an integer month index."""
    if len(value) != 6 or not value.isascii() or not value.isdigit():
        raise ValueError(f"Invalid YYYYMM: {value!r}")

    year = int(value[:4])
    month = int(value[4:])

    if not (1900 <= year <= 2100 and 1 <= month <= 12):
        raise ValueError(f"Invalid YYYYMM: {value!r}")

    return year * 12 + month - 1


def month_label(index):
    year, month = divmod(index, 12)
    return f"{year:04d}{month + 1:02d}"


@dataclass(slots=True)
class LoanHistory:
    first_payment: int
    first_period: int | None = None
    last_period: int | None = None
    months_mask: int = 0

    def add_month(self, period):
        if self.first_period is None:
            self.first_period = period
            self.last_period = period
            self.months_mask = 1
            return False

        if period < self.first_period:
            self.months_mask <<= self.first_period - period
            self.first_period = period

        bit = 1 << (period - self.first_period)
        duplicate = bool(self.months_mask & bit)
        self.months_mask |= bit
        self.last_period = max(self.last_period, period)
        return duplicate


def main():
    parser = argparse.ArgumentParser(
        description="Audit Freddie Mac monthly coverage and age alignment"
    )
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if not args.zip.is_file():
        raise FileNotFoundError(args.zip)
    if args.report.resolve() == args.zip.resolve():
        raise ValueError("Report must not overwrite the source")
    if args.report.exists():
        raise FileExistsError(args.report)

    loans = {}
    invalid_first_payment = 0
    origination_records = 0

    for record in iter_records(
        args.zip,
        f"orig_{args.quarter}.txt",
        ORIGINATION_COLUMNS,
    ):
        origination_records += 1
        loan_id = record["loan_id"]

        if loan_id in loans:
            raise ValueError("Duplicate origination ID")

        try:
            first_payment = month_index(record["first_payment_date"])
        except ValueError:
            invalid_first_payment += 1
            continue

        loans[loan_id] = LoanHistory(first_payment)

    counts = Counter()
    monthly_records = Counter()
    age_offsets = Counter()
    first_observation_offsets = Counter()
    age_alignment_by_modification = {}

    for number, record in enumerate(
        iter_records(
            args.zip,
            f"perf_{args.quarter}.txt",
            PERFORMANCE_COLUMNS,
        ),
        start=1,
    ):
        counts["performance_records"] += 1

        if number % 500_000 == 0:
            print(f"Performance: {number:,} records", flush=True)

        try:
            period = month_index(record["period"])
        except ValueError:
            counts["invalid_period_records"] += 1
            continue

        monthly_records[record["period"]] += 1
        history = loans.get(record["loan_id"])

        if history is None:
            counts["records_without_valid_origination_date"] += 1
            continue

        if history.add_month(period):
            counts["duplicate_loan_month_records"] += 1

        offset = period - history.first_payment
        if offset < 0:
            counts["records_before_first_payment"] += 1

        raw_age = record["loan_age"]
        try:
            age = int(raw_age)
        except ValueError:
            counts["noninteger_loan_age_records"] += 1
            continue

        if age < 0:
            counts["negative_loan_age_records"] += 1

        expected_age = offset + 1
        age_offsets[str(age - expected_age)] += 1
        flag = record["modification_flag"] or "(blank)"
        alignment = age_alignment_by_modification.setdefault(
            flag, {"matching": 0, "different": 0}
            )
        alignment["matching" if age == expected_age else "different"] += 1

    gap_counts = Counter()
    coverage_12m = Counter()
    gap_examples = []
    early_examples = []
    late_examples = []

    no_performance = 0
    min_period = None
    max_period = None

    for loan_id, history in loans.items():
        if history.first_period is None:
            no_performance += 1
            continue

        first = history.first_period
        last = history.last_period
        observed = history.months_mask.bit_count()
        internal_missing = last - first + 1 - observed

        first_payment = history.first_payment
        observed_offsets = {
            index
            for index in range(12)
            if first_payment + index >= first
            and (
                history.months_mask
                & (1 << (first_payment + index - first))
            )
        }
        coverage_12m[str(len(observed_offsets))] += 1

        if internal_missing and len(gap_examples) < 5:
            missing_periods = [
                month_label(first + offset)
                for offset in range(last - first + 1)
                if not (history.months_mask & (1 << offset))
            ]
            gap_examples.append(
                {
                    "loan_id": loan_id,
                    "first_period": month_label(first),
                    "last_period": month_label(last),
                    "missing_periods": missing_periods,
                }
            )

        example = {
            "loan_id": loan_id,
            "first_payment_date": month_label(first_payment),
            "first_observed_period": month_label(first),
            "first_observation_offset": first - first_payment,
            "observed_months_in_first_12": len(observed_offsets),
        }

        if first - first_payment < -1 and len(early_examples) < 5:
            early_examples.append(example)

        if first > first_payment and len(late_examples) < 5:
            late_examples.append(example)

        gap_counts[str(internal_missing)] += 1
        first_observation_offsets[str(first - first_payment)] += 1

        min_period = first if min_period is None else min(min_period, first)
        max_period = last if max_period is None else max(max_period, last)

    expected_count = len(loans) - no_performance
    if sum(coverage_12m.values()) != expected_count:
        raise ValueError("Coverage counts do not reconcile with loan count")

    if any(not 0 <= int(months) <= 12 for months in coverage_12m):
        raise ValueError("Observed coverage must be between 0 and 12 months")

    check_names = [
        "performance_records",
        "invalid_period_records",
        "records_without_valid_origination_date",
        "duplicate_loan_month_records",
        "records_before_first_payment",
        "noninteger_loan_age_records",
        "negative_loan_age_records",
    ]

    report = {
        "schema_version": 1,
        "source_schema": SCHEMA_VERSION,
        "source_zip": str(args.zip),
        "quarter": args.quarter,
        "origination_records": origination_records,
        "invalid_first_payment_dates": invalid_first_payment,
        "loans_without_valid_performance": no_performance,
        "checks": {name: counts[name] for name in check_names},
        "first_valid_period": (
            month_label(min_period) if min_period is not None else None
        ),
        "last_valid_period": (
            month_label(max_period) if max_period is not None else None
        ),
        "records_by_period": dict(sorted(monthly_records.items())),
        "loans_by_internal_missing_months": dict(
            sorted(gap_counts.items(), key=lambda item: int(item[0]))
        ),
        "loans_by_first_observation_offset": dict(
            sorted(
                first_observation_offsets.items(),
                key=lambda item: int(item[0]),
            )
        ),
        "records_by_age_minus_expected_age": dict(
            sorted(age_offsets.items(), key=lambda item: int(item[0]))
        ),
        "definitions": {
            "first_observation_offset": (
                "first observed period minus first payment date, in months"
            ),
            "expected_age": (
                "period minus first payment date, in months, plus one"
            ),
            "internal_missing_months": (
                "missing months between first and last observed period; "
                "does not assess coverage after termination"
            ),
        },
        "limitations": (
            "Age alignment is diagnostic, not a rejection rule. "
            "No target, maturity or termination classification is produced."
        ),
        "age_alignment_by_modification_flag": age_alignment_by_modification,
        "loans_by_observed_months_in_first_12": dict(
            sorted(coverage_12m.items(), key=lambda item: int(item[0]))
        ),
        "diagnostic_examples": {
            "internal_gaps": gap_examples,
            "starts_before_previous_month": early_examples,
            "late_starts": late_examples,
            },
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )

    terminal_report = {
        key: value
        for key, value in report.items()
        if key != "records_by_period"
    }
    print(json.dumps(terminal_report, indent=2))
    print(f"Saved: {args.report}")


if __name__ == "__main__":
    main()