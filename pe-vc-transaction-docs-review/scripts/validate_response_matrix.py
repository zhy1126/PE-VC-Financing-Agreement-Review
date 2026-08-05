#!/usr/bin/env python3
"""All seven semantic cell values are required on every Response Matrix row.

Use the explicit value ``not applicable`` or ``不适用`` when there is no
residual/new risk or no synchronized clause to record. This validator checks
CSV structure and required evidence fields, not substantive legal correctness.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from review_schema import (
    RESPONSE_KEYS,
    canonical_response_status,
    canonical_response_row,
    response_semantic_for_header,
)


def load_matrix(path: Path) -> tuple[list[str], list[dict[object, object]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        return reader.fieldnames or [], list(reader)


def validate_headers(headers: list[str]) -> list[str]:
    errors: list[str] = []
    if len(headers) != len(RESPONSE_KEYS):
        errors.append(f"expected exactly {len(RESPONSE_KEYS)} columns; found {len(headers)}")

    recognized: list[str] = []
    for header in headers:
        semantic = response_semantic_for_header(header)
        if semantic is None:
            errors.append(f"unrecognized column: {header or '<blank>'}")
        else:
            recognized.append(semantic)

    for semantic in RESPONSE_KEYS:
        count = recognized.count(semantic)
        if count == 0:
            errors.append(f"missing required semantic column: {semantic}")
        elif count > 1:
            errors.append(f"duplicate semantic column: {semantic}")
    return errors


def validate_rows(rows: list[dict[object, object]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        if None in raw:
            errors.append(f"row {index}: values extend beyond the declared seven columns")
        row = canonical_response_row(raw)
        for semantic in RESPONSE_KEYS:
            if not row[semantic]:
                errors.append(f"row {index}: missing {semantic}")

        issue_id = row["issue_id"]
        if issue_id:
            normalized_id = issue_id.casefold()
            if normalized_id in seen_ids:
                errors.append(f"row {index}: duplicate Issue ID {issue_id}")
            seen_ids.add(normalized_id)

        status = canonical_response_status(row["response_status"])
        if status is None:
            errors.append(
                f"row {index}: Response Status must contain exactly one supported response status; "
                f"found {row['response_status']!r}"
            )
        elif status == "new_issue" and not issue_id.startswith("NEW-"):
            errors.append(f"row {index}: new_issue requires an Issue ID beginning with NEW-")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response_matrix", type=Path)
    args = parser.parse_args()

    try:
        headers, rows = load_matrix(args.response_matrix)
    except (OSError, UnicodeError, csv.Error) as exc:
        print(f"Could not read Response Matrix: {exc}", file=sys.stderr)
        return 2

    errors = [*validate_headers(headers)]
    if not rows:
        errors.append("no response matrix rows found")
    errors.extend(validate_rows(rows))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(f"FAILED: {len(errors)} validation issue(s)", file=sys.stderr)
        return 1

    print(f"OK: {len(rows)} response matrix row(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
