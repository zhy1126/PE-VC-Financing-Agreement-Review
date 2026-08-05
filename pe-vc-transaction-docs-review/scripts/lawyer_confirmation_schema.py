"""Fail-closed validation and deterministic reduction for lawyer confirmations.

This module deliberately uses only the Python standard library.  Validation
errors are stable, machine-readable mappings so callers can render them in a
CLI, Word repair list, or a later import record without parsing prose.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any
import unicodedata


LAWYER_DECISIONS = {
    "agree",
    "revise",
    "reject",
    "defer_client",
    "defer_research",
    "not_applicable",
}
DRAFTING_ACTIONS = {
    "keep_current",
    "modify",
    "delete_clause",
    "no_contract_change",
    "not_applicable",
}
ITEM_TYPES = {"fact", "legal", "commercial", "drafting"}
COMPLETION_IMPACTS = {"foundational", "local", "informational"}
CLIENT_DISPOSITIONS = {"include", "client_pending", "legal_pending", "internal_only"}
PROJECTION_FIELDS = {
    "client_report_disposition",
    "include_in_major_issue_list",
    "include_in_counterparty_comment",
    "include_in_redline",
}
ISSUE_FIELDS = {
    "issue_id",
    "file",
    "clause",
    "risk",
    "displayed_analysis",
    "sync_scope",
    "source_mappings",
    "proposed_drafting_action",
    "drafting_action",
    "proposed_projections",
    "projections",
    "subitems",
    "lawyer_new_placeholder",
}
SUBITEM_FIELDS = {
    "confirmation_id",
    "item_type",
    "lawyer_decision",
    "lawyer_comment",
    "required_for_final",
    "completion_impact",
    "replacement_text",
    "replacement_complete",
    "reread_confirmed",
    "reread_approved_analysis",
    "reread_approved_text",
}
MANIFEST_FIELDS = {
    "schema_version",
    "matter_id",
    "review_round",
    "generated_at",
    "language",
    "confirmation_batch_id",
    "source_files",
    "source_file_collection_sha256",
    "issue_log_sha256",
    "issue_snapshot_sha256",
    "base_manifest_sha256",
    "generated_form_sha256",
    "immutable_visible_content_sha256",
    "sdt_manifest_sha256",
    "issues",
    "batch_decisions",
}
BATCH_FIELDS = {
    "batch_id",
    "category",
    "confirmation_ids",
    "lawyer_decision",
    "lawyer_comment",
    "exception_confirmation_ids",
}
SOURCE_FILE_FIELDS = {"source_file_id", "path", "sha256"}
SOURCE_MAPPING_FIELDS = {
    "confirmation_id",
    "source_file_id",
    "clause_locator",
    "excerpt_sha256",
    "proposed_content_sha256",
}
BATCH_CATEGORIES = {"regular_substantive", "text_cleanup"}
LANGUAGES = {"zh-CN", "en"}
RESERVED_ROUTING_IDS = {"OVERALL", "LAWYER-NEW"}
REQUIRED_ISSUE_FIELDS = ISSUE_FIELDS - {"lawyer_new_placeholder"}
REQUIRED_SUBITEM_FIELDS = {
    "confirmation_id",
    "item_type",
    "lawyer_decision",
    "lawyer_comment",
    "required_for_final",
    "completion_impact",
}
REQUIRED_MANIFEST_FIELDS = MANIFEST_FIELDS
REQUIRED_BATCH_FIELDS = BATCH_FIELDS - {"lawyer_decision"}
LAWYER_NEW_ID = re.compile(r"^LAWYER-NEW-[0-9]{3}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_DEPTH = 256
MAX_JSON_NODES = 100_000


class ValidationError(dict[str, str]):
    """Stable validation record with both mapping and attribute access."""

    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(code=code, path=path, message=message)

    @property
    def code(self) -> str:
        return self["code"]

    @property
    def path(self) -> str:
        return self["path"]

    @property
    def message(self) -> str:
        return self["message"]


def _error(code: str, path: str, message: str) -> ValidationError:
    return ValidationError(code, path, message)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_identifier(value: Any) -> bool:
    return (
        _is_nonempty_string(value)
        and "/" not in value
        and "\\" not in value
        and not any(character.isspace() or unicodedata.category(character) == "Cc" for character in value)
    )


def _identifier_error(value: Any, path: str) -> list[ValidationError]:
    if _is_nonempty_string(value) and not _is_valid_identifier(value):
        return [_error("invalid_identifier", path, "identifier contains a forbidden delimiter, whitespace, or control character")]
    return []


def _enum_member(value: Any, allowed: set[str]) -> bool:
    return isinstance(value, str) and value in allowed


def _validate_sha256(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        return [_error("invalid_sha256", path, "value must be a lowercase SHA-256 digest")]
    return []


def _non_finite_errors(value: Any, path: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    stack: list[tuple[Any, str, int]] = [(value, path, 0)]
    visited_nodes = 0
    while stack:
        current, current_path, depth = stack.pop()
        visited_nodes += 1
        if visited_nodes > MAX_JSON_NODES:
            errors.append(
                _error(
                    "input_too_large",
                    path,
                    f"input exceeds the {MAX_JSON_NODES}-node validation limit",
                )
            )
            break
        if depth > MAX_JSON_DEPTH:
            errors.append(
                _error(
                    "input_too_deep",
                    path,
                    f"input exceeds the {MAX_JSON_DEPTH}-level nesting limit",
                )
            )
            break
        if isinstance(current, float) and not math.isfinite(current):
            errors.append(
                _error("non_finite_number", current_path, "JSON numbers must be finite")
            )
        elif isinstance(current, Mapping):
            for key in reversed(sorted(current, key=str)):
                stack.append((current[key], f"{current_path}.{key}", depth + 1))
        elif isinstance(current, (list, tuple)):
            for index in range(len(current) - 1, -1, -1):
                stack.append((current[index], f"{current_path}[{index}]", depth + 1))
    return errors


def _dedupe_errors(errors: list[ValidationError]) -> list[ValidationError]:
    result: list[ValidationError] = []
    seen: set[tuple[str, str, str]] = set()
    for error in errors:
        identity = (error.code, error.path, error.message)
        if identity not in seen:
            seen.add(identity)
            result.append(error)
    return result


def _is_iso8601_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return "T" in value and parsed.tzinfo is not None


def _check_fields(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    path: str,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for field in sorted(set(value) - allowed):
        errors.append(_error("unknown_field", f"{path}.{field}", "field is not allowed"))
    for field in sorted(required - set(value)):
        errors.append(_error("missing_field", f"{path}.{field}", "required field is missing"))
    return errors


def _validate_projection(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, Mapping):
        return [_error("expected_projections_object", path, "projections must be an object")]
    errors = _check_fields(value, allowed=PROJECTION_FIELDS, required=PROJECTION_FIELDS, path=path)
    disposition = value.get("client_report_disposition")
    if "client_report_disposition" in value and not _enum_member(disposition, CLIENT_DISPOSITIONS):
        errors.append(
            _error(
                "invalid_client_report_disposition",
                f"{path}.client_report_disposition",
                "client report disposition is not supported",
            )
        )
    for field in sorted(PROJECTION_FIELDS - {"client_report_disposition"}):
        if field in value and type(value[field]) is not bool:
            errors.append(_error("expected_boolean", f"{path}.{field}", "projection flag must be boolean"))
    return errors


def _validate_subitem(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, Mapping):
        return [_error("expected_subitem_object", path, "subitem must be an object")]
    errors = _check_fields(value, allowed=SUBITEM_FIELDS, required=REQUIRED_SUBITEM_FIELDS, path=path)

    if "confirmation_id" in value and not _is_nonempty_string(value["confirmation_id"]):
        errors.append(_error("invalid_confirmation_id", f"{path}.confirmation_id", "confirmation ID must be non-empty"))
    elif value.get("confirmation_id") in RESERVED_ROUTING_IDS:
        errors.append(_error("reserved_identifier", f"{path}.confirmation_id", "identifier is reserved for confirmation routing"))
    if "confirmation_id" in value:
        errors.extend(_identifier_error(value["confirmation_id"], f"{path}.confirmation_id"))
    if "item_type" in value and not _enum_member(value["item_type"], ITEM_TYPES):
        errors.append(_error("invalid_item_type", f"{path}.item_type", "item type is not supported"))
    if "lawyer_decision" in value:
        decision = value["lawyer_decision"]
        if decision is not None and not _enum_member(decision, LAWYER_DECISIONS):
            errors.append(
                _error("invalid_lawyer_decision", f"{path}.lawyer_decision", "lawyer decision is not supported")
            )
    if "lawyer_comment" in value and not isinstance(value["lawyer_comment"], str):
        errors.append(_error("expected_string", f"{path}.lawyer_comment", "lawyer comment must be a string"))
    if "required_for_final" in value and type(value["required_for_final"]) is not bool:
        errors.append(_error("expected_boolean", f"{path}.required_for_final", "required flag must be boolean"))
    if "completion_impact" in value and not _enum_member(value["completion_impact"], COMPLETION_IMPACTS):
        errors.append(
            _error("invalid_completion_impact", f"{path}.completion_impact", "completion impact is not supported")
        )
    if value.get("completion_impact") == "informational" and value.get("required_for_final") is True:
        errors.append(
            _error(
                "informational_cannot_be_required",
                f"{path}.required_for_final",
                "informational items cannot be required for final output",
            )
        )
    for field in ("replacement_complete", "reread_confirmed"):
        if field in value and type(value[field]) is not bool:
            errors.append(_error("expected_boolean", f"{path}.{field}", f"{field} must be boolean"))
    if "replacement_text" in value and not isinstance(value["replacement_text"], str):
        errors.append(_error("expected_string", f"{path}.replacement_text", "replacement text must be a string"))
    for field in ("reread_approved_analysis", "reread_approved_text"):
        if field in value and not isinstance(value[field], str):
            errors.append(_error("expected_string", f"{path}.{field}", f"{field} must be a string"))

    decision = value.get("lawyer_decision")
    if _enum_member(decision, {"revise", "reject", "not_applicable"}) and not _is_nonempty_string(value.get("lawyer_comment")):
        errors.append(
            _error("decision_reason_required", f"{path}.lawyer_comment", f"{decision} requires a reason")
        )
    if decision == "revise" and value.get("replacement_complete") is True:
        if not _is_nonempty_string(value.get("replacement_text")):
            errors.append(
                _error(
                    "replacement_text_required",
                    f"{path}.replacement_text",
                    "a complete replacement requires replacement text",
                )
            )
    if decision == "revise" and value.get("replacement_complete") is not True:
        reread_content_present = any(
            _is_nonempty_string(value.get(field))
            for field in ("reread_approved_analysis", "reread_approved_text")
        )
        if value.get("reread_confirmed") is True:
            if not all(
                _is_nonempty_string(value.get(field))
                for field in ("reread_approved_analysis", "reread_approved_text")
            ):
                errors.append(
                    _error(
                        "reread_approved_content_required",
                        path,
                        "a reread-confirmed direction-only revision requires approved analysis and approved text",
                    )
                )
        elif reread_content_present:
            errors.append(
                _error(
                    "reread_content_without_confirmation",
                    path,
                    "reread-approved content requires reread confirmation",
                )
            )
    return errors


def _validate_source_mapping(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, Mapping):
        return [_error("expected_source_mapping_object", path, "source mapping must be an object")]
    errors = _check_fields(
        value,
        allowed=SOURCE_MAPPING_FIELDS,
        required=SOURCE_MAPPING_FIELDS,
        path=path,
    )
    for field in ("confirmation_id", "source_file_id", "clause_locator"):
        if field in value and not _is_nonempty_string(value[field]):
            errors.append(_error("expected_nonempty_string", f"{path}.{field}", f"{field} must be non-empty"))
    for field in ("confirmation_id", "source_file_id"):
        if field in value:
            errors.extend(_identifier_error(value[field], f"{path}.{field}"))
    for field in ("excerpt_sha256", "proposed_content_sha256"):
        if field in value:
            errors.extend(_validate_sha256(value[field], f"{path}.{field}"))
    return errors


def _validate_source_file(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, Mapping):
        return [_error("expected_source_file_object", path, "source file must be an object")]
    errors = _check_fields(value, allowed=SOURCE_FILE_FIELDS, required=SOURCE_FILE_FIELDS, path=path)
    for field in ("source_file_id", "path"):
        if field in value and not _is_nonempty_string(value[field]):
            errors.append(_error("expected_nonempty_string", f"{path}.{field}", f"{field} must be non-empty"))
    if "source_file_id" in value:
        errors.extend(_identifier_error(value["source_file_id"], f"{path}.source_file_id"))
    if "sha256" in value:
        errors.extend(_validate_sha256(value["sha256"], f"{path}.sha256"))
    return errors


def _projection_is(value: Any, *, disposition: str, flags: bool = False) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("client_report_disposition") == disposition
        and value.get("include_in_major_issue_list") is flags
        and value.get("include_in_counterparty_comment") is flags
        and value.get("include_in_redline") is flags
    )


def _active_decisions(issue: Mapping[str, Any]) -> list[str]:
    subitems = issue.get("subitems")
    if not isinstance(subitems, list):
        return []
    decisions: list[str] = []
    for item in subitems:
        if not isinstance(item, Mapping):
            continue
        if item.get("completion_impact") == "informational" or item.get("required_for_final") is not True:
            continue
        decision = item.get("lawyer_decision")
        if _enum_member(decision, LAWYER_DECISIONS):
            decisions.append(decision)
    return decisions


def _validate_hard_combination(issue: Mapping[str, Any], path: str) -> list[ValidationError]:
    decisions = _active_decisions(issue)
    if not decisions:
        return []
    errors: list[ValidationError] = []
    action = issue.get("drafting_action")
    projections = issue.get("projections")

    if "defer_client" in decisions and "defer_research" in decisions:
        errors.append(
            _error(
                "mixed_pending_decisions",
                f"{path}.subitems",
                "client and legal pending decisions cannot share one issue action",
            )
        )
        return errors
    if "defer_client" in decisions:
        if action != "no_contract_change":
            errors.append(
                _error(
                    "defer_client_requires_no_contract_change",
                    f"{path}.drafting_action",
                    "defer_client requires no_contract_change",
                )
            )
        if not _projection_is(projections, disposition="client_pending"):
            errors.append(
                _error(
                    "defer_client_forbids_external_projection",
                    f"{path}.projections",
                    "defer_client requires client_pending and disables external projections",
                )
            )
        return errors
    if "defer_research" in decisions:
        if action != "no_contract_change":
            errors.append(
                _error(
                    "defer_research_requires_no_contract_change",
                    f"{path}.drafting_action",
                    "defer_research requires no_contract_change",
                )
            )
        if not _projection_is(projections, disposition="legal_pending"):
            errors.append(
                _error(
                    "defer_research_requires_legal_pending",
                    f"{path}.projections",
                    "defer_research requires legal_pending and disables external projections",
                )
            )
        return errors
    if set(decisions).issubset({"agree", "not_applicable"}) and "agree" in decisions:
        if action != issue.get("proposed_drafting_action"):
            errors.append(
                _error(
                    "agree_requires_proposed_action",
                    f"{path}.drafting_action",
                    "agree cannot change the proposed drafting action",
                )
            )
        if projections != issue.get("proposed_projections"):
            errors.append(
                _error(
                    "agree_requires_proposed_projections",
                    f"{path}.projections",
                    "agree cannot change the proposed projections",
                )
            )
        return errors
    if set(decisions) == {"not_applicable"}:
        if action != "not_applicable":
            errors.append(
                _error(
                    "not_applicable_requires_action",
                    f"{path}.drafting_action",
                    "not_applicable requires the not_applicable action",
                )
            )
        if not _projection_is(projections, disposition="internal_only"):
            errors.append(
                _error(
                    "not_applicable_forbids_external_projection",
                    f"{path}.projections",
                    "not_applicable must remain internal and disable external projections",
                )
            )
        return errors
    if "revise" in decisions:
        if not _enum_member(action, DRAFTING_ACTIONS - {"not_applicable"}):
            errors.append(
                _error(
                    "revise_invalid_action",
                    f"{path}.drafting_action",
                    "revise requires a substantive drafting action",
                )
            )
        disposition = projections.get("client_report_disposition") if isinstance(projections, Mapping) else None
        if not _enum_member(disposition, {"include", "internal_only"}):
            errors.append(
                _error(
                    "revise_invalid_client_disposition",
                    f"{path}.projections.client_report_disposition",
                    "revise permits include or reasoned internal_only",
                )
            )
        return errors
    if "reject" in decisions:
        if not _enum_member(action, {"keep_current", "no_contract_change"}):
            errors.append(
                _error(
                    "reject_invalid_action",
                    f"{path}.drafting_action",
                    "reject permits keep_current or no_contract_change",
                )
            )
        if not _projection_is(projections, disposition="internal_only"):
            errors.append(
                _error(
                    "reject_requires_internal_projection",
                    f"{path}.projections",
                    "reject defaults to internal_only and disables external projections",
                )
            )
        return errors
    return errors


def validate_issue(issue: Any, path: str = "$") -> list[ValidationError]:
    """Validate one issue card without raising for malformed external input."""

    if not isinstance(issue, Mapping):
        return [_error("expected_object", path, "issue must be an object")]
    errors = _check_fields(issue, allowed=ISSUE_FIELDS, required=REQUIRED_ISSUE_FIELDS, path=path)
    structural_scan_errors = _non_finite_errors(issue, path)
    errors.extend(structural_scan_errors)
    if any(error.code in {"input_too_deep", "input_too_large"} for error in structural_scan_errors):
        return _dedupe_errors(errors)

    issue_id = issue.get("issue_id")
    if "issue_id" in issue and not _is_nonempty_string(issue_id):
        errors.append(_error("invalid_issue_id", f"{path}.issue_id", "issue ID must be non-empty"))
    elif issue_id in RESERVED_ROUTING_IDS:
        errors.append(_error("reserved_identifier", f"{path}.issue_id", "identifier is reserved for confirmation routing"))
    if "issue_id" in issue:
        errors.extend(_identifier_error(issue_id, f"{path}.issue_id"))
    is_lawyer_new_prefix = isinstance(issue_id, str) and issue_id.startswith("LAWYER-NEW-")
    is_lawyer_new = isinstance(issue_id, str) and bool(LAWYER_NEW_ID.fullmatch(issue_id))
    if is_lawyer_new_prefix and not is_lawyer_new:
        errors.append(_error("invalid_lawyer_new_id", f"{path}.issue_id", "lawyer-new ID must match LAWYER-NEW-###"))
    if is_lawyer_new and issue.get("lawyer_new_placeholder") is not True:
        errors.append(
            _error(
                "lawyer_new_placeholder_required",
                f"{path}.lawyer_new_placeholder",
                "lawyer-new records must be marked as placeholders",
            )
        )
    if "lawyer_new_placeholder" in issue and type(issue["lawyer_new_placeholder"]) is not bool:
        errors.append(
            _error("expected_boolean", f"{path}.lawyer_new_placeholder", "placeholder flag must be boolean")
        )
    if issue.get("lawyer_new_placeholder") is True and not is_lawyer_new:
        errors.append(
            _error(
                "placeholder_only_for_lawyer_new",
                f"{path}.lawyer_new_placeholder",
                "placeholder flag is reserved for LAWYER-NEW-### records",
            )
        )

    for field in ("file", "clause", "risk", "displayed_analysis"):
        if field in issue and not _is_nonempty_string(issue[field]):
            errors.append(
                _error("expected_nonempty_string", f"{path}.{field}", f"{field} must be non-empty")
            )
    sync_scope = issue.get("sync_scope")
    if "sync_scope" in issue and (
        not isinstance(sync_scope, list)
        or any(not _is_nonempty_string(entry) for entry in sync_scope)
    ):
        errors.append(
            _error("expected_string_array", f"{path}.sync_scope", "sync scope must be an array of strings")
        )
    source_mappings = issue.get("source_mappings")
    if "source_mappings" in issue and not isinstance(source_mappings, list):
        errors.append(
            _error(
                "expected_source_mappings_array",
                f"{path}.source_mappings",
                "source mappings must be an array",
            )
        )
    elif isinstance(source_mappings, list):
        for index, mapping in enumerate(source_mappings):
            errors.extend(_validate_source_mapping(mapping, f"{path}.source_mappings[{index}]"))

    for field in ("proposed_drafting_action", "drafting_action"):
        if field in issue and not _enum_member(issue[field], DRAFTING_ACTIONS):
            errors.append(_error("invalid_drafting_action", f"{path}.{field}", "drafting action is not supported"))
    for field in ("proposed_projections", "projections"):
        if field in issue:
            errors.extend(_validate_projection(issue[field], f"{path}.{field}"))

    subitems = issue.get("subitems")
    if "subitems" in issue and not isinstance(subitems, list):
        errors.append(_error("expected_subitems_array", f"{path}.subitems", "subitems must be an array"))
    elif isinstance(subitems, list):
        seen: set[str] = set()
        for index, item in enumerate(subitems):
            item_path = f"{path}.subitems[{index}]"
            errors.extend(_validate_subitem(item, item_path))
            if isinstance(item, Mapping) and _is_nonempty_string(item.get("confirmation_id")):
                confirmation_id = item["confirmation_id"]
                if confirmation_id in seen:
                    errors.append(
                        _error(
                            "duplicate_confirmation_id",
                            f"{item_path}.confirmation_id",
                            "confirmation ID is duplicated",
                        )
                    )
                seen.add(confirmation_id)
        mapped_ids: set[str] = set()
        mapping_keys: set[tuple[str, str, str]] = set()
        if isinstance(source_mappings, list):
            for mapping_index, mapping in enumerate(source_mappings):
                if not isinstance(mapping, Mapping):
                    continue
                mapping_path = f"{path}.source_mappings[{mapping_index}]"
                confirmation_id = mapping.get("confirmation_id")
                if not _is_nonempty_string(confirmation_id):
                    continue
                if confirmation_id not in seen:
                    errors.append(
                        _error(
                            "unknown_mapped_confirmation_id",
                            f"{mapping_path}.confirmation_id",
                            f"mapped confirmation ID {confirmation_id} is not in this issue",
                        )
                    )
                    continue
                mapped_ids.add(confirmation_id)
                source_file_id = mapping.get("source_file_id")
                clause_locator = mapping.get("clause_locator")
                if _is_nonempty_string(source_file_id) and _is_nonempty_string(clause_locator):
                    mapping_key = (confirmation_id, source_file_id, clause_locator)
                    if mapping_key in mapping_keys:
                        errors.append(
                            _error(
                                "duplicate_source_mapping",
                                mapping_path,
                                "source mapping is duplicated",
                            )
                        )
                    mapping_keys.add(mapping_key)
        for confirmation_id in sorted(seen - mapped_ids):
            errors.append(
                _error(
                    "missing_source_mapping",
                    f"{path}.source_mappings",
                    f"confirmation ID {confirmation_id} has no source mapping",
                )
            )
    if is_lawyer_new:
        if issue.get("drafting_action") != "no_contract_change" or not _projection_is(
            issue.get("projections"), disposition="internal_only"
        ):
            errors.append(
                _error(
                    "lawyer_new_must_remain_draft",
                    path,
                    "lawyer-new placeholders cannot change contracts or enter external projections",
                )
            )
    else:
        errors.extend(_validate_hard_combination(issue, path))
    return _dedupe_errors(errors)


def _required_items(issue: Any) -> list[Mapping[str, Any]]:
    if not isinstance(issue, Mapping) or not isinstance(issue.get("subitems"), list):
        return []
    return [
        item
        for item in issue["subitems"]
        if isinstance(item, Mapping)
        and item.get("required_for_final") is True
        and item.get("completion_impact") != "informational"
    ]


def reduce_issue(issue: Any) -> dict[str, Any]:
    """Deterministically reduce a validated or malformed issue to a gate state."""

    errors = validate_issue(issue)
    required_items = _required_items(issue)
    informational_count = 0
    if isinstance(issue, Mapping) and isinstance(issue.get("subitems"), list):
        informational_count = sum(
            1
            for item in issue["subitems"]
            if isinstance(item, Mapping) and item.get("completion_impact") == "informational"
        )

    unresolved: list[str] = []
    reread_required: list[str] = []
    foundational_pending = False
    blank_pending = False
    local_defer_only = True
    applicable = 0
    not_applicable = 0
    for item in required_items:
        confirmation_id = str(item.get("confirmation_id", ""))
        decision = item.get("lawyer_decision")
        if decision == "not_applicable":
            not_applicable += 1
            continue
        applicable += 1
        if decision == "revise" and item.get("replacement_complete") is not True and item.get("reread_confirmed") is not True:
            unresolved.append(confirmation_id)
            reread_required.append(confirmation_id)
            local_defer_only = False
            if item.get("completion_impact") == "foundational":
                foundational_pending = True
        elif _enum_member(decision, {"defer_client", "defer_research"}):
            unresolved.append(confirmation_id)
            if item.get("completion_impact") == "foundational":
                foundational_pending = True
        elif not _enum_member(decision, LAWYER_DECISIONS):
            unresolved.append(confirmation_id)
            blank_pending = True
            local_defer_only = False
            if item.get("completion_impact") == "foundational":
                foundational_pending = True

    unresolved = sorted(set(unresolved))
    reread_required = sorted(set(reread_required))
    is_lawyer_new = isinstance(issue, Mapping) and bool(issue.get("lawyer_new_placeholder"))
    if errors or is_lawyer_new or reread_required or foundational_pending or blank_pending:
        status = "blocked"
    elif unresolved and local_defer_only:
        status = "passed_with_limitations"
    elif required_items and not_applicable == len(required_items):
        status = "not_applicable"
    else:
        status = "passed"

    return {
        "issue_id": issue.get("issue_id") if isinstance(issue, Mapping) else None,
        "status": status,
        "unresolved_required_ids": unresolved,
        "reread_required_ids": reread_required,
        "reread_required": bool(reread_required or is_lawyer_new),
        "approved": status == "passed",
        "validation_errors": errors,
        "counts": {
            "required": len(required_items),
            "applicable_required": applicable,
            "not_applicable_required": not_applicable,
            "informational": informational_count,
            "unresolved_required": len(unresolved),
        },
    }


def _validate_batch(value: Any, path: str) -> list[ValidationError]:
    if not isinstance(value, Mapping):
        return [_error("expected_batch_object", path, "batch decision must be an object")]
    errors = _check_fields(value, allowed=BATCH_FIELDS, required=REQUIRED_BATCH_FIELDS, path=path)
    if "batch_id" in value and not _is_nonempty_string(value["batch_id"]):
        errors.append(_error("invalid_batch_id", f"{path}.batch_id", "batch ID must be non-empty"))
    elif value.get("batch_id") in RESERVED_ROUTING_IDS:
        errors.append(_error("reserved_identifier", f"{path}.batch_id", "identifier is reserved for confirmation routing"))
    if "batch_id" in value:
        errors.extend(_identifier_error(value["batch_id"], f"{path}.batch_id"))
    if "category" in value and not _enum_member(value["category"], BATCH_CATEGORIES):
        errors.append(
            _error("invalid_batch_category", f"{path}.category", "batch category is not supported")
        )
    for field in ("confirmation_ids", "exception_confirmation_ids"):
        item = value.get(field)
        if field in value and (not isinstance(item, list) or any(not _is_nonempty_string(entry) for entry in item)):
            errors.append(_error("expected_id_array", f"{path}.{field}", f"{field} must be an array of IDs"))
        if isinstance(item, list):
            for index, identifier in enumerate(item):
                errors.extend(_identifier_error(identifier, f"{path}.{field}[{index}]"))
    decision = value.get("lawyer_decision")
    if "lawyer_decision" in value and decision is not None and not _enum_member(decision, LAWYER_DECISIONS):
        errors.append(_error("invalid_lawyer_decision", f"{path}.lawyer_decision", "lawyer decision is not supported"))
    if "lawyer_comment" in value and not isinstance(value["lawyer_comment"], str):
        errors.append(_error("expected_string", f"{path}.lawyer_comment", "lawyer comment must be a string"))
    if _enum_member(decision, {"revise", "reject", "not_applicable"}) and not _is_nonempty_string(value.get("lawyer_comment")):
        errors.append(_error("decision_reason_required", f"{path}.lawyer_comment", f"{decision} requires a reason"))
    ids = value.get("confirmation_ids")
    exceptions = value.get("exception_confirmation_ids")
    if (
        isinstance(ids, list)
        and isinstance(exceptions, list)
        and all(_is_nonempty_string(item) for item in ids)
        and all(_is_nonempty_string(item) for item in exceptions)
    ):
        for confirmation_id in sorted(set(exceptions) - set(ids)):
            errors.append(
                _error(
                    "batch_exception_outside_scope",
                    f"{path}.exception_confirmation_ids",
                    f"exception {confirmation_id} is outside the batch scope",
                )
            )
    return errors


def validate_manifest(manifest: Any) -> list[ValidationError]:
    """Validate a matter manifest, including cross-issue and batch conflicts."""

    if not isinstance(manifest, Mapping):
        return [_error("expected_object", "$", "manifest must be an object")]
    errors = _check_fields(manifest, allowed=MANIFEST_FIELDS, required=REQUIRED_MANIFEST_FIELDS, path="$")
    structural_scan_errors = _non_finite_errors(manifest, "$")
    errors.extend(structural_scan_errors)
    if any(error.code in {"input_too_deep", "input_too_large"} for error in structural_scan_errors):
        return _dedupe_errors(errors)
    if "schema_version" in manifest and manifest["schema_version"] != "1.0":
        errors.append(_error("unsupported_schema_version", "$.schema_version", "schema version is not supported"))
    for field in ("matter_id", "confirmation_batch_id"):
        if field in manifest and not _is_nonempty_string(manifest[field]):
            errors.append(_error(f"invalid_{field}", f"$.{field}", f"{field} must be non-empty"))
        if field in manifest:
            errors.extend(_identifier_error(manifest[field], f"$.{field}"))
    review_round = manifest.get("review_round")
    if "review_round" in manifest and (type(review_round) is not int or review_round < 1):
        errors.append(
            _error("invalid_review_round", "$.review_round", "review round must be a positive integer")
        )
    if "generated_at" in manifest and not _is_iso8601_datetime(manifest["generated_at"]):
        errors.append(
            _error(
                "invalid_generated_at",
                "$.generated_at",
                "generated_at must be an ISO 8601 datetime with timezone",
            )
        )
    if "language" in manifest and not _enum_member(manifest["language"], LANGUAGES):
        errors.append(_error("invalid_language", "$.language", "language must be zh-CN or en"))
    for field in (
        "source_file_collection_sha256",
        "issue_log_sha256",
        "issue_snapshot_sha256",
        "base_manifest_sha256",
        "generated_form_sha256",
        "immutable_visible_content_sha256",
        "sdt_manifest_sha256",
    ):
        if field in manifest:
            errors.extend(_validate_sha256(manifest[field], f"$.{field}"))

    source_file_ids: set[str] = set()
    source_file_paths: dict[str, str] = {}
    source_files = manifest.get("source_files")
    if "source_files" in manifest and not isinstance(source_files, list):
        errors.append(_error("expected_source_files_array", "$.source_files", "source files must be an array"))
    elif isinstance(source_files, list):
        for index, source_file in enumerate(source_files):
            source_path = f"$.source_files[{index}]"
            errors.extend(_validate_source_file(source_file, source_path))
            if not isinstance(source_file, Mapping) or not _is_nonempty_string(source_file.get("source_file_id")):
                continue
            source_file_id = source_file["source_file_id"]
            if source_file_id in source_file_ids:
                errors.append(
                    _error("duplicate_source_file_id", f"{source_path}.source_file_id", "source file ID is duplicated")
                )
            source_file_ids.add(source_file_id)
            if _is_nonempty_string(source_file.get("path")):
                source_file_paths[source_file_id] = source_file["path"]
        collection_digest = manifest.get("source_file_collection_sha256")
        if isinstance(collection_digest, str) and SHA256_PATTERN.fullmatch(collection_digest):
            try:
                expected_collection_digest = canonical_json_sha256(source_files)
            except (TypeError, ValueError):
                expected_collection_digest = None
            if expected_collection_digest is not None and collection_digest != expected_collection_digest:
                errors.append(
                    _error(
                        "source_file_collection_digest_mismatch",
                        "$.source_file_collection_sha256",
                        "source file collection digest does not match source_files",
                    )
                )

    confirmation_index: dict[str, Mapping[str, Any]] = {}
    issue_ids: set[str] = set()
    issues = manifest.get("issues")
    if "issues" in manifest and not isinstance(issues, list):
        errors.append(_error("expected_issues_array", "$.issues", "issues must be an array"))
    elif isinstance(issues, list):
        for index, issue in enumerate(issues):
            issue_path = f"$.issues[{index}]"
            errors.extend(validate_issue(issue, issue_path))
            if not isinstance(issue, Mapping):
                continue
            issue_id = issue.get("issue_id")
            if _is_nonempty_string(issue_id):
                if issue_id in issue_ids:
                    errors.append(_error("duplicate_issue_id", f"{issue_path}.issue_id", "issue ID is duplicated"))
                issue_ids.add(issue_id)
            if isinstance(issue.get("subitems"), list):
                for item_index, item in enumerate(issue["subitems"]):
                    if not isinstance(item, Mapping) or not _is_nonempty_string(item.get("confirmation_id")):
                        continue
                    confirmation_id = item["confirmation_id"]
                    if confirmation_id in confirmation_index:
                        errors.append(
                            _error(
                                "duplicate_confirmation_id",
                                f"{issue_path}.subitems[{item_index}].confirmation_id",
                                "confirmation ID is duplicated across issues",
                            )
                        )
                    else:
                        confirmation_index[confirmation_id] = item
            if isinstance(issue.get("source_mappings"), list):
                for mapping_index, mapping in enumerate(issue["source_mappings"]):
                    if not isinstance(mapping, Mapping):
                        continue
                    source_file_id = mapping.get("source_file_id")
                    if _is_nonempty_string(source_file_id) and source_file_id not in source_file_ids:
                        errors.append(
                            _error(
                                "unknown_source_file_id",
                                f"{issue_path}.source_mappings[{mapping_index}].source_file_id",
                                f"source file ID {source_file_id} is unknown",
                            )
                        )

    batches = manifest.get("batch_decisions")
    if "batch_decisions" in manifest and not isinstance(batches, list):
        errors.append(_error("expected_batch_decisions_array", "$.batch_decisions", "batch decisions must be an array"))
    elif isinstance(batches, list):
        seen_batches: set[str] = set()
        batch_decisions_by_confirmation: dict[str, set[str]] = {}
        for index, batch in enumerate(batches):
            batch_path = f"$.batch_decisions[{index}]"
            errors.extend(_validate_batch(batch, batch_path))
            if not isinstance(batch, Mapping):
                continue
            batch_id = batch.get("batch_id")
            if _is_nonempty_string(batch_id):
                if batch_id in seen_batches:
                    errors.append(_error("duplicate_batch_id", f"{batch_path}.batch_id", "batch ID is duplicated"))
                seen_batches.add(batch_id)
            ids = batch.get("confirmation_ids")
            exceptions = batch.get("exception_confirmation_ids")
            decision = batch.get("lawyer_decision")
            if not isinstance(ids, list) or not isinstance(exceptions, list):
                continue
            for confirmation_id in ids:
                if not _is_nonempty_string(confirmation_id):
                    continue
                if confirmation_id not in confirmation_index:
                    errors.append(
                        _error(
                            "unknown_confirmation_id",
                            f"{batch_path}.confirmation_ids",
                            f"confirmation ID {confirmation_id} is unknown",
                        )
                    )
                    continue
                if confirmation_id not in exceptions and _enum_member(decision, LAWYER_DECISIONS):
                    batch_decisions_by_confirmation.setdefault(confirmation_id, set()).add(decision)
                if (
                    batch.get("category") == "text_cleanup"
                    and confirmation_id not in exceptions
                    and confirmation_index[confirmation_id].get("item_type") != "drafting"
                ):
                    errors.append(
                        _error(
                            "text_cleanup_ineligible_item",
                            f"{batch_path}.confirmation_ids",
                            f"text_cleanup cannot cover {confirmation_index[confirmation_id].get('item_type')} item {confirmation_id}",
                        )
                    )
                individual = confirmation_index[confirmation_id].get("lawyer_decision")
                if (
                    confirmation_id not in exceptions
                    and _enum_member(decision, LAWYER_DECISIONS)
                    and individual is not None
                    and individual != decision
                ):
                    errors.append(
                        _error(
                            "batch_individual_conflict",
                            f"{batch_path}.confirmation_ids",
                            f"batch and individual decisions conflict for {confirmation_id}",
                        )
                    )
        for confirmation_id in sorted(batch_decisions_by_confirmation):
            decisions = batch_decisions_by_confirmation[confirmation_id]
            if len(decisions) > 1:
                errors.append(
                    _error(
                        "conflicting_batch_decisions",
                        "$.batch_decisions",
                        f"batches assign conflicting decisions to {confirmation_id}",
                    )
                )

    if isinstance(issues, list):
        required_items = [item for issue in issues for item in _required_items(issue)]
        applicable = [item for item in required_items if item.get("lawyer_decision") != "not_applicable"]
        evidenced_na = any(
            item.get("lawyer_decision") == "not_applicable" and _is_nonempty_string(item.get("lawyer_comment"))
            for item in required_items
        )
        if not applicable and not evidenced_na:
            errors.append(
                _error(
                    "zero_applicable_without_evidence",
                    "$.issues",
                    "zero applicable items requires an evidenced not_applicable decision",
                )
            )
    effective_manifest = resolve_effective_manifest(manifest)
    effective_issues = (
        effective_manifest.get("issues") if isinstance(effective_manifest, Mapping) else None
    )
    if isinstance(effective_issues, list):
        for index, issue in enumerate(effective_issues):
            errors.extend(validate_issue(issue, f"$.issues[{index}]"))
    return _dedupe_errors(errors)


def resolve_effective_manifest(manifest: Any) -> Any:
    """Copy a manifest and apply only unambiguous, non-excepted batch decisions."""

    if not isinstance(manifest, Mapping):
        return manifest
    if any(
        error.code in {"input_too_deep", "input_too_large"}
        for error in _non_finite_errors(manifest, "$")
    ):
        return manifest
    effective = deepcopy(manifest)
    issues = effective.get("issues")
    batches = effective.get("batch_decisions")
    if not isinstance(issues, list) or not isinstance(batches, list):
        return effective
    subitem_index: dict[str, dict[str, Any]] = {}
    for issue in issues:
        if not isinstance(issue, Mapping) or not isinstance(issue.get("subitems"), list):
            continue
        for item in issue["subitems"]:
            if isinstance(item, dict) and _is_nonempty_string(item.get("confirmation_id")):
                subitem_index[item["confirmation_id"]] = item
    candidates: dict[str, list[tuple[str, str]]] = {}
    for batch in batches:
        if not isinstance(batch, Mapping):
            continue
        ids = batch.get("confirmation_ids")
        exceptions = batch.get("exception_confirmation_ids")
        decision = batch.get("lawyer_decision")
        if (
            not isinstance(ids, list)
            or not isinstance(exceptions, list)
            or not _enum_member(decision, LAWYER_DECISIONS)
        ):
            continue
        for confirmation_id in ids:
            if not _is_nonempty_string(confirmation_id) or confirmation_id in exceptions:
                continue
            candidates.setdefault(confirmation_id, []).append(
                (decision, batch.get("lawyer_comment", ""))
            )
    for confirmation_id in sorted(candidates):
        item = subitem_index.get(confirmation_id)
        if item is None or item.get("lawyer_decision") is not None:
            continue
        decisions = {decision for decision, _comment in candidates[confirmation_id]}
        if len(decisions) != 1:
            continue
        decision = next(iter(decisions))
        item["lawyer_decision"] = decision
        comments = sorted(
            comment
            for candidate_decision, comment in candidates[confirmation_id]
            if candidate_decision == decision and _is_nonempty_string(comment)
        )
        if not _is_nonempty_string(item.get("lawyer_comment")) and comments:
            item["lawyer_comment"] = comments[0]
    return effective


def reduce_matter(manifest: Any) -> dict[str, Any]:
    """Reduce all issues with foundational blockers taking deterministic priority."""

    errors = validate_manifest(manifest)
    if any(error.code in {"input_too_deep", "input_too_large"} for error in errors):
        effective_manifest = manifest
    else:
        effective_manifest = resolve_effective_manifest(manifest)
    issues = effective_manifest.get("issues", []) if isinstance(effective_manifest, Mapping) else []
    issue_results = [reduce_issue(issue) for issue in issues] if isinstance(issues, list) else []
    issue_results.sort(key=lambda item: str(item.get("issue_id") or ""))
    unresolved = sorted(
        {
            confirmation_id
            for result in issue_results
            for confirmation_id in result["unresolved_required_ids"]
        }
    )
    counts = {
        "issues": len(issue_results),
        "required": sum(result["counts"]["required"] for result in issue_results),
        "applicable_required": sum(result["counts"]["applicable_required"] for result in issue_results),
        "not_applicable_required": sum(result["counts"]["not_applicable_required"] for result in issue_results),
        "informational": sum(result["counts"]["informational"] for result in issue_results),
        "unresolved_required": len(unresolved),
    }
    if errors or any(result["status"] == "blocked" for result in issue_results):
        status = "blocked"
    elif any(result["status"] == "passed_with_limitations" for result in issue_results):
        status = "passed_with_limitations"
    else:
        status = "passed"
    return {
        "status": status,
        "approved": status in {"passed", "passed_with_limitations"},
        "zero_applicable": counts["applicable_required"] == 0 and not errors,
        "unresolved_required_ids": unresolved,
        "counts": counts,
        "issue_results": issue_results,
        "validation_errors": errors,
    }


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        normalized = [_canonicalize(item) for item in value]
        if normalized and all(isinstance(item, Mapping) for item in normalized):
            for identifier in ("confirmation_id", "issue_id", "batch_id"):
                if all(identifier in item for item in normalized):
                    return sorted(
                        normalized,
                        key=lambda item: (
                            str(item[identifier]),
                            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        ),
                    )
        return normalized
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_json_sha256(value: Any) -> str:
    """Return SHA-256 of canonical UTF-8 JSON with identified lists sorted."""

    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ValidationError",
    "canonical_json_sha256",
    "reduce_issue",
    "reduce_matter",
    "resolve_effective_manifest",
    "validate_issue",
    "validate_manifest",
]
