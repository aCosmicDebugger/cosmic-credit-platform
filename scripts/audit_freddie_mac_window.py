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
    if len(value) != 6 or not value.isascii() or not value.isdigit():
        raise ValueError(f"Invalid YYYYMM: {value!r}")

    year = int(value[:4])
    month = int(value[4:])

    if not (1900 <= year <= 2100 and 1 <= month <= 12):
        raise ValueError(f"Invalid YYYYMM: {value!r}")

    return year * 12 + month - 1


@dataclass(slots=True)
class Window:
    first_payment: int
    observed_mask: int = 0
    numeric_status_mask: int = 0
    numeric_90plus: bool = False
    reo_status: bool = False
    unknown_status: bool = False
    termination_in_window: bool = False


def main():
    parser = argparse.ArgumentParser(
        description="Audit delinquency and termination in a 12-month window"
    )
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if not args.zip.is_file():
        raise FileNotFoundError(args.zip)
    if args.report.resolve() == args.zip.resolve():
        raise ValueError("Report must not overwrite source")
    if args.report.exists():
        raise FileExistsError(args.report)

    loans = {}
    for record in iter_records(
        args.zip,
        f"orig_{args.quarter}.txt",
        ORIGINATION_COLUMNS,
    ):
        loan_id = record["loan_id"]
        if not loan_id.strip() or loan_id in loans:
            raise ValueError("Empty or duplicate origination ID")

        loans[loan_id] = Window(
            first_payment=month_index(record["first_payment_date"])
        )

    status_counts = Counter()
    termination_codes = Counter()
    termination_effective_codes = Counter()
    checks = Counter()

    for number, record in enumerate(
        iter_records(
            args.zip,
            f"perf_{args.quarter}.txt",
            PERFORMANCE_COLUMNS,
        ),
        start=1,
    ):
        checks["performance_records"] += 1
        if number % 500_000 == 0:
            print(f"Performance: {number:,} records", flush=True)

        loan = loans.get(record["loan_id"])
        if loan is None:
            raise ValueError("Performance ID without origination")

        period = month_index(record["period"])
        offset = period - loan.first_payment
        in_window = 0 <= offset < 12

        code = record["zero_balance_code"].strip()
        effective_date = record["zero_balance_effective_date"].strip()

        # Inspect effective event dates even when reported outside the window.
        if code:
            checks["termination_code_records_all_periods"] += 1

            if not effective_date:
                checks["termination_code_without_effective_date"] += 1
            else:
                try:
                    effective = month_index(effective_date)
                except ValueError:
                    checks["invalid_termination_effective_date"] += 1
                else:
                    effective_offset = effective - loan.first_payment
                    if 0 <= effective_offset < 12:
                        loan.termination_in_window = True
                        termination_effective_codes[code] += 1
                        if not in_window:
                            checks[
                                "termination_in_window_reported_outside"
                            ] += 1

        if not in_window:
            continue

        checks["records_in_window"] += 1
        bit = 1 << offset
        if loan.observed_mask & bit:
            raise ValueError("Duplicate loan/month inside window")
        loan.observed_mask |= bit

        status = record["current_loan_delinquency_status"].strip()
        status_counts[status or "(blank)"] += 1

        is_numeric_status = (
            status.isascii()
            and status.isdigit()
            and 0 <= int(status) <= 99
        )

        if is_numeric_status:
            loan.numeric_status_mask |= bit
            if int(status) >= 3:
                loan.numeric_90plus = True
        elif status == "RA":
            loan.reo_status = True
        else:
            loan.unknown_status = True

        if code:
            termination_codes[code] += 1

    coverage = Counter()
    joint_groups = Counter()
    full_mask = (1 << 12) - 1

    for loan in loans.values():
        coverage[str(loan.observed_mask.bit_count())] += 1

        # Joint categories preserve overlapping findings.
        group = (
            f"complete_rows={loan.observed_mask == full_mask};"
            f"complete_numeric_status={loan.numeric_status_mask == full_mask};"
            f"numeric_90plus={loan.numeric_90plus};"
            f"reo={loan.reo_status};"
            f"unknown_status={loan.unknown_status};"
            f"termination_in_window={loan.termination_in_window}"
        )
        joint_groups[group] += 1

    if sum(coverage.values()) != len(loans):
        raise ValueError("Coverage count does not reconcile")

    report = {
        "schema_version": 1,
        "source_schema": SCHEMA_VERSION,
        "source_zip": str(args.zip),
        "quarter": args.quarter,
        "window": "first payment month through first payment month + 11",
        "n_loans": len(loans),
        "checks": dict(sorted(checks.items())),
        "status_records_in_window": dict(sorted(status_counts.items())),
        "termination_code_records_reported_in_window": dict(
            sorted(termination_codes.items())
        ),
        "termination_code_records_effective_in_window": dict(
            sorted(termination_effective_codes.items())
        ),
        "loans_by_observed_months": dict(
            sorted(coverage.items(), key=lambda item: int(item[0]))
        ),
        "loan_counts_by_joint_diagnostics": dict(sorted(joint_groups.items())),
        "definitions": {
            "numeric_90plus": "numeric delinquency status from 03 through 99",
            "reo": "RA recorded separately; no final target rule applied",
            "unknown_status": "any nonnumeric status other than RA",
            "termination_in_window": (
                "nonempty zero balance code with effective date in window; "
                "does not imply voluntary payoff"
            ),
        },
        "limitations": (
            "Diagnostic only. No final target or eligibility label. "
            "Effective termination dates may be disclosed after the window; "
            "historical label availability is not established."
        ),
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    print(f"Saved: {args.report}")


if __name__ == "__main__":
    main()