#!/usr/bin/env python3
"""Validate a lawyer-confirmation manifest from the command line."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

from lawyer_confirmation_schema import ValidationError, reduce_matter, validate_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a lawyer-confirmation JSON manifest.")
    parser.add_argument("--input", required=True, type=Path, help="confirmation manifest JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return
    print(f"valid: {str(payload['valid']).lower()}")
    print(f"matter_status: {payload['matter_status']}")
    for error in payload["errors"]:
        print(f"{error['code']} {error['path']}: {error['message']}")


def _reject_non_finite_constant(_value: str) -> None:
    raise ValueError("non-finite JSON numeric literal")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _emit_limit_failure(
    input_path: Path,
    as_json: bool,
    *,
    code: str = "input_too_deep",
    message: str = "JSON input exceeds the supported nesting limit",
) -> int:
    error = ValidationError(
        code,
        input_path.name,
        message,
    )
    _emit(
        {
            "valid": False,
            "errors": [error],
            "matter_status": "unreadable",
            "counts": {},
        },
        as_json,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with args.input.open("r", encoding="utf-8") as handle:
            value = json.load(
                handle,
                parse_constant=_reject_non_finite_constant,
                parse_float=_parse_finite_float,
            )
    except RecursionError:
        return _emit_limit_failure(args.input, args.json)
    except (json.JSONDecodeError, ValueError) as exc:
        error = ValidationError(
            "input_invalid_json",
            args.input.name,
            f"invalid JSON input ({type(exc).__name__})",
        )
        _emit(
            {
                "valid": False,
                "errors": [error],
                "matter_status": "unreadable",
                "counts": {},
            },
            args.json,
        )
        return 2
    except (OSError, UnicodeError) as exc:
        error = ValidationError(
            "input_unreadable",
            args.input.name,
            f"could not read JSON input ({type(exc).__name__})",
        )
        _emit(
            {
                "valid": False,
                "errors": [error],
                "matter_status": "unreadable",
                "counts": {},
            },
            args.json,
        )
        return 2

    try:
        errors = validate_manifest(value)
        limit_error = next(
            (
                error
                for error in errors
                if error.code in {"input_too_deep", "input_too_large"}
            ),
            None,
        )
        if limit_error is not None:
            return _emit_limit_failure(
                args.input,
                args.json,
                code=limit_error.code,
                message=limit_error.message,
            )
        reduction = reduce_matter(value)
    except RecursionError:
        return _emit_limit_failure(args.input, args.json)
    payload = {
        "valid": not errors,
        "errors": errors,
        "matter_status": reduction["status"],
        "counts": reduction["counts"],
    }
    _emit(payload, args.json)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
