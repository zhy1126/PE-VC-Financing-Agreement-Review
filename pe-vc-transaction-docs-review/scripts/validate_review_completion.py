#!/usr/bin/env python3
"""Aggregate review evidence and block unsupported completion claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import review_checkpoint
from lawyer_confirmation_schema import canonical_json_sha256


SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = {1, 2}
TERMINAL_STAGE_STATUSES = {"completed", "completed_with_limitations", "not_applicable"}
JUDGMENT_GATE_NAMES = {
    "matter_and_authority",
    "substantive_coverage",
    "high_risk_spot_check",
    "delivery_and_confidentiality",
}
JUDGMENT_GATE_STATUSES = {"passed", "passed_with_limitations", "blocked"}
ABSOLUTE_USER_PATH = re.compile(r"/(?:Users|Volumes)/[^\s\"'<>]+")
INTERNAL_SOURCE_NAME = re.compile(r"(?!)")
PRIVATE_TREE_NAME = re.compile(r"(?!)")
LOCAL_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])/(?:Users|Volumes|private|System|Library|var|tmp)(?:/[^\s\"'<>;,]*)*"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(base: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def has_evidence(value: object) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, tuple, set)):
        return bool(value) and any(has_evidence(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and any(has_evidence(item) for item in value.values())
    return bool(value)


def safe_public_text(value: object) -> str:
    return LOCAL_PATH_PATTERN.sub("[local artifact]", str(value))


def content_sha256(value: dict[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return canonical_json_sha256(payload)


def active_import_head(import_store: Path, batch_id: object) -> dict[str, object] | None:
    records: list[dict[str, object]] = []
    for path in sorted(import_store.glob("import-*.json")) if import_store.is_dir() else []:
        try:
            value = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("record_type") != "lawyer_confirmation_import":
            return None
        if value.get("confirmation_batch_id") == batch_id:
            records.append(value)
    by_key = {
        str(record.get("idempotency_key")): record
        for record in records
        if isinstance(record.get("idempotency_key"), str) and record.get("idempotency_key")
    }
    if len(by_key) != len(records) or not records:
        return None
    superseded = {record.get("supersedes") for record in records if record.get("supersedes") is not None}
    if any(not isinstance(key, str) or key not in by_key for key in superseded):
        return None
    heads = sorted(set(by_key) - superseded)
    return by_key[heads[0]] if len(heads) == 1 else None


def machine_check(check_id: str, ok: bool, detail: str, evidence: str | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "id": check_id,
        "kind": "machine",
        "ok": ok,
        "detail": safe_public_text(detail),
    }
    if evidence:
        result["evidence"] = Path(evidence).name
    return result


def run_validator(script: Path, artifact: Path) -> tuple[bool, str]:
    process = subprocess.run(
        [sys.executable, str(script), str(artifact)],
        text=True,
        capture_output=True,
        check=False,
    )
    detail = (process.stdout.strip() or process.stderr.strip() or f"return code {process.returncode}")[:2000]
    return process.returncode == 0, detail


def validate_checkpoint(
    config: dict[str, object],
    base: Path,
    checks: list[dict[str, object]],
) -> tuple[dict[str, object] | None, list[Path]]:
    checkpoint_value = config.get("checkpoint")
    source_values = config.get("source_files")
    if not checkpoint_value:
        checks.append(machine_check("checkpoint", False, "checkpoint is required"))
        return None, []
    if not isinstance(source_values, list) or not source_values:
        checks.append(machine_check("source_files", False, "at least one source file is required"))
        return None, []

    checkpoint_path = resolve_path(base, checkpoint_value)
    sources = [resolve_path(base, value) for value in source_values]
    missing_sources = [path for path in sources if not path.is_file()]
    if missing_sources:
        checks.append(
            machine_check(
                "source_files",
                False,
                "missing source file(s): " + ", ".join(path.name for path in missing_sources),
            )
        )
        return None, sources
    try:
        state = review_checkpoint.load_state(checkpoint_path)
    except (OSError, ValueError) as exc:
        checks.append(machine_check("checkpoint", False, str(exc), str(checkpoint_path)))
        return None, sources

    matter_id = str(config.get("matter_id", "")).strip()
    identity_ok = bool(matter_id) and state.get("matter_id") == matter_id
    checks.append(
        machine_check(
            "matter_identity",
            identity_ok,
            "checkpoint matter matches config" if identity_ok else "matter_id is missing or does not match checkpoint",
            str(checkpoint_path),
        )
    )
    current_records = review_checkpoint.source_records(sources)
    fingerprint_ok = state.get("source_files") == current_records
    checks.append(
        machine_check(
            "source_fingerprints",
            fingerprint_ok,
            "source fingerprints unchanged" if fingerprint_ok else "source files changed after checkpoint creation",
            str(checkpoint_path),
        )
    )
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    incomplete = {
        stage: (stages.get(stage) or {}).get("status", "missing")
        for stage in review_checkpoint.STAGES
        if not isinstance(stages.get(stage), dict)
        or (stages.get(stage) or {}).get("status") not in TERMINAL_STAGE_STATUSES
    }
    checks.append(
        machine_check(
            "checkpoint_stages",
            not incomplete,
            "all review stages reached a terminal status" if not incomplete else f"non-terminal stages: {incomplete}",
            str(checkpoint_path),
        )
    )
    return state, sources


def validate_artifacts(
    config: dict[str, object],
    base: Path,
    sources: list[Path],
    checks: list[dict[str, object]],
) -> list[Path]:
    artifacts = config.get("artifacts")
    if not isinstance(artifacts, dict):
        checks.append(machine_check("artifacts", False, "artifacts object is required"))
        return []
    scripts = Path(__file__).resolve().parent
    requirements = config.get("requirements") if isinstance(config.get("requirements"), dict) else {}
    deliverables: list[Path] = []

    issue_value = artifacts.get("issue_log")
    if not issue_value:
        checks.append(machine_check("issue_log", False, "issue_log is required"))
    else:
        issue_log = resolve_path(base, issue_value)
        if not issue_log.is_file():
            checks.append(machine_check("issue_log", False, "issue log is missing", str(issue_log)))
        else:
            ok, detail = run_validator(scripts / "validate_issue_log.py", issue_log)
            checks.append(machine_check("issue_log", ok, detail, str(issue_log)))
            deliverables.append(issue_log)

    major_required = bool(requirements.get("major_issue_list", False))
    major_value = artifacts.get("major_issue_list")
    if major_required and not major_value:
        checks.append(machine_check("major_issue_list", False, "major issue list is required"))
    elif major_value:
        major = resolve_path(base, major_value)
        if not major.is_file():
            checks.append(machine_check("major_issue_list", False, "major issue list is missing", str(major)))
        else:
            ok, detail = run_validator(scripts / "validate_major_issue_list.py", major)
            checks.append(machine_check("major_issue_list", ok, detail, str(major)))
            deliverables.append(major)

    matrix_required = bool(requirements.get("package_matrix", False))
    matrix_value = artifacts.get("package_matrix")
    if matrix_required and not matrix_value:
        checks.append(machine_check("package_matrix", False, "package matrix is required"))
    elif matrix_value:
        matrix_path = resolve_path(base, matrix_value)
        try:
            matrix = load_json(matrix_path)
            if not isinstance(matrix, dict):
                raise ValueError("package matrix must be a JSON object")
            extraction_errors = matrix.get("extraction_errors", [])
            document_count = int(matrix.get("document_count", 0))
            ok = document_count > 0 and not extraction_errors
            detail = (
                f"{document_count} document(s); no extraction errors"
                if ok
                else f"document_count={document_count}; extraction_errors={extraction_errors}"
            )
            checks.append(machine_check("package_matrix", ok, detail, str(matrix_path)))
            deliverables.append(matrix_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            checks.append(machine_check("package_matrix", False, f"invalid package matrix: {exc}", str(matrix_path)))

    comment_required = bool(requirements.get("native_comments", False))
    comment_value = artifacts.get("comment_apply_report")
    if comment_required and not comment_value:
        checks.append(machine_check("native_comments", False, "comment apply report is required"))
    elif comment_value:
        report_path = resolve_path(base, comment_value)
        try:
            report = load_json(report_path)
            if not isinstance(report, dict):
                raise ValueError("comment apply report must be a JSON object")
            ok = all(
                (
                    report.get("ok") is True,
                    report.get("visible_text_unchanged") is True,
                    report.get("source_file_unchanged") is True,
                    int(report.get("added_comment_count", 0)) > 0,
                    int(report.get("failed_rows", 0)) == 0,
                )
            )
            checks.append(
                machine_check(
                    "native_comments",
                    ok,
                    "native comments passed source and visible-text integrity checks"
                    if ok
                    else "native comment integrity report is incomplete or failed",
                    str(report_path),
                )
            )
            deliverables.append(report_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            checks.append(machine_check("native_comments", False, f"invalid comment report: {exc}", str(report_path)))

    extra = artifacts.get("deliverables", [])
    if not isinstance(extra, list):
        checks.append(machine_check("deliverables", False, "artifacts.deliverables must be a list"))
    else:
        extra_paths = [resolve_path(base, value) for value in extra]
        missing = [path for path in extra_paths if not path.is_file() or path.stat().st_size == 0]
        checks.append(
            machine_check(
                "deliverables",
                not missing and bool(extra_paths),
                "all declared deliverables exist and are non-empty"
                if not missing and extra_paths
                else "missing, empty, or undeclared final deliverables: " + ", ".join(path.name for path in missing),
            )
        )
        deliverables.extend(path for path in extra_paths if path.is_file())

    source_hashes = {sha256_file(path) for path in sources if path.is_file()}
    output_overwrites_source = any(path.is_file() and sha256_file(path) in source_hashes for path in deliverables)
    checks.append(
        machine_check(
            "source_output_separation",
            not output_overwrites_source,
            "deliverables are distinct from source files"
            if not output_overwrites_source
            else "a declared deliverable is identical to a source file",
        )
    )
    return list(dict.fromkeys(deliverables))


def scan_deliverables(
    deliverables: list[Path],
    forbidden_terms: list[str],
    checks: list[dict[str, object]],
) -> None:
    findings: list[str] = []
    for path in deliverables:
        if path.suffix.lower() not in {".md", ".txt", ".csv", ".json"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        if ABSOLUTE_USER_PATH.search(text):
            findings.append(f"{path.name}: absolute local path")
        if INTERNAL_SOURCE_NAME.search(text):
            findings.append(f"{path.name}: named internal benchmark source")
        if PRIVATE_TREE_NAME.search(text):
            findings.append(f"{path.name}: private source-tree reference")
        for term in forbidden_terms:
            if term and term in text:
                findings.append(f"{path.name}: forbidden term {term!r}")
    checks.append(
        machine_check(
            "confidentiality_scan",
            not findings,
            "no configured confidentiality leak pattern found" if not findings else "; ".join(findings),
        )
    )


def validate_judgment_gates(config: dict[str, object]) -> tuple[list[dict[str, object]], bool]:
    raw = config.get("judgment_gates")
    results: list[dict[str, object]] = []
    has_limitations = False
    if not isinstance(raw, dict):
        return [
            {
                "id": name,
                "kind": "judgment",
                "status": "blocked",
                "ok": False,
                "detail": "required judgment gate is missing",
            }
            for name in sorted(JUDGMENT_GATE_NAMES)
        ], False
    for name in sorted(JUDGMENT_GATE_NAMES):
        gate = raw.get(name)
        if not isinstance(gate, dict):
            results.append(
                {"id": name, "kind": "judgment", "status": "blocked", "ok": False, "detail": "gate is missing"}
            )
            continue
        status = str(gate.get("status", ""))
        reviewer = str(gate.get("reviewer", "")).strip()
        evidence = str(gate.get("evidence", "")).strip()
        valid = status in JUDGMENT_GATE_STATUSES and bool(reviewer) and bool(evidence) and status != "blocked"
        if status == "passed_with_limitations":
            has_limitations = True
        results.append(
            {
                "id": name,
                "kind": "judgment",
                "status": status or "blocked",
                "ok": valid,
                "reviewer": safe_public_text(reviewer),
                "detail": safe_public_text(evidence or "reviewer and evidence are required"),
            }
        )
    return results, has_limitations


def has_final_output_claim(config: dict[str, object]) -> bool:
    artifacts = config.get("artifacts") if isinstance(config.get("artifacts"), dict) else {}
    final_artifact = config.get("final_artifact")
    final_status = final_artifact.get("status") if isinstance(final_artifact, dict) else None
    confirmation = config.get("lawyer_confirmation")
    confirmation_evidence = (
        confirmation.get("evidence")
        if isinstance(confirmation, dict) and isinstance(confirmation.get("evidence"), dict)
        else {}
    )
    final_marker = bool(
        isinstance(final_artifact, dict)
        and (final_status == "final" or final_artifact.get("report_model"))
    ) or any((
        config.get("artifact_state") == "final",
        bool(config.get("final_marker")),
        isinstance(confirmation, dict) and confirmation.get("artifact_state") == "final",
    ))
    deliverables = artifacts.get("deliverables") if isinstance(artifacts.get("deliverables"), list) else []
    final_like_docx = any(
        Path(str(value)).suffix.lower() == ".docx"
        and re.search(r"(?:final|report|审查报告|最终)", Path(str(value)).name, re.IGNORECASE)
        for value in deliverables
    )
    projected_json = any(
        re.search(r"(?:report[-_ ]?model|approved[-_ ]?content)", Path(str(value)).name, re.IGNORECASE)
        for value in deliverables
    )
    return bool(
        artifacts.get("report_model")
        or artifacts.get("final_report_model")
        or artifacts.get("approved_content")
        or artifacts.get("approved_content_package")
        or config.get("report_model")
        or config.get("approved_content")
        or confirmation_evidence.get("report_model")
        or confirmation_evidence.get("approved_content")
        or confirmation_evidence.get("final_docx")
        or final_marker
        or final_like_docx
        or projected_json
    )


def v1_claims_v016_final(config: dict[str, object]) -> bool:
    version_parts = tuple(
        int(part) for part in str(config.get("skill_version", "")).split(".")
        if part.isdigit()
    )
    version_v016_or_later = len(version_parts) >= 3 and version_parts[:3] >= (0, 1, 16)
    return bool(
        version_v016_or_later
        or config.get("lawyer_confirmation")
        or has_final_output_claim(config)
    )


def validator_detail(script: Path, process: subprocess.CompletedProcess[str]) -> str:
    """Return a bounded validator result without leaking local paths or raw payloads."""
    codes: list[str] = []
    try:
        payload = json.loads(process.stdout)
    except (json.JSONDecodeError, TypeError):
        payload = None
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            codes = sorted({
                str(item.get("code"))
                for item in errors
                if isinstance(item, dict) and item.get("code")
            })[:5]
    if process.returncode == 0:
        return f"{script.name} passed"
    code_detail = f" ({', '.join(codes)})" if codes else ""
    return f"{script.name} failed with exit code {process.returncode}{code_detail}"


def run_canonical_validator(script: Path, arguments: list[object]) -> tuple[bool, str]:
    try:
        process = subprocess.run(
            [sys.executable, str(script), *[str(argument) for argument in arguments]],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return False, f"{script.name} could not run ({type(exc).__name__})"
    return process.returncode == 0, validator_detail(script, process)


def canonical_file_match(actual: Path | None, expected: Path) -> bool:
    if actual is None or not actual.is_file() or not expected.is_file():
        return False
    try:
        return canonical_json_sha256(load_json(actual)) == canonical_json_sha256(load_json(expected))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return False


def load_evidence_file(
    evidence: dict[str, object],
    name: str,
    base: Path,
    checks: list[dict[str, object]],
) -> tuple[Path | None, object | None]:
    entry = evidence.get(name)
    if not isinstance(entry, dict):
        checks.append(machine_check(f"lawyer_confirmation_{name}", False, f"{name} evidence is required"))
        return None, None
    value = entry.get("path")
    expected_sha = str(entry.get("sha256", ""))
    if not value:
        checks.append(machine_check(f"lawyer_confirmation_{name}", False, f"{name}.path is required"))
        return None, None
    path = resolve_path(base, value)
    if not path.is_file():
        checks.append(machine_check(f"lawyer_confirmation_{name}", False, f"{name} evidence file is missing", str(path)))
        return path, None
    actual_sha = sha256_file(path)
    current = bool(re.fullmatch(r"[0-9a-f]{64}", expected_sha)) and expected_sha == actual_sha
    try:
        value = load_json(path) if path.suffix.lower() == ".json" else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        checks.append(machine_check(f"lawyer_confirmation_{name}", False, f"{name} evidence is unreadable: {exc}", str(path)))
        return path, None
    checks.append(machine_check(
        f"lawyer_confirmation_{name}", current,
        f"{name} evidence hash is current" if current else f"{name} evidence hash is missing or stale",
        str(path),
    ))
    return path, value


def validate_word_qa_binding(
    qa: object,
    *,
    qa_name: str,
    docx_path: Path | None,
    source_path: Path | None,
    approved_path: Path | None,
    checks: list[dict[str, object]],
) -> None:
    valid = isinstance(qa, dict)
    detail = "current Word QA evidence validated"
    if valid:
        pages = qa.get("pages")
        structural = qa.get("structural_checks")
        valid = all((
            qa.get("qa_schema_version") == "2.0",
            qa.get("artifact_type") == "word_render_qa",
            isinstance(pages, list) and bool(pages) and all(
                isinstance(page, dict) and page.get("inspected") is True for page in pages
            ),
            isinstance(structural, dict) and bool(structural) and all(value is True for value in structural.values()),
            docx_path is not None and qa.get("docx_sha256") == sha256_file(docx_path),
            source_path is not None and qa.get("source_sha256") == sha256_file(source_path),
            approved_path is None or qa.get("approved_content_sha256") == sha256_file(approved_path),
        ))
    if not valid:
        detail = "Word QA is missing, stale, uninspected, or structurally incomplete"
    checks.append(machine_check(f"lawyer_confirmation_{qa_name}_binding", valid, detail))


def validate_canonical_confirmation_evidence(
    evidence: dict[str, object],
    base: Path,
    paths: dict[str, Path],
    checks: list[dict[str, object]],
) -> None:
    """Recompute the v2 chain and invoke the authoritative artifact validators."""
    scripts = Path(__file__).resolve().parent
    base_manifest = paths.get("base_manifest")
    import_record = paths.get("active_import_record")
    approved_content = paths.get("approved_content")
    report_model = paths.get("report_model")
    pack_manifest = paths.get("confirmation_pack_manifest")
    confirmation_docx = paths.get("confirmation_docx")
    confirmation_qa = paths.get("confirmation_word_qa")
    final_docx = paths.get("final_docx")
    final_qa = paths.get("final_word_qa")

    if base_manifest is None:
        base_valid, base_detail = False, "validate_lawyer_confirmation.py requires base-manifest.json"
    else:
        base_valid, base_detail = run_canonical_validator(
            scripts / "validate_lawyer_confirmation.py",
            ["--input", base_manifest, "--json"],
        )
    checks.append(machine_check(
        "lawyer_confirmation_base_manifest_canonical",
        base_valid,
        base_detail,
    ))

    import_store_value = evidence.get("import_store")
    import_store = (
        resolve_path(base, import_store_value)
        if isinstance(import_store_value, str) and import_store_value.strip()
        else None
    )
    with tempfile.TemporaryDirectory(prefix="pevc-completion-") as temporary:
        temporary_dir = Path(temporary)
        rebuilt_approved = temporary_dir / "approved-content.json"
        rebuilt_report = temporary_dir / "report-model.json"

        if base_manifest is None or import_record is None or import_store is None:
            approved_built = False
            approved_detail = "build_approved_content_package.py requires base, active import, and import store"
        else:
            approved_built, approved_detail = run_canonical_validator(
                scripts / "build_approved_content_package.py",
                [
                    "--base-manifest", base_manifest,
                    "--import-record", import_record,
                    "--import-store", import_store,
                    "--output", rebuilt_approved,
                ],
            )
        approved_matches = approved_built and canonical_file_match(approved_content, rebuilt_approved)
        checks.append(machine_check(
            "lawyer_confirmation_approved_content_canonical",
            approved_matches,
            (
                "approved-content.json matches the deterministic active-import projection"
                if approved_matches
                else approved_detail if not approved_built
                else "approved-content.json differs from the deterministic active-import projection"
            ),
        ))

        if not approved_built:
            report_built = False
            report_detail = "build_report_model.py requires canonical approved-content.json"
        else:
            report_built, report_detail = run_canonical_validator(
                scripts / "build_report_model.py",
                ["--approved-content", rebuilt_approved, "--output", rebuilt_report],
            )
        report_matches = report_built and canonical_file_match(report_model, rebuilt_report)
        checks.append(machine_check(
            "lawyer_confirmation_report_model_canonical",
            report_matches,
            (
                "report-model.json matches the deterministic approved-content projection"
                if report_matches
                else report_detail if not report_built
                else "report-model.json differs from the deterministic approved-content projection"
            ),
        ))

    confirmation_render_value = evidence.get("confirmation_render_dir")
    confirmation_render = (
        resolve_path(base, confirmation_render_value)
        if isinstance(confirmation_render_value, str) and confirmation_render_value.strip()
        else None
    )
    confirmation_inputs = (
        confirmation_qa,
        confirmation_docx,
        confirmation_render,
        pack_manifest,
    )
    confirmation_docx_ok = confirmation_docx is not None and confirmation_docx.suffix.lower() == ".docx"
    if not confirmation_docx_ok or any(value is None for value in confirmation_inputs):
        confirmation_qa_ok = False
        confirmation_qa_detail = "validate_word_qa.py requires a DOCX, pack manifest, QA record, and render directory"
    else:
        confirmation_qa_ok, confirmation_qa_detail = run_canonical_validator(
            scripts / "validate_word_qa.py",
            [
                "--qa", confirmation_qa,
                "--docx", confirmation_docx,
                "--render-dir", confirmation_render,
                "--pack-manifest", pack_manifest,
                "--json",
            ],
        )
    checks.append(machine_check(
        "lawyer_confirmation_confirmation_word_qa_canonical",
        confirmation_qa_ok,
        confirmation_qa_detail,
    ))

    final_render_value = evidence.get("final_render_dir")
    final_render = (
        resolve_path(base, final_render_value)
        if isinstance(final_render_value, str) and final_render_value.strip()
        else None
    )
    final_inputs = (final_qa, final_docx, final_render, report_model, approved_content)
    final_docx_ok = final_docx is not None and final_docx.suffix.lower() == ".docx"
    if not final_docx_ok or any(value is None for value in final_inputs):
        final_qa_ok = False
        final_qa_detail = "validate_word_qa.py requires a DOCX, model, approved content, QA record, and render directory"
    else:
        final_qa_ok, final_qa_detail = run_canonical_validator(
            scripts / "validate_word_qa.py",
            [
                "--qa", final_qa,
                "--docx", final_docx,
                "--render-dir", final_render,
                "--report-model", report_model,
                "--approved-content", approved_content,
                "--json",
            ],
        )
    checks.append(machine_check(
        "lawyer_confirmation_final_word_qa_canonical",
        final_qa_ok,
        final_qa_detail,
    ))


def validate_lawyer_confirmation(
    config: dict[str, object],
    base: Path,
    checks: list[dict[str, object]],
) -> bool:
    block = config.get("lawyer_confirmation")
    if not isinstance(block, dict):
        checks.append(machine_check("lawyer_confirmation", False, "schema v2 requires lawyer_confirmation"))
        return False
    applicability = block.get("applicability")
    checks.append(machine_check(
        "lawyer_confirmation_applicability",
        applicability in {"required", "not_applicable"},
        "applicability recorded" if applicability in {"required", "not_applicable"} else
        "applicability must be required or not_applicable",
    ))
    trigger_ok = has_evidence(block.get("trigger_evidence"))
    checks.append(machine_check(
        "lawyer_confirmation_trigger_evidence", trigger_ok,
        "trigger evidence recorded" if trigger_ok else "nonempty trigger evidence is required",
    ))
    if applicability == "not_applicable":
        final_claim = has_final_output_claim(config)
        checks.append(machine_check(
            "lawyer_confirmation_not_applicable_final_claim",
            not final_claim,
            (
                "not_applicable is consistent with the absence of final artifacts"
                if not final_claim
                else "not_applicable cannot coexist with final artifacts, projections, or markers"
            ),
        ))
    if applicability != "required":
        return False

    evidence = block.get("evidence")
    if not isinstance(evidence, dict):
        checks.append(machine_check("lawyer_confirmation_evidence", False, "required confirmation evidence object is missing"))
        return False
    loaded: dict[str, object] = {}
    paths: dict[str, Path] = {}
    for name in (
        "base_manifest", "active_import_record", "approved_content", "report_model",
        "confirmation_pack_manifest", "confirmation_docx", "confirmation_word_qa",
        "final_docx", "final_word_qa",
    ):
        path, value = load_evidence_file(evidence, name, base, checks)
        if path is not None:
            paths[name] = path
        if value is not None:
            loaded[name] = value

    artifacts = config.get("artifacts") if isinstance(config.get("artifacts"), dict) else {}
    deliverable_values = artifacts.get("deliverables") if isinstance(artifacts.get("deliverables"), list) else []
    declared_deliverables = [resolve_path(base, value) for value in deliverable_values]
    final_docx_path = paths.get("final_docx")
    final_docx_entry = evidence.get("final_docx") if isinstance(evidence.get("final_docx"), dict) else {}
    final_qa_record = loaded.get("final_word_qa")
    final_hash = sha256_file(final_docx_path) if final_docx_path is not None and final_docx_path.is_file() else None
    final_deliverable_ok = all((
        final_docx_path is not None and final_docx_path in declared_deliverables,
        final_hash is not None,
        final_docx_entry.get("sha256") == final_hash,
        isinstance(final_qa_record, dict) and final_qa_record.get("docx_sha256") == final_hash,
    ))
    checks.append(machine_check(
        "final_deliverable_mismatch",
        final_deliverable_ok,
        (
            f"{final_docx_path.name} is the declared final deliverable and matches QA"
            if final_deliverable_ok and final_docx_path is not None
            else "final DOCX path or hash does not match artifacts.deliverables and QA"
        ),
    ))

    base_manifest = loaded.get("base_manifest")
    import_record = loaded.get("active_import_record")
    approved = loaded.get("approved_content")
    report = loaded.get("report_model")
    identities = []
    for value in (base_manifest, import_record, approved, report, loaded.get("confirmation_pack_manifest")):
        if isinstance(value, dict):
            identities.append((value.get("matter_id"), value.get("review_round"), value.get("confirmation_batch_id")))
    expected_identity = (
        config.get("matter_id"),
        base_manifest.get("review_round") if isinstance(base_manifest, dict) else None,
        base_manifest.get("confirmation_batch_id") if isinstance(base_manifest, dict) else None,
    )
    identity_ok = len(identities) == 5 and all(identity == expected_identity for identity in identities)
    checks.append(machine_check(
        "lawyer_confirmation_identity", identity_ok,
        "matter, round, and batch identities match" if identity_ok else "confirmation evidence identity mismatch",
    ))

    source_ok = isinstance(base_manifest, dict) and isinstance(base_manifest.get("source_files"), list)
    if source_ok:
        for item in base_manifest["source_files"]:
            if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
                source_ok = False
                break
            manifest_dir = paths["base_manifest"].parent if "base_manifest" in paths else base
            source_path = resolve_path(manifest_dir, item["path"])
            if not source_path.is_file() or sha256_file(source_path) != item["sha256"]:
                source_ok = False
                break
    checks.append(machine_check(
        "lawyer_confirmation_source_fingerprints", source_ok,
        "confirmation source fingerprints are current" if source_ok else "confirmation source fingerprint is stale or incomplete",
    ))

    import_store_value = evidence.get("import_store")
    import_current = False
    if import_store_value and isinstance(base_manifest, dict) and isinstance(import_record, dict):
        active = active_import_head(resolve_path(base, import_store_value), base_manifest.get("confirmation_batch_id"))
        import_current = active is not None and canonical_json_sha256(active) == canonical_json_sha256(import_record)
    checks.append(machine_check(
        "lawyer_confirmation_active_import", import_current,
        "import record is the unique active head" if import_current else "active import record is missing, stale, or conflicted",
    ))

    approved_ok = isinstance(approved, dict) and all((
        approved.get("package_type") == "approved_content_package",
        approved.get("approved_content_sha256") == content_sha256(approved, "approved_content_sha256"),
        isinstance(import_record, dict) and approved.get("import_idempotency_key") == import_record.get("idempotency_key"),
        isinstance(base_manifest, dict)
        and approved.get("source_manifest_sha256") == canonical_json_sha256(base_manifest),
        isinstance(import_record, dict) and isinstance(paths.get("base_manifest"), Path)
        and import_record.get("base_manifest_file_sha256") == sha256_file(paths["base_manifest"]),
    ))
    checks.append(machine_check(
        "lawyer_confirmation_approved_content", approved_ok,
        "approved content is bound to current base and import" if approved_ok else "approved content is stale or unbound",
    ))
    report_ok = isinstance(report, dict) and isinstance(approved, dict) and all((
        report.get("model_type") == "legal_review_report_model",
        report.get("report_model_sha256") == content_sha256(report, "report_model_sha256"),
        report.get("approved_content_sha256") == approved.get("approved_content_sha256"),
        report.get("matter_status") == approved.get("matter_status"),
    ))
    checks.append(machine_check(
        "lawyer_confirmation_report_model", report_ok,
        "report model is bound to approved content" if report_ok else "report model is stale or unbound",
    ))

    validate_word_qa_binding(
        loaded.get("confirmation_word_qa"), qa_name="confirmation_word_qa",
        docx_path=paths.get("confirmation_docx"), source_path=paths.get("confirmation_pack_manifest"),
        approved_path=None, checks=checks,
    )
    validate_word_qa_binding(
        loaded.get("final_word_qa"), qa_name="final_word_qa",
        docx_path=paths.get("final_docx"), source_path=paths.get("report_model"),
        approved_path=paths.get("approved_content"), checks=checks,
    )
    validate_canonical_confirmation_evidence(evidence, base, paths, checks)

    status = approved.get("matter_status") if isinstance(approved, dict) else "blocked"
    decisions = [
        decision
        for issue in approved.get("issues", []) if isinstance(approved, dict) and isinstance(issue, dict)
        for decision in issue.get("lawyer_decisions", []) if isinstance(decision, dict) and decision.get("required_for_final") is True
    ] if isinstance(approved, dict) else []
    foundational_pending = any(
        item.get("completion_impact") == "foundational"
        and item.get("lawyer_decision") in {None, "defer_client", "defer_research"}
        for item in decisions
    )
    blank_required = any(item.get("lawyer_decision") is None for item in decisions)
    draft = block.get("artifact_state") == "draft" or status == "blocked"
    final_status_ok = status in {"passed", "passed_with_limitations"} and not foundational_pending and not blank_required and not draft
    checks.append(machine_check(
        "lawyer_confirmation_final_status", final_status_ok,
        "confirmation status permits final output" if final_status_ok else
        "blank/foundational decision, reread, or draft status blocks final output",
    ))
    limited = status == "passed_with_limitations"
    disclosure_ok = not limited or bool(str(block.get("limitation_disclosure", "")).strip())
    checks.append(machine_check(
        "lawyer_confirmation_limitation_disclosure", disclosure_ok,
        "limitation disclosure is present" if disclosure_ok else "local pending items require prominent limitation disclosure",
    ))
    return limited


def evaluate(config: dict[str, object], config_path: Path) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    schema_version = config.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "completion_claim_allowed": False,
            "errors": ["config schema_version must be 1 or 2"],
            "checks": [],
        }
    base = config_path.resolve().parent
    if schema_version == 1 and v1_claims_v016_final(config):
        checks.append(machine_check(
            "legacy_v1_final_claim", False,
            "schema v1 cannot claim a v0.1.16 final artifact or report model; use schema v2",
        ))
    _, sources = validate_checkpoint(config, base, checks)
    deliverables = validate_artifacts(config, base, sources, checks)
    forbidden_terms = config.get("forbidden_terms", [])
    if not isinstance(forbidden_terms, list) or not all(isinstance(term, str) for term in forbidden_terms):
        checks.append(machine_check("forbidden_terms", False, "forbidden_terms must be a list of strings"))
        forbidden_terms = []
    scan_deliverables(deliverables, forbidden_terms, checks)
    judgment_checks, judgment_limitations = validate_judgment_gates(config)
    checks.extend(judgment_checks)
    confirmation_limitations = validate_lawyer_confirmation(config, base, checks) if schema_version == 2 else False

    limitations = config.get("limitations", [])
    limitation_errors: list[str] = []
    disclosed_limitations = False
    if not isinstance(limitations, list):
        limitation_errors.append("limitations must be a list")
    else:
        for index, limitation in enumerate(limitations, start=1):
            if not isinstance(limitation, dict):
                limitation_errors.append(f"limitation {index} must be an object")
                continue
            if not str(limitation.get("code", "")).strip() or not str(limitation.get("description", "")).strip():
                limitation_errors.append(f"limitation {index} requires code and description")
            if limitation.get("disclosed") is not True:
                limitation_errors.append(f"limitation {index} is not marked disclosed")
            disclosed_limitations = True
    checks.append(
        machine_check(
            "limitations",
            not limitation_errors,
            "limitations are disclosed and structured" if disclosed_limitations and not limitation_errors else (
                "no limitations declared" if not limitation_errors else "; ".join(limitation_errors)
            ),
        )
    )

    failed = [check for check in checks if not check.get("ok")]
    checkpoint_limited = False
    checkpoint_value = config.get("checkpoint")
    if checkpoint_value:
        try:
            state = review_checkpoint.load_state(resolve_path(base, checkpoint_value))
            checkpoint_limited = any(
                isinstance(record, dict) and record.get("status") == "completed_with_limitations"
                for record in (state.get("stages") or {}).values()
            )
        except (OSError, ValueError):
            pass
    has_limitations = judgment_limitations or disclosed_limitations or checkpoint_limited or confirmation_limitations
    status = "blocked" if failed else ("passed_with_limitations" if has_limitations else "passed")
    return {
        "schema_version": schema_version,
        "matter_id": config.get("matter_id"),
        "status": status,
        "completion_claim_allowed": status == "passed",
        "limited_completion_claim_allowed": status == "passed_with_limitations",
        "summary": {
            "check_count": len(checks),
            "failed_count": len(failed),
            "limitation_count": len(limitations) if isinstance(limitations, list) else 0,
        },
        "checks": checks,
        "errors": [str(check.get("detail")) for check in failed],
        "completion_rule": (
            "Only status=passed permits an unqualified completion claim. "
            "status=passed_with_limitations must be delivered as completed with prominently disclosed limitations. "
            "status=blocked prohibits any completion claim."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        config = load_json(args.config)
        if not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        report = evaluate(config, args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not run completion gate: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if report["status"] == "passed":
        return 0
    if report["status"] == "passed_with_limitations":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
