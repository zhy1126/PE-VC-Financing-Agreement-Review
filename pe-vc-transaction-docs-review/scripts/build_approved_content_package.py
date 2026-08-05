#!/usr/bin/env python3
"""Build a deterministic, projection-safe approved-content package.

The base manifest remains the immutable source of displayed content.  The
import record supplies lawyer decisions and raw comments.  No substantive text
is generated here: direction-only revisions remain pending re-read.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from lawyer_confirmation_schema import (
    canonical_json_sha256,
    reduce_issue,
    reduce_matter,
    validate_manifest,
)
from import_lawyer_confirmation_pack import ImportValidationError, derive_active_import_head


PACKAGE_TYPE = "approved_content_package"
PACKAGE_VERSION = "1.0"
IMMUTABLE_ISSUE_FIELDS = (
    "issue_id", "file", "clause", "risk", "displayed_analysis", "sync_scope",
    "source_mappings", "proposed_drafting_action", "proposed_projections",
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"json_input_unreadable:{path.name}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validated_inputs(base_manifest: Any, import_record: Any, import_store: Path) -> tuple[dict, dict]:
    base_errors = validate_manifest(base_manifest)
    if base_errors:
        raise ValueError("base_manifest_invalid:" + ",".join(sorted({item.code for item in base_errors})))
    if not isinstance(import_record, dict):
        raise ValueError("import_record_required")
    if import_record.get("record_type") != "lawyer_confirmation_import" or import_record.get("status") != "imported":
        raise ValueError("immutable_import_record_required")
    try:
        active_head = derive_active_import_head(import_store, import_record.get("confirmation_batch_id"))
    except ImportValidationError as exc:
        raise ValueError("import_store_invalid:" + ",".join(sorted({item["code"] for item in exc.errors}))) from exc
    if import_record.get("idempotency_key") != active_head.get("idempotency_key"):
        raise ValueError("stale_import_record")
    if canonical_json_sha256(import_record) != canonical_json_sha256(active_head):
        raise ValueError("import_record_store_mismatch")
    imported = import_record.get("imported_base_manifest")
    imported_errors = validate_manifest(imported)
    if imported_errors:
        raise ValueError("imported_manifest_invalid:" + ",".join(sorted({item.code for item in imported_errors})))
    for field in ("schema_version", "matter_id", "review_round", "confirmation_batch_id"):
        if import_record.get(field) != base_manifest.get(field) or imported.get(field) != base_manifest.get(field):
            raise ValueError(f"import_identity_mismatch:{field}")
    base_by_id = {item["issue_id"]: item for item in base_manifest["issues"]}
    imported_by_id = {item["issue_id"]: item for item in imported["issues"]}
    if set(base_by_id) != set(imported_by_id):
        raise ValueError("import_issue_set_mismatch")
    for issue_id in sorted(base_by_id):
        expected = {field: base_by_id[issue_id].get(field) for field in IMMUTABLE_ISSUE_FIELDS}
        actual = {field: imported_by_id[issue_id].get(field) for field in IMMUTABLE_ISSUE_FIELDS}
        if canonical_json_sha256(expected) != canonical_json_sha256(actual):
            raise ValueError(f"immutable_issue_content_mismatch:{issue_id}")
        expected_subitems = {
            item["confirmation_id"]: {
                key: item.get(key)
                for key in ("confirmation_id", "item_type", "required_for_final", "completion_impact")
            }
            for item in base_by_id[issue_id]["subitems"]
        }
        actual_subitems = {
            item["confirmation_id"]: {
                key: item.get(key)
                for key in ("confirmation_id", "item_type", "required_for_final", "completion_impact")
            }
            for item in imported_by_id[issue_id]["subitems"]
        }
        if canonical_json_sha256(expected_subitems) != canonical_json_sha256(actual_subitems):
            raise ValueError(f"immutable_subitem_content_mismatch:{issue_id}")
    return deepcopy(base_manifest), deepcopy(imported)


def _decision_records(issue: dict) -> list[dict[str, Any]]:
    records = []
    for item in sorted(issue["subitems"], key=lambda value: value["confirmation_id"]):
        records.append({
            "confirmation_id": item["confirmation_id"],
            "item_type": item["item_type"],
            "required_for_final": item["required_for_final"],
            "completion_impact": item["completion_impact"],
            "lawyer_decision": item.get("lawyer_decision"),
            "lawyer_original_text": item.get("lawyer_comment", ""),
            "replacement_text": item.get("replacement_text"),
            "replacement_complete": item.get("replacement_complete") is True,
            "reread_confirmed": item.get("reread_confirmed") is True,
            "reread_approved_analysis": item.get("reread_approved_analysis"),
            "reread_approved_text": item.get("reread_approved_text"),
        })
    return records


def _approved_text(issue: dict, records: list[dict[str, Any]], reread_required: bool) -> tuple[str | None, str | None]:
    active = [item for item in records if item["required_for_final"] and item["completion_impact"] != "informational"]
    decisions = {item["lawyer_decision"] for item in active}
    if reread_required or decisions & {None, "reject", "defer_client", "defer_research", "not_applicable"}:
        return None, None
    if "revise" in decisions:
        approved_analyses: list[str] = []
        approved_texts: list[str] = []
        for item in active:
            if item["lawyer_decision"] != "revise":
                continue
            if item["replacement_complete"]:
                analysis = item.get("replacement_text")
                text = item.get("replacement_text")
            elif item["reread_confirmed"]:
                analysis = item.get("reread_approved_analysis")
                text = item.get("reread_approved_text")
            else:
                return None, None
            if not isinstance(analysis, str) or not analysis.strip():
                return None, None
            if not isinstance(text, str) or not text.strip():
                return None, None
            normalized_analysis = analysis.strip()
            normalized_text = text.strip()
            if normalized_analysis not in approved_analyses:
                approved_analyses.append(normalized_analysis)
            if normalized_text not in approved_texts:
                approved_texts.append(normalized_text)
        if not approved_analyses or not approved_texts:
            return None, None
        return "\n".join(approved_analyses), "\n".join(approved_texts)
    if decisions == {"agree"} or decisions.issubset({"agree"}):
        displayed = issue["displayed_analysis"]
        return displayed, displayed
    return None, None


def _pending_kind(records: list[dict[str, Any]]) -> str | None:
    decisions = {item["lawyer_decision"] for item in records if item["required_for_final"]}
    if "defer_client" in decisions:
        return "client"
    if "defer_research" in decisions:
        return "legal"
    return None


def _pending_reason(records: list[dict[str, Any]], kind: str | None) -> str | None:
    if kind is None:
        return None
    expected = "defer_client" if kind == "client" else "defer_research"
    reasons = [
        item["lawyer_original_text"].strip()
        for item in records
        if item["lawyer_decision"] == expected and item["lawyer_original_text"].strip()
    ]
    return "；".join(dict.fromkeys(reasons)) or ("待客户确认" if kind == "client" else "待进一步法律核验")


def _project(issue: dict, approved: bool) -> dict[str, bool]:
    source = issue["projections"]
    disposition = source["client_report_disposition"]
    return {
        "client_report": approved and disposition == "include",
        "major_issue_list": approved and source["include_in_major_issue_list"] is True,
        "counterparty_comment": approved and source["include_in_counterparty_comment"] is True,
        "redline": approved and source["include_in_redline"] is True,
    }


def package_content_sha256(package: dict[str, Any]) -> str:
    payload = deepcopy(package)
    payload.pop("approved_content_sha256", None)
    return canonical_json_sha256(payload)


def build_approved_content_package(base_manifest: Any, import_record: Any, *,
                                   import_store: Path) -> dict[str, Any]:
    base, imported = _validated_inputs(base_manifest, import_record, Path(import_store))
    reduction = reduce_matter(imported)
    result_by_id = {item["issue_id"]: item for item in reduction["issue_results"]}
    issues: list[dict[str, Any]] = []
    approved_ids: list[str] = []
    reread_issue_ids: list[str] = []
    pending_client_ids: list[str] = []
    pending_legal_ids: list[str] = []
    excluded_reasons: dict[str, list[str]] = {}
    for issue in sorted(imported["issues"], key=lambda value: value["issue_id"]):
        records = _decision_records(issue)
        issue_reduction = result_by_id[issue["issue_id"]]
        reread_required = bool(issue_reduction["reread_required"])
        analysis, text = _approved_text(issue, records, reread_required)
        pending_kind = _pending_kind(records)
        finalized_decisions = {
            item["lawyer_decision"] for item in records
            if item["required_for_final"] and item["completion_impact"] != "informational"
        }
        approved = (
            issue_reduction["status"] == "passed"
            and analysis is not None
            and bool(finalized_decisions & {"agree", "revise"})
        )
        reasons: list[str] = []
        if reread_required:
            reasons.append("reread_required")
            reread_issue_ids.append(issue["issue_id"])
        if pending_kind:
            reasons.append(f"{pending_kind}_pending")
            (pending_client_ids if pending_kind == "client" else pending_legal_ids).append(issue["issue_id"])
        if "reject" in finalized_decisions:
            reasons.append("lawyer_rejected_modification")
        if "not_applicable" in finalized_decisions:
            reasons.append("not_applicable")
        if not approved and not reasons:
            reasons.append("no_approved_substantive_content")
        if reasons:
            excluded_reasons[issue["issue_id"]] = sorted(set(reasons))
        record = {
            "issue_id": issue["issue_id"],
            "file": issue["file"],
            "clause": issue["clause"],
            "risk": issue["risk"],
            "displayed_analysis": issue["displayed_analysis"],
            "source_mappings": deepcopy(issue["source_mappings"]),
            "sync_scope": deepcopy(issue["sync_scope"]),
            "proposed_drafting_action": issue["proposed_drafting_action"],
            "lawyer_decisions": records,
            "lawyer_original_text": {
                item["confirmation_id"]: item["lawyer_original_text"] for item in records
            },
            "approved_analysis": analysis,
            "approved_text": text,
            "drafting_action": issue["drafting_action"],
            "client_report_disposition": issue["projections"]["client_report_disposition"],
            "projections": _project(issue, approved),
            "approved": approved,
            "decision_status": issue_reduction["status"],
            "pending_kind": pending_kind,
            "pending_reason": _pending_reason(records, pending_kind),
            "reread_required": reread_required,
            "reread_required_confirmation_ids": issue_reduction["reread_required_ids"],
            "supersedes": import_record.get("supersedes"),
            "reopened_reason": "direction_only_revision" if reread_required else None,
        }
        issues.append(record)
        if approved:
            approved_ids.append(issue["issue_id"])

    lawyer_new = []
    for item in sorted(import_record.get("lawyer_new_issues", []), key=lambda value: str(value.get("issue_id", ""))):
        issue_id = item.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id.startswith("LAWYER-NEW-"):
            raise ValueError("invalid_lawyer_new_placeholder")
        lawyer_new.append({
            "issue_id": issue_id,
            "lawyer_original_text": item.get("lawyer_original_text", ""),
            "status": "reread_required",
            "approved": False,
            "reread_required": True,
            "required_next_steps": ["fact_analysis", "legal_or_transaction_analysis", "drafting_sync_analysis", "lawyer_reread"],
        })
        excluded_reasons[issue_id] = ["lawyer_new_reread_required"]
        reread_issue_ids.append(issue_id)

    matter_status = "blocked" if lawyer_new else reduction["status"]
    package = {
        "package_type": PACKAGE_TYPE,
        "package_version": PACKAGE_VERSION,
        "schema_version": base["schema_version"],
        "matter_id": base["matter_id"],
        "review_round": base["review_round"],
        "confirmation_batch_id": base["confirmation_batch_id"],
        "source_files": deepcopy(sorted(base["source_files"], key=lambda value: value["source_file_id"])),
        "source_manifest_sha256": canonical_json_sha256(base),
        "import_idempotency_key": import_record.get("idempotency_key"),
        "supersedes": import_record.get("supersedes"),
        "matter_status": matter_status,
        "matter_reduction": {
            "unresolved_required_ids": reduction["unresolved_required_ids"],
            "counts": reduction["counts"],
        },
        "issues": issues,
        "approved_issue_ids": sorted(approved_ids),
        "client_pending_issue_ids": sorted(pending_client_ids),
        "legal_pending_issue_ids": sorted(pending_legal_ids),
        "reread_required_issue_ids": sorted(set(reread_issue_ids)),
        "lawyer_new_placeholders": lawyer_new,
        "excluded_issue_reasons": {key: excluded_reasons[key] for key in sorted(excluded_reasons)},
    }
    package["approved_content_sha256"] = package_content_sha256(package)
    return package


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build approved content from one active lawyer-confirmation import.")
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--import-response", "--import-record", dest="import_response", required=True, type=Path)
    parser.add_argument("--import-store", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        package = build_approved_content_package(
            _load_json(args.base_manifest), _load_json(args.import_response),
            import_store=args.import_store,
        )
        _write_json(args.output, package)
    except ValueError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(json.dumps({"status": "built", "output": args.output.name, "sha256": package["approved_content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
