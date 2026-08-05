#!/usr/bin/env python3
"""Create four independent, deterministic audience projections."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from lawyer_confirmation_schema import canonical_json_sha256
from build_approved_content_package import package_content_sha256


PROJECTIONS = ("client_report", "major_issue_list", "counterparty_comment", "redline")


def _external_item(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_id": issue["issue_id"],
        "file": Path(str(issue["file"])).name,
        "clause": issue["clause"],
        "risk": issue["risk"],
        "approved_analysis": issue["approved_analysis"],
        "approved_text": issue["approved_text"],
        "drafting_action": issue["drafting_action"],
        "sync_scope": deepcopy(issue["sync_scope"]),
        "pending_kind": issue["pending_kind"],
        "pending_reason": issue["pending_reason"],
        "approved": issue["approved"],
    }


def report_model_content_sha256(model: dict[str, Any]) -> str:
    payload = deepcopy(model)
    payload.pop("report_model_sha256", None)
    return canonical_json_sha256(payload)


def _validate_package(package: Any) -> dict[str, Any]:
    if not isinstance(package, dict) or package.get("package_type") != "approved_content_package":
        raise ValueError("approved_content_package_required")
    if package.get("approved_content_sha256") != package_content_sha256(package):
        raise ValueError("approved_content_hash_mismatch")
    if package.get("matter_status") not in {"blocked", "passed_with_limitations", "passed"}:
        raise ValueError("invalid_matter_status")
    if not isinstance(package.get("issues"), list):
        raise ValueError("approved_issue_array_required")
    issue_ids: set[str] = set()
    required_issue_fields = {
        "issue_id", "file", "clause", "risk", "approved_analysis", "approved_text",
        "drafting_action", "sync_scope", "pending_kind", "pending_reason", "approved",
        "client_report_disposition", "projections",
    }
    for issue in package["issues"]:
        if not isinstance(issue, dict) or not required_issue_fields.issubset(issue):
            raise ValueError("approved_issue_shape_invalid")
        issue_id = issue.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id or issue_id in issue_ids:
            raise ValueError("approved_issue_id_invalid")
        issue_ids.add(issue_id)
        if type(issue.get("approved")) is not bool:
            raise ValueError("approved_issue_flag_invalid")
        projections = issue.get("projections")
        if not isinstance(projections, dict) or set(projections) != set(PROJECTIONS):
            raise ValueError("approved_issue_projection_shape_invalid")
        if any(type(projections[name]) is not bool for name in PROJECTIONS):
            raise ValueError("approved_issue_projection_flag_invalid")
        selected = any(projections.values())
        if selected and issue.get("approved") is not True:
            raise ValueError(f"unapproved_projection_reference:{issue_id}")
        if issue.get("approved") is True and (
            not isinstance(issue.get("approved_analysis"), str)
            or not issue["approved_analysis"].strip()
            or not isinstance(issue.get("approved_text"), str)
            or not issue["approved_text"].strip()
        ):
            raise ValueError("approved_issue_content_missing")
        pending_kind = issue.get("pending_kind")
        if pending_kind not in {None, "client", "legal"}:
            raise ValueError("approved_issue_pending_kind_invalid")
        if pending_kind is not None and (issue.get("approved") is not False or selected):
            raise ValueError("pending_issue_cannot_be_approved")
    return deepcopy(package)


def _exclusion_reason(issue: dict[str, Any], projection_name: str) -> str:
    if issue.get("reread_required"):
        return "reread_required"
    if issue.get("pending_kind"):
        return f"{issue['pending_kind']}_pending"
    if projection_name == "client_report" and issue.get("client_report_disposition") == "internal_only":
        return "internal_only"
    if not issue.get("approved"):
        return "unapproved_content"
    return "projection_disabled"


def _build_projection(issues: list[dict[str, Any]], name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    included: list[dict[str, Any]] = []
    excluded: dict[str, str] = {}
    for issue in issues:
        issue_id = issue["issue_id"]
        selected = issue.get("projections", {}).get(name) is True
        if selected and not issue.get("approved"):
            raise ValueError(f"unapproved_projection_reference:{name}:{issue_id}")
        if selected:
            included.append(_external_item(issue))
        else:
            excluded[issue_id] = _exclusion_reason(issue, name)
    included.sort(key=lambda value: value["issue_id"])
    projection = {
        "included_ids": [item["issue_id"] for item in included],
        "items": included,
    }
    if name == "client_report":
        client_pending = [_external_item(item) for item in issues if item.get("pending_kind") == "client"]
        legal_pending = [_external_item(item) for item in issues if item.get("pending_kind") == "legal"]
        projection.update({
            "client_pending_ids": sorted(item["issue_id"] for item in client_pending),
            "client_pending_items": sorted(client_pending, key=lambda value: value["issue_id"]),
            "legal_pending_ids": sorted(item["issue_id"] for item in legal_pending),
            "legal_pending_items": sorted(legal_pending, key=lambda value: value["issue_id"]),
        })
    allowed_pending_ids = []
    if name == "client_report":
        allowed_pending_ids = sorted(
            set(projection["client_pending_ids"]) | set(projection["legal_pending_ids"])
        )
    anti_leak = {
        "conclusion_excluded_ids": sorted(excluded),
        "allowed_pending_ids": allowed_pending_ids,
        "reasons": {key: excluded[key] for key in sorted(excluded)},
    }
    return projection, anti_leak


def _validate_anti_leak(model: dict[str, Any], package: dict[str, Any]) -> None:
    known = {item["issue_id"] for item in package["issues"]}
    lawyer_new = {item["issue_id"] for item in package.get("lawyer_new_placeholders", [])}
    for name in PROJECTIONS:
        projection = model["projections"][name]
        included = set(projection["included_ids"])
        excluded = set(model["anti_leak"][name]["conclusion_excluded_ids"])
        allowed_pending = set(model["anti_leak"][name]["allowed_pending_ids"])
        if included & excluded:
            raise ValueError(f"anti_leak_overlap:{name}")
        if not included.issubset(known) or included & lawyer_new:
            raise ValueError(f"unauthorized_projection_id:{name}")
        item_ids = {item["issue_id"] for item in projection["items"]}
        if item_ids != included:
            raise ValueError(f"projection_item_id_mismatch:{name}")
        if any(not item.get("approved") for item in projection["items"]):
            raise ValueError(f"unapproved_projection_reference:{name}")
        if name == "client_report":
            pending = set(projection["client_pending_ids"]) | set(projection["legal_pending_ids"])
            if pending != allowed_pending or not pending.issubset(excluded):
                raise ValueError("client_pending_anti_leak_mismatch")
        elif allowed_pending:
            raise ValueError(f"unexpected_allowed_pending_ids:{name}")


def build_report_model(approved_package: Any) -> dict[str, Any]:
    package = _validate_package(approved_package)
    issues = sorted(package["issues"], key=lambda value: value["issue_id"])
    projections: dict[str, Any] = {}
    anti_leak: dict[str, Any] = {}
    lawyer_new_ids = sorted(item["issue_id"] for item in package.get("lawyer_new_placeholders", []))
    for name in PROJECTIONS:
        projections[name], anti_leak[name] = _build_projection(issues, name)
        for issue_id in lawyer_new_ids:
            anti_leak[name]["reasons"][issue_id] = "lawyer_new_reread_required"
        anti_leak[name]["conclusion_excluded_ids"] = sorted(anti_leak[name]["reasons"])

    status = package["matter_status"]
    if status == "passed":
        visible_status = "最终版"
    elif status == "passed_with_limitations":
        visible_status = "最终版（附保留事项）"
    elif package.get("reread_required_issue_ids"):
        visible_status = "草稿——律师确认未完成"
    else:
        visible_status = "暂不能形成最终版"
    client = projections["client_report"]
    included = client["items"]
    model = {
        "model_type": "legal_review_report_model",
        "model_version": "1.0",
        "design_preset": "standard_business_brief",
        "approved_content_sha256": package["approved_content_sha256"],
        "matter_id": package["matter_id"],
        "review_round": package["review_round"],
        "confirmation_batch_id": package["confirmation_batch_id"],
        "matter_status": status,
        "visible_status": visible_status,
        "position": "以事项委托说明所载立场为准",
        "scope": sorted({Path(str(item["path"])).name for item in package.get("source_files", [])}),
        "version_basis": f"第 {package['review_round']} 轮；确认批次 {package['confirmation_batch_id']}",
        "limitations": [
            "本报告仅基于已列明文件及律师确认结果，不替代未提供材料或未完成专项核验。",
        ] + (["存在已显著披露的局部待决事项；其余结论不受影响。"] if status == "passed_with_limitations" else []),
        "unreviewed_materials": ["未列入本报告范围的底层材料、历史决议及外部登记资料"],
        "projections": projections,
        "anti_leak": anti_leak,
        "required_section_ids": {
            "client_report": deepcopy(client["included_ids"]),
            "major_issue_list": deepcopy(projections["major_issue_list"]["included_ids"]),
            "confirmed_facts": [item["issue_id"] for item in included],
            "approved_analysis": [item["issue_id"] for item in included if item.get("approved_analysis")],
            "modifications_sync": [
                item["issue_id"] for item in included
                if item.get("drafting_action") in {"modify", "delete_clause"}
            ],
            "client_pending": deepcopy(client["client_pending_ids"]),
            "legal_pending": deepcopy(client["legal_pending_ids"]),
        },
    }
    _validate_anti_leak(model, package)
    model["report_model_sha256"] = report_model_content_sha256(model)
    return model


def validate_report_model_binding(report_model: Any, approved_package: Any) -> dict[str, Any]:
    """Rebuild the only authorized model and require canonical exact equality."""

    expected = build_report_model(approved_package)
    if not isinstance(report_model, dict) or canonical_json_sha256(report_model) != canonical_json_sha256(expected):
        raise ValueError("report_model_approved_content_mismatch")
    return expected


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"approved_content_unreadable:{path.name}") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build deterministic four-audience report model.")
    parser.add_argument("--approved-content", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        model = build_report_model(_load(args.approved_content))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except ValueError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1
    print(json.dumps({"status": "built", "output": args.output.name, "sha256": model["report_model_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
