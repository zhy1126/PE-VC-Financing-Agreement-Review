#!/usr/bin/env python3
"""Fail-closed importer for generated lawyer-confirmation DOCX files."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

from confirmation_word_common import (
    DocxInspectionError,
    canonical_json_sha256,
    inspect_docx,
    normalize_whitespace,
    safe_basename,
    sha256_file,
)
from lawyer_confirmation_schema import reduce_matter, validate_manifest


class ImportValidationError(Exception):
    """One or more stable import validation failures."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("lawyer confirmation import failed")
        self.errors = errors


def _error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _load_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImportValidationError([_error(code, path.name, type(exc).__name__)]) from exc


def _write_new_json(path: Path, value: Any) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def _normalize_field(field: str, value: str) -> Any:
    normalized = normalize_whitespace(value)
    if field == "batch_exception_confirmation_ids":
        return sorted({
            item.strip()
            for item in re.split(r"[,，、;；\s]+", normalized)
            if item.strip()
        })
    if field in {"include_in_major_issue_list", "include_in_counterparty_comment", "include_in_redline"}:
        lowered = normalized.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    if field in {"lawyer_decision", "batch_lawyer_decision", "drafting_action", "client_report_disposition"}:
        return normalized.lower()
    return normalized


def _valid_confirmation_date(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _base_scope_card_map(base: dict[str, Any]) -> dict[tuple[str, str], str]:
    result = {
        ("overall", "OVERALL"): "OVERALL",
        ("lawyer_new", "LAWYER-NEW"): "LAWYER-NEW",
    }
    for issue in base.get("issues", []):
        if not isinstance(issue, dict) or not isinstance(issue.get("issue_id"), str):
            continue
        issue_id = issue["issue_id"]
        result[("issue", issue_id)] = issue_id
        for subitem in issue.get("subitems", []):
            if isinstance(subitem, dict) and isinstance(subitem.get("confirmation_id"), str):
                result[("subitem", subitem["confirmation_id"])] = issue_id
    for batch in base.get("batch_decisions", []):
        if isinstance(batch, dict) and isinstance(batch.get("batch_id"), str):
            result[("batch", batch["batch_id"])] = batch["batch_id"]
    return result


def _validate_pack(base: Any, pack: Any, base_path: Path,
                   pack_path: Path) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    base_errors = validate_manifest(base)
    if base_errors:
        errors.append(_error("base_manifest_invalid", base_path.name, "base manifest failed strict schema validation"))
    if not isinstance(base, dict):
        return errors
    required = {
        "pack_manifest_version", "design_preset", "schema_version", "matter_id", "review_round",
        "confirmation_batch_id", "base_manifest_file_sha256", "generated_form_sha256",
        "generated_content_sha256", "immutable_visible_content_sha256", "sdt_manifest_sha256",
        "sdt_manifest", "header_template", "base_manifest_filename", "generated_form_filename",
    }
    if not isinstance(pack, dict):
        errors.append(_error("pack_manifest_invalid", pack_path.name, "pack manifest must be a JSON object"))
        return errors
    for field in sorted(required - set(pack)):
        errors.append(_error("pack_manifest_missing_field", f"{pack_path.name}.{field}", "required pack field is missing"))
    for field in sorted(set(pack) - required):
        errors.append(_error("pack_manifest_invalid", f"$.{field}", "unknown pack manifest field"))
    if pack.get("pack_manifest_version") != "1.0":
        errors.append(_error("unsupported_pack_manifest_version", "$.pack_manifest_version", "pack manifest version is not supported"))
    string_fields = required - {"review_round", "sdt_manifest"}
    for field in sorted(string_fields):
        if field in pack and not isinstance(pack[field], str):
            errors.append(_error("pack_manifest_invalid", f"$.{field}", "pack field has the wrong type"))
    if "review_round" in pack and (type(pack["review_round"]) is not int or pack["review_round"] < 1):
        errors.append(_error("pack_manifest_invalid", "$.review_round", "review round must be a positive integer"))
    for field in ("base_manifest_file_sha256", "generated_form_sha256", "generated_content_sha256", "immutable_visible_content_sha256", "sdt_manifest_sha256"):
        if isinstance(pack.get(field), str) and not re.fullmatch(r"[0-9a-f]{64}", pack[field]):
            errors.append(_error("pack_manifest_invalid", f"$.{field}", "pack digest must be lowercase SHA-256"))
    for field in ("base_manifest_filename", "generated_form_filename"):
        if isinstance(pack.get(field), str) and not safe_basename(pack[field]):
            errors.append(_error("pack_manifest_invalid", f"$.{field}", "pack filename is unsafe"))
    if pack.get("design_preset") != "contract_negotiation_brief":
        errors.append(_error("pack_design_preset_mismatch", "$.design_preset", "unexpected design preset"))
    for field in ("schema_version", "matter_id", "review_round", "confirmation_batch_id"):
        if pack.get(field) != base.get(field):
            errors.append(_error(f"{field}_mismatch", f"$.{field}", "pack and base manifest do not match"))
    if pack.get("base_manifest_file_sha256") != sha256_file(base_path):
        errors.append(_error("base_manifest_digest_mismatch", "$.base_manifest_file_sha256", "base manifest bytes do not match the generated pack"))
    manifest = pack.get("sdt_manifest")
    if isinstance(manifest, list):
        entry_fields = {"tag", "type", "allowed_values", "confirmation_id", "field", "card_id", "scope", "editable"}
        card_map = _base_scope_card_map(base)
        tags: list[str] = []
        valid_entries = True
        for index, item in enumerate(manifest):
            path = f"$.sdt_manifest[{index}]"
            if not isinstance(item, dict):
                errors.append(_error("sdt_manifest_invalid", path, "SDT manifest entry must be an object"))
                valid_entries = False
                continue
            if set(item) != entry_fields:
                errors.append(_error("sdt_manifest_invalid", path, "SDT manifest entry fields are invalid"))
                valid_entries = False
            for field in ("tag", "type", "confirmation_id", "field", "card_id", "scope"):
                if not isinstance(item.get(field), str) or not item.get(field):
                    errors.append(_error("sdt_manifest_invalid", f"{path}.{field}", "SDT manifest field must be a nonempty string"))
                    valid_entries = False
            if type(item.get("editable")) is not bool:
                errors.append(_error("sdt_manifest_invalid", f"{path}.editable", "editable must be boolean"))
                valid_entries = False
            allowed = item.get("allowed_values")
            if allowed is not None and (not isinstance(allowed, list) or any(not isinstance(value, str) for value in allowed)):
                errors.append(_error("sdt_manifest_invalid", f"{path}.allowed_values", "allowed values must be null or an array of strings"))
                valid_entries = False
            confirmation_id = item.get("confirmation_id")
            scope = item.get("scope")
            if scope not in {"issue", "subitem", "batch", "overall", "lawyer_new"}:
                errors.append(_error("sdt_manifest_invalid", f"{path}.scope", "SDT scope is not supported"))
                valid_entries = False
            if isinstance(confirmation_id, str) and isinstance(scope, str) and card_map.get((scope, confirmation_id)) != item.get("card_id"):
                errors.append(_error("sdt_manifest_invalid", f"{path}.card_id", "card ID does not match the base manifest"))
                valid_entries = False
            if isinstance(item.get("tag"), str):
                tags.append(item["tag"])
        if len(tags) != len(set(tags)):
            errors.append(_error("sdt_manifest_invalid", "$.sdt_manifest", "SDT manifest tags must be unique"))
            valid_entries = False
        if valid_entries and manifest != sorted(manifest, key=lambda item: item["tag"]):
            errors.append(_error("sdt_manifest_not_sorted", "$.sdt_manifest", "SDT manifest must be sorted by tag"))
        if valid_entries and pack.get("sdt_manifest_sha256") != canonical_json_sha256(manifest):
            errors.append(_error("sdt_manifest_digest_mismatch", "$.sdt_manifest_sha256", "SDT manifest digest is invalid"))
    else:
        errors.append(_error("sdt_manifest_invalid", "$.sdt_manifest", "SDT manifest must be an array"))
    generated_name = pack.get("generated_form_filename")
    if isinstance(generated_name, str) and safe_basename(generated_name):
        generated = pack_path.parent / generated_name
        if generated.exists() and pack.get("generated_form_sha256") != sha256_file(generated):
            errors.append(_error("generated_form_digest_mismatch", generated.name, "generated form no longer matches the pack audit digest"))
    return errors


def _validate_document(inspection: dict[str, Any], pack: dict[str, Any], base: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if inspection["tracked_changes_count"]:
        errors.append(_error("tracked_changes_present", "word/document.xml", "relevant tracked changes must be accepted or rejected before import"))
    if inspection["immutable_visible_content_sha256"] != pack.get("immutable_visible_content_sha256"):
        errors.append(_error("immutable_content_mismatch", "word/document.xml", "immutable visible content was changed"))
    expected_properties = {
        "PEVCGeneratedContentSHA256": pack.get("generated_content_sha256"),
        "PEVCBaseManifestSHA256": pack.get("base_manifest_file_sha256"),
        "PEVCImmutableVisibleSHA256": pack.get("immutable_visible_content_sha256"),
        "PEVCSDTManifestSHA256": pack.get("sdt_manifest_sha256"),
    }
    actual_properties = inspection.get("custom_properties", {})
    if not actual_properties:
        errors.append(_error("custom_properties_missing", "docProps/custom.xml", "provenance custom properties are missing"))
    elif not inspection.get("custom_properties_linked"):
        errors.append(_error("custom_property_package_invalid", "docProps/custom.xml", "custom properties are not linked by package relationships and content types"))
    elif any(actual_properties.get(name) != value for name, value in expected_properties.items()):
        errors.append(_error("custom_property_mismatch", "docProps/custom.xml", "provenance custom properties do not match the pack"))
    if inspection["matter_ids"] != [base["matter_id"]]:
        errors.append(_error("matter_id_mismatch", "word/document.xml", "visible matter ID does not match the base manifest"))
    if inspection["confirmation_batch_ids"] != [base["confirmation_batch_id"]]:
        errors.append(_error("confirmation_batch_id_mismatch", "word/document.xml", "visible confirmation batch does not match"))
    if inspection["review_rounds"] != [str(base["review_round"])]:
        errors.append(_error("review_round_mismatch", "word/document.xml", "visible review round does not match"))
    expected_list = pack.get("sdt_manifest") if isinstance(pack.get("sdt_manifest"), list) else []
    expected = {item.get("tag"): item for item in expected_list if isinstance(item, dict)}
    actual_tags = {item["tag"] for item in inspection["sdts"]}
    for tag in sorted(set(expected) - actual_tags):
        errors.append(_error("missing_sdt_tag", tag, "required editable control is missing"))
    for tag in sorted(actual_tags - set(expected)):
        errors.append(_error("unknown_sdt_tag", tag or "<blank>", "editable control is not in the generated whitelist"))
    for tag in inspection["duplicate_sdt_tags"]:
        errors.append(_error("duplicate_sdt_tag", tag, "editable control tag is duplicated"))
    for item in inspection["sdts"]:
        tag = item["tag"]
        if item["tag_component_count"] != 3:
            errors.append(_error("invalid_sdt_tag", tag or "<blank>", "SDT tag must contain batch/confirmation/field"))
        if item["batch_id"] != base["confirmation_batch_id"]:
            errors.append(_error("confirmation_batch_id_mismatch", tag, "SDT tag uses the wrong confirmation batch"))
        if item["visible_confirmation_id"] != item["confirmation_id"]:
            errors.append(_error("tag_visible_id_mismatch", tag, "tag and visible Confirmation ID do not match"))
        if item["merged_response_cell"]:
            errors.append(_error("merged_response_cell", tag, "response cells may not be merged"))
        metadata = expected.get(tag)
        if metadata:
            if metadata.get("field") != item["field"] or metadata.get("confirmation_id") != item["confirmation_id"]:
                errors.append(_error("sdt_manifest_entry_mismatch", tag, "SDT metadata does not match the tag"))
            if metadata.get("card_id") != item["card_issue_id"]:
                errors.append(_error("sdt_card_structure_mismatch", tag, "editable row is outside its explicit manifest card"))
            if metadata.get("type") != item["control_type"]:
                errors.append(_error("sdt_type_mismatch", tag, "content-control type does not match the generated whitelist"))
            allowed = metadata.get("allowed_values")
            normalized = _normalize_field(item["field"], item["value"])
            if item["value"] and isinstance(allowed, list):
                candidate = str(normalized) if item["field"] in {"confirmation_status", "overall_opinion_effect"} else str(normalized).lower()
                allowed_set = {str(value) for value in allowed} if item["field"] in {"confirmation_status", "overall_opinion_effect"} else {str(value).lower() for value in allowed}
                if candidate not in allowed_set:
                    errors.append(_error("invalid_editable_value", tag, "editable value is outside the allowed set"))
    return errors


def _response_projection(inspection: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    subitems: dict[str, dict[str, Any]] = {}
    issues: dict[str, dict[str, Any]] = {}
    overall: dict[str, Any] = {}
    batches: dict[str, dict[str, Any]] = {}
    lawyer_new_text = ""
    metadata_by_tag = {item["tag"]: item for item in pack["sdt_manifest"]}
    for item in sorted(inspection["sdts"], key=lambda value: value["tag"]):
        confirmation_id = item["confirmation_id"]
        field = item["field"]
        scope = metadata_by_tag[item["tag"]]["scope"]
        value = _normalize_field(field, item["value"])
        if scope == "batch":
            target = batches.setdefault(confirmation_id, {})
            mapped_field = {
                "batch_lawyer_decision": "lawyer_decision",
                "batch_exception_confirmation_ids": "exception_confirmation_ids",
                "batch_lawyer_comment": "lawyer_comment",
            }.get(field, field)
            target[mapped_field] = value
        elif scope == "overall":
            overall[field] = value
        elif scope == "lawyer_new":
            lawyer_new_text = value
        elif scope == "subitem":
            subitems.setdefault(confirmation_id, {})[field] = value or (None if field == "lawyer_decision" else "")
        elif scope == "issue":
            issues.setdefault(confirmation_id, {})[field] = value
    return {
        "subitems": {key: subitems[key] for key in sorted(subitems)},
        "issues": {key: issues[key] for key in sorted(issues)},
        "batches": {key: batches[key] for key in sorted(batches)},
        "overall": {key: overall[key] for key in sorted(overall)},
        "lawyer_new_area": lawyer_new_text,
    }


def _apply_response(base: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    imported = deepcopy(base)
    batch_by_id = {item["batch_id"]: item for item in imported["batch_decisions"]}
    for batch_item in imported["batch_decisions"]:
        batch_item["lawyer_decision"] = None
        batch_item["lawyer_comment"] = ""
    for batch_id, fields in response["batches"].items():
        batch_item = batch_by_id.get(batch_id)
        if batch_item is None:
            continue
        if fields.get("lawyer_decision"):
            batch_item["lawyer_decision"] = fields["lawyer_decision"]
        if "lawyer_comment" in fields:
            batch_item["lawyer_comment"] = fields["lawyer_comment"]
        if "exception_confirmation_ids" in fields:
            batch_item["exception_confirmation_ids"] = fields["exception_confirmation_ids"]
    for issue in imported["issues"]:
        issue_response = response["issues"].get(issue["issue_id"], {})
        if "drafting_action" in issue_response and issue_response["drafting_action"]:
            issue["drafting_action"] = issue_response["drafting_action"]
        for field in ("client_report_disposition", "include_in_major_issue_list", "include_in_counterparty_comment", "include_in_redline"):
            if field in issue_response and issue_response[field] != "":
                issue["projections"][field] = issue_response[field]
        for subitem in issue["subitems"]:
            fields = response["subitems"].get(subitem["confirmation_id"], {})
            if "lawyer_decision" in fields:
                subitem["lawyer_decision"] = fields["lawyer_decision"]
            if "lawyer_comment" in fields:
                subitem["lawyer_comment"] = fields["lawyer_comment"]
    individually_decided = {
        subitem["confirmation_id"]
        for issue in imported["issues"]
        for subitem in issue["subitems"]
        if subitem.get("lawyer_decision") is not None
        and response["subitems"].get(subitem["confirmation_id"], {}).get("lawyer_decision") is not None
    }
    for batch_item in imported["batch_decisions"]:
        covered = set(batch_item["confirmation_ids"])
        exceptions = set(batch_item["exception_confirmation_ids"])
        batch_item["exception_confirmation_ids"] = sorted(exceptions | (covered & individually_decided))
    return imported


def _lawyer_new_records(text: str) -> list[dict[str, Any]]:
    if not normalize_whitespace(text):
        return []
    return [{
        "issue_id": "LAWYER-NEW-001",
        "lawyer_new_placeholder": True,
        "lawyer_original_text": normalize_whitespace(text),
        "status": "reread_required",
    }]


def _existing_records(output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("import-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("record_type") == "lawyer_confirmation_import":
            value["_record_path"] = str(path)
            records.append(value)
    return records


def derive_active_import_head(output_dir: Path, confirmation_batch_id: str) -> dict[str, Any]:
    """Derive the unique current batch head from the append-only import store."""

    output_dir = Path(output_dir)
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("import-*.json")) if output_dir.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ImportValidationError([
                _error("import_store_invalid", path.name, "append-only import record is unreadable")
            ]) from exc
        if not isinstance(value, dict) or value.get("record_type") != "lawyer_confirmation_import":
            raise ImportValidationError([
                _error("import_store_invalid", path.name, "append-only import record has the wrong type")
            ])
        if value.get("confirmation_batch_id") == confirmation_batch_id:
            records.append(value)
    if not records:
        raise ImportValidationError([
            _error("active_response_head_missing", output_dir.name, "batch has no import records")
        ])
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        key = record.get("idempotency_key")
        if not isinstance(key, str) or not key or key in by_key:
            raise ImportValidationError([
                _error("import_store_invalid", output_dir.name, "batch import keys must be unique nonempty strings")
            ])
        by_key[key] = record
    superseded: set[str] = set()
    for record in records:
        prior = record.get("supersedes")
        if prior is not None:
            if not isinstance(prior, str) or prior not in by_key:
                raise ImportValidationError([
                    _error("import_store_invalid", output_dir.name, "supersedes must reference a batch import record")
                ])
            superseded.add(prior)
    heads = sorted(set(by_key) - superseded)
    if len(heads) != 1:
        code = "active_response_head_missing" if not heads else "multiple_active_response_heads"
        raise ImportValidationError([
            _error(code, output_dir.name, "batch must have exactly one current import head")
        ])
    return deepcopy(by_key[heads[0]])


def import_confirmation_pack(*, base_manifest_path: Path, pack_manifest_path: Path,
                             returned_docx_path: Path, output_dir: Path,
                             supersedes: str | None = None) -> dict[str, Any]:
    base_manifest_path = Path(base_manifest_path)
    pack_manifest_path = Path(pack_manifest_path)
    returned_docx_path = Path(returned_docx_path)
    output_dir = Path(output_dir)
    base = _load_json(base_manifest_path, "base_manifest_unreadable")
    pack = _load_json(pack_manifest_path, "pack_manifest_unreadable")
    errors = _validate_pack(base, pack, base_manifest_path, pack_manifest_path)
    if errors:
        raise ImportValidationError(errors)
    try:
        inspection = inspect_docx(returned_docx_path)
    except DocxInspectionError as exc:
        errors.append(_error(exc.code, returned_docx_path.name, exc.message))
        raise ImportValidationError(errors) from exc
    errors.extend(_validate_document(inspection, pack, base))
    if errors:
        raise ImportValidationError(errors)
    response = _response_projection(inspection, pack)
    imported_base = _apply_response(base, response)
    schema_errors = validate_manifest(imported_base)
    if schema_errors:
        errors.append(_error("response_schema_invalid", "$.response", "editable response violates the confirmation schema"))
        errors.extend(dict(item) for item in schema_errors)
        raise ImportValidationError(errors)
    reduction = reduce_matter(imported_base)
    if reduction["status"] == "blocked":
        unresolved = ", ".join(reduction["unresolved_required_ids"]) or "validation blocked"
        errors.append(_error("confirmation_incomplete", "$.response", f"required lawyer decisions are incomplete: {unresolved}"))
    signoff_name = normalize_whitespace(str(response["overall"].get("signoff_name", "")))
    signoff_date = normalize_whitespace(str(response["overall"].get("signoff_date", "")))
    confirmation_status = normalize_whitespace(str(response["overall"].get("confirmation_status", "")))
    if not signoff_name or confirmation_status != "confirm" or not _valid_confirmation_date(signoff_date):
        errors.append(
            _error(
                "confirmation_signoff_incomplete",
                "$.response.overall",
                "nonempty confirmer, exact status confirm, and a real ISO YYYY-MM-DD date are required",
            )
        )
    overall_opinion = normalize_whitespace(str(response["overall"].get("overall_opinion", "")))
    opinion_effect = normalize_whitespace(str(response["overall"].get("overall_opinion_effect", "")))
    if overall_opinion and not opinion_effect:
        errors.append(
            _error(
                "overall_opinion_effect_required",
                "$.response.overall.overall_opinion_effect",
                "a nonempty overall opinion requires a structured effect",
            )
        )
    elif not overall_opinion and opinion_effect == "decision_override":
        errors.append(
            _error(
                "overall_opinion_effect_invalid",
                "$.response.overall.overall_opinion_effect",
                "decision_override requires nonempty overall opinion text",
            )
        )
    elif overall_opinion and opinion_effect == "decision_override":
        errors.append(
            _error(
                "overall_opinion_requires_item_revision",
                "$.response.overall.overall_opinion_effect",
                "decision override must be applied to per-item fields and re-read before final confirmation",
            )
        )
    if errors:
        raise ImportValidationError(errors)

    base_digest = pack["base_manifest_file_sha256"]
    response_digest = canonical_json_sha256(response)
    idempotency_key = canonical_json_sha256({
        "confirmation_batch_id": base["confirmation_batch_id"],
        "base_manifest_file_sha256": base_digest,
        "normalized_response_sha256": response_digest,
    })
    returned_sha = sha256_file(returned_docx_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = _existing_records(output_dir)
    same_batch = [record for record in existing if record.get("confirmation_batch_id") == base["confirmation_batch_id"]]
    superseded_keys = {
        record.get("supersedes")
        for record in same_batch
        if isinstance(record.get("supersedes"), str)
    }
    active_heads = [record for record in same_batch if record.get("idempotency_key") not in superseded_keys]
    if len(active_heads) > 1:
        raise ImportValidationError([_error("multiple_active_response_heads", output_dir.name, "batch has multiple active response heads")])
    active_head = active_heads[0] if active_heads else None
    if same_batch and active_head is None:
        raise ImportValidationError([_error("active_response_head_missing", output_dir.name, "batch has no active response head")])
    current_head_key = active_head.get("idempotency_key") if active_head is not None else None
    for record in existing:
        if record.get("idempotency_key") == idempotency_key:
            return {
                "status": "imported",
                "idempotent_replay": True,
                "active": idempotency_key == current_head_key,
                "current_head": current_head_key,
                "idempotency_key": idempotency_key,
                "record_path": record["_record_path"],
                "returned_form_sha256": returned_sha,
                "generated_form_sha256": pack["generated_form_sha256"],
                "supersedes": record.get("supersedes"),
            }
    if active_head is not None and supersedes is None:
        raise ImportValidationError([_error("response_conflict_requires_supersedes", "--supersedes", "a different response already exists for this batch")])
    if active_head is not None and supersedes != active_head.get("idempotency_key"):
        raise ImportValidationError([_error("supersedes_not_active_head", "--supersedes", "supersedes must identify the current active response")])
    if active_head is None and supersedes is not None:
        raise ImportValidationError([_error("invalid_supersedes", "--supersedes", "there is no active response to supersede")])

    record_path = output_dir / f"import-{idempotency_key}.json"
    record = {
        "record_type": "lawyer_confirmation_import",
        "record_version": "1.0",
        "status": "imported",
        "schema_version": base["schema_version"],
        "matter_id": base["matter_id"],
        "review_round": base["review_round"],
        "confirmation_batch_id": base["confirmation_batch_id"],
        "base_manifest_file_sha256": base_digest,
        "generated_form_sha256": pack["generated_form_sha256"],
        "returned_form_sha256": returned_sha,
        "immutable_visible_content_sha256": inspection["immutable_visible_content_sha256"],
        "sdt_manifest_sha256": pack["sdt_manifest_sha256"],
        "normalized_response_sha256": response_digest,
        "idempotency_key": idempotency_key,
        "supersedes": supersedes,
        "response": response,
        "imported_base_manifest": imported_base,
        "lawyer_new_issues": _lawyer_new_records(response["lawyer_new_area"]),
    }
    _write_new_json(record_path, record)
    return {
        "status": "imported",
        "idempotent_replay": False,
        "active": True,
        "current_head": idempotency_key,
        "idempotency_key": idempotency_key,
        "record_path": str(record_path),
        "returned_form_sha256": returned_sha,
        "generated_form_sha256": pack["generated_form_sha256"],
        "supersedes": supersedes,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import a returned lawyer-confirmation DOCX.")
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--pack-manifest", required=True, type=Path)
    parser.add_argument("--returned-docx", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--supersedes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not safe_basename(args.returned_docx.name):
        print(json.dumps({"valid": False, "errors": [_error("unsafe_basename", args.returned_docx.name, "returned DOCX basename is unsafe")]}, ensure_ascii=False), file=sys.stderr)
        return 2
    try:
        result = import_confirmation_pack(
            base_manifest_path=args.base_manifest,
            pack_manifest_path=args.pack_manifest,
            returned_docx_path=args.returned_docx,
            output_dir=args.output_dir,
            supersedes=args.supersedes,
        )
    except ImportValidationError as exc:
        print(json.dumps({"valid": False, "errors": exc.errors}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ImportValidationError",
    "canonical_json_sha256",
    "derive_active_import_head",
    "import_confirmation_pack",
    "inspect_docx",
]
