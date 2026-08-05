#!/usr/bin/env python3
"""Build and validate fail-closed Word render and structure QA evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from build_report_model import report_model_content_sha256, validate_report_model_binding
from lawyer_confirmation_schema import canonical_json_sha256


PAGE_PATTERN = re.compile(r"^page-([1-9][0-9]*)\.png$")
VISIBLE_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9-])(?:PEVC-[A-Za-z0-9-]+|LAWYER-NEW-[0-9]{3})(?![A-Za-z0-9-])"
)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
PACKAGE_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_RELS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PLACEHOLDERS = ("（请填写）", "（可填写）", "（如有，请填写）", "（未填写）", "TBD")

REPORT_REQUIRED_SECTIONS = [
    "范围、版本、立场与限制",
    "执行摘要",
    "Major Issue List",
    "已确认事实基础",
    "已批准法律与处理分析",
    "修改建议及同步修改",
    "待客户确认事项",
    "待进一步法律核验事项",
    "未审材料",
]
CONFIRMATION_REQUIRED_SECTIONS = [
    "1. 使用说明及完成度",
    "2. 项目事实问题",
    "3. 法律与处理分析",
    "4. 常规实质事项批量确认",
    "5. 律师新增关注点",
    "6. 未确认、冲突和缺材料摘要",
    "7. 补充意见及审阅信息",
]
REPORT_SECTION_KEYS = {
    "Major Issue List": "major_issue_list",
    "已确认事实基础": "confirmed_facts",
    "已批准法律与处理分析": "approved_analysis",
    "修改建议及同步修改": "modifications_sync",
    "待客户确认事项": "client_pending",
    "待进一步法律核验事项": "legal_pending",
}
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _page_files(render_dir: Path) -> list[tuple[int, Path]]:
    result = []
    for path in render_dir.iterdir() if render_dir.is_dir() else []:
        match = PAGE_PATTERN.fullmatch(path.name)
        if match and path.is_file():
            result.append((int(match.group(1)), path))
    return sorted(result)


def _error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _element_text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{W}t")).strip()


def _active_header_footer_parts(archive: ZipFile, names: set[str],
                                document: ElementTree.Element) -> set[str]:
    references = document.findall(f".//{W}headerReference") + document.findall(f".//{W}footerReference")
    if not references:
        return set()
    rels_name = "word/_rels/document.xml.rels"
    if rels_name not in names:
        raise KeyError(rels_name)
    rels = ElementTree.fromstring(archive.read(rels_name))
    by_id = {
        item.get("Id"): item
        for item in rels.findall(f"{{{PACKAGE_RELS_NS}}}Relationship")
        if item.get("Id")
    }
    parts: set[str] = set()
    for reference in references:
        relationship = by_id.get(reference.get(f"{{{OFFICE_RELS_NS}}}id"))
        if relationship is None or relationship.get("TargetMode") == "External":
            raise KeyError("active story relationship")
        target = posixpath.normpath(posixpath.join("word", relationship.get("Target") or ""))
        if not target.startswith("word/") or target not in names:
            raise KeyError(target)
        parts.add(target)
    return parts


def _sensitive_part_text(root: ElementTree.Element, *, include_attributes: bool) -> str:
    values = [
        node.text or ""
        for tag in (f"{W}t", f"{W}instrText", f"{W}delText")
        for node in root.iter(tag)
    ]
    if not values:
        values.extend(text for text in root.itertext() if text)
    if include_attributes:
        values.extend(value for node in root.iter() for value in node.attrib.values())
    return "\n".join(values)


def _inspect_docx(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not path.is_file():
        return None, [_error("docx_missing", "$.docx_filename", "the DOCX is required")]
    try:
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            document_xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(document_xml)
            sensitive_part_names = {"word/document.xml"}
            sensitive_part_names.update(_active_header_footer_parts(archive, names, root))
            sensitive_part_names.update(
                name for name in names
                if name in {"word/footnotes.xml", "word/endnotes.xml"}
                or name.startswith("word/comments") and name.endswith(".xml")
                or name in {"docProps/core.xml", "docProps/custom.xml", "docProps/app.xml"}
                or name.endswith(".rels")
            )
            sensitive_parts: dict[str, str] = {}
            for part_name in sorted(sensitive_part_names):
                part_root = root if part_name == "word/document.xml" else ElementTree.fromstring(archive.read(part_name))
                sensitive_parts[part_name] = _sensitive_part_text(
                    part_root,
                    include_attributes=True,
                )
    except (OSError, KeyError, BadZipFile, ElementTree.ParseError):
        return None, [_error("docx_unreadable", "$.docx_filename", "the DOCX package is unreadable")]

    body = root.find(f"{W}body")
    if body is None:
        return None, [_error("docx_unreadable", "$.docx_filename", "word/document.xml has no body")]
    headings: list[str] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for child in body:
        text = _element_text(child)
        if child.tag == f"{W}p":
            style = child.find(f"./{W}pPr/{W}pStyle")
            style_name = style.get(f"{W}val", "") if style is not None else ""
            if style_name.replace(" ", "").lower() == "heading1":
                current_section = text
                headings.append(text)
                sections.setdefault(text, [])
                continue
        if current_section is not None and text:
            sections[current_section].append(text)

    full_text = sensitive_parts["word/document.xml"]
    sdt_tags = sorted(
        tag.get(f"{W}val", "")
        for tag in root.findall(f".//{W}sdtPr/{W}tag")
        if tag.get(f"{W}val", "")
    )
    return {
        "full_text": full_text,
        "sensitive_parts": sensitive_parts,
        "sensitive_text": "\n".join(sensitive_parts.values()),
        "headings": headings,
        "sections": {key: "\n".join(value) for key, value in sections.items()},
        "sdt_tags": sdt_tags,
    }, []


def _load_json_source(path: Path, *, kind: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not path.is_file():
        return None, [_error("source_missing", "$.source_filename", f"the {kind} source is required")]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, [_error("source_unreadable", "$.source_filename", f"the {kind} source is unreadable")]
    if not isinstance(value, dict):
        return None, [_error("source_invalid", "$.source_filename", f"the {kind} source must be an object")]
    return value, []


def _expected_report_status(model: dict[str, Any]) -> str | None:
    status = model.get("matter_status")
    if status == "passed":
        return "最终版"
    if status == "passed_with_limitations":
        return "最终版（附保留事项）"
    if status == "blocked" and model.get("visible_status") in {
        "草稿——律师确认未完成", "暂不能形成最终版"
    }:
        return model["visible_status"]
    return None


def _sensitive_scan_errors(inspected: dict[str, Any], *, authorized_ids: set[str],
                           forbidden_terms: list[str], allow_document_placeholders: bool) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    sensitive_text = inspected["sensitive_text"]
    if re.search(r"(?:/" + "Users/" + r"|/home/|[A-Za-z]:\\)", sensitive_text):
        errors.append(_error("absolute_path_visible", "$.structural_checks", "a sensitive DOCX part contains an absolute path"))
    placeholder_text = "\n".join(
        text for name, text in inspected["sensitive_parts"].items()
        if not allow_document_placeholders or name != "word/document.xml"
    )
    if any(token in placeholder_text for token in PLACEHOLDERS):
        errors.append(_error("placeholder_visible", "$.structural_checks", "a sensitive DOCX part contains a placeholder"))
    if any(term in sensitive_text for term in forbidden_terms):
        errors.append(_error("forbidden_term_visible", "$.forbidden_terms", "a configured forbidden term appears in a sensitive DOCX part"))
    visible_ids = set(VISIBLE_ID_PATTERN.findall(sensitive_text))
    if visible_ids - authorized_ids:
        errors.append(_error("unauthorized_visible_id", "$.expected_id_sets", "a sensitive DOCX part contains an unauthorized ID"))
    return errors


def _report_evidence(model: dict[str, Any], inspected: dict[str, Any],
                     forbidden_terms: list[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    if model.get("model_type") != "legal_review_report_model":
        errors.append(_error("source_invalid", "$.source_filename", "a legal review report model is required"))
    if model.get("report_model_sha256") != report_model_content_sha256(model):
        errors.append(_error("source_hash_mismatch", "$.source_sha256", "report model content hash is invalid"))
    expected_status = _expected_report_status(model)
    if expected_status is None or model.get("visible_status") != expected_status:
        errors.append(_error("source_status_invalid", "$.visible_status", "report model status is inconsistent"))

    headings = set(inspected["headings"])
    for heading in REPORT_REQUIRED_SECTIONS:
        if heading not in headings:
            errors.append(_error("required_section_missing", f"$.required_sections.{heading}", "required report section is missing"))

    full_text = inspected["full_text"]
    if expected_status is not None:
        execution_summary = inspected["sections"].get("执行摘要", "")
        visible_statuses = re.findall(r"文档状态：([^。\n]+)", execution_summary)
        if visible_statuses != [expected_status]:
            errors.append(_error("visible_status_mismatch", "$.visible_status", "visible document status does not exactly match the report model"))

    required_ids = model.get("required_section_ids")
    expected_id_sets: dict[str, list[str]] = {}
    if not isinstance(required_ids, dict):
        errors.append(_error("source_invalid", "$.expected_id_sets", "report model required_section_ids is missing"))
        required_ids = {}
    for heading, key in REPORT_SECTION_KEYS.items():
        expected = required_ids.get(key)
        if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
            errors.append(_error("source_invalid", f"$.expected_id_sets.{key}", "expected section IDs must be an array of strings"))
            expected = []
        expected_id_sets[key] = sorted(set(expected))
        actual = sorted(set(VISIBLE_ID_PATTERN.findall(inspected["sections"].get(heading, ""))))
        if actual != expected_id_sets[key]:
            errors.append(_error("section_id_set_mismatch", f"$.expected_id_sets.{key}", f"{heading} IDs do not match the report model"))

    anti_leak = model.get("anti_leak", {}).get("client_report", {})
    excluded = set(anti_leak.get("conclusion_excluded_ids", []))
    allowed_pending = set(anti_leak.get("allowed_pending_ids", []))
    pending = set(expected_id_sets.get("client_pending", [])) | set(expected_id_sets.get("legal_pending", []))
    if pending != allowed_pending or not pending.issubset(excluded):
        errors.append(_error("pending_anti_leak_mismatch", "$.allowed_pending_ids", "pending IDs are not explicitly allowed and conclusion-excluded"))
    conclusion_headings = (
        "执行摘要", "已确认事实基础", "已批准法律与处理分析", "修改建议及同步修改"
    )
    conclusion_ids = set().union(*(
        set(VISIBLE_ID_PATTERN.findall(inspected["sections"].get(heading, "")))
        for heading in conclusion_headings
    ))
    if allowed_pending & conclusion_ids:
        errors.append(_error("pending_id_in_conclusion", "$.allowed_pending_ids", "an allowed pending ID appears in an approved conclusion section"))

    authorized_ids = set().union(*(set(value) for value in expected_id_sets.values())) if expected_id_sets else set()
    errors.extend(_sensitive_scan_errors(
        inspected, authorized_ids=authorized_ids, forbidden_terms=forbidden_terms,
        allow_document_placeholders=False,
    ))

    return {
        "required_sections": REPORT_REQUIRED_SECTIONS,
        "visible_status": expected_status,
        "expected_id_sets": expected_id_sets,
        "sdt_tags": [],
        "structural_checks": {
            "no_sensitive_part_leaks": not any(item["code"] in {
                "absolute_path_visible", "placeholder_visible", "forbidden_term_visible",
                "unauthorized_visible_id",
            } for item in errors),
            "required_sections": not any(item["code"] == "required_section_missing" for item in errors),
            "section_id_sets": not any(item["code"] == "section_id_set_mismatch" for item in errors),
            "visible_status": not any(item["code"] == "visible_status_mismatch" for item in errors),
        },
    }, errors


def _confirmation_evidence(pack: dict[str, Any], inspected: dict[str, Any],
                           docx_sha256: str, forbidden_terms: list[str]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    if pack.get("generated_form_sha256") != docx_sha256:
        errors.append(_error("generated_form_hash_mismatch", "$.docx_sha256", "DOCX hash does not match the pack manifest"))
    manifest = pack.get("sdt_manifest")
    if not isinstance(manifest, list) or any(not isinstance(item, dict) for item in manifest):
        errors.append(_error("sdt_manifest_invalid", "$.sdt_tags", "pack SDT manifest must be an array of objects"))
        manifest = []
    if pack.get("sdt_manifest_sha256") != canonical_json_sha256(manifest):
        errors.append(_error("source_hash_mismatch", "$.source_sha256", "pack SDT manifest hash is invalid"))
    expected_tags = sorted(
        item.get("tag") for item in manifest if isinstance(item.get("tag"), str) and item.get("tag")
    )
    actual_tags = inspected["sdt_tags"]
    if expected_tags != actual_tags:
        errors.append(_error("sdt_tag_set_mismatch", "$.sdt_tags", "DOCX SDT tags do not match the pack manifest"))
    headings = set(inspected["headings"])
    for heading in CONFIRMATION_REQUIRED_SECTIONS:
        if heading not in headings:
            errors.append(_error("required_section_missing", f"$.required_sections.{heading}", "required confirmation section is missing"))
    authorized_ids = {
        component
        for tag in expected_tags
        for component in tag.split("/")
        if VISIBLE_ID_PATTERN.fullmatch(component)
    }
    errors.extend(_sensitive_scan_errors(
        inspected, authorized_ids=authorized_ids, forbidden_terms=forbidden_terms,
        allow_document_placeholders=True,
    ))
    return {
        "required_sections": CONFIRMATION_REQUIRED_SECTIONS,
        "visible_status": None,
        "expected_id_sets": {},
        "sdt_tags": actual_tags,
        "structural_checks": {
            "required_sections": not any(item["code"] == "required_section_missing" for item in errors),
            "sdt_tag_set": not any(item["code"] == "sdt_tag_set_mismatch" for item in errors),
            "no_sensitive_part_leaks": not any(item["code"] in {
                "absolute_path_visible", "placeholder_visible", "forbidden_term_visible",
                "unauthorized_visible_id",
            } for item in errors),
        },
    }, errors


def _derive_evidence(*, docx_path: Path, report_model_path: Path | None,
                     pack_manifest_path: Path | None,
                     approved_content_path: Path | None,
                     forbidden_terms: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    if (report_model_path is None) == (pack_manifest_path is None):
        return None, None, [_error("qa_source_required", "$.source_filename", "provide exactly one report model or pack manifest")]
    inspected, errors = _inspect_docx(docx_path)
    if errors:
        return None, None, errors
    assert inspected is not None
    source_path = Path(report_model_path or pack_manifest_path)  # type: ignore[arg-type]
    kind = "report_model" if report_model_path is not None else "confirmation_pack_manifest"
    source, source_errors = _load_json_source(source_path, kind=kind)
    if source_errors:
        return None, None, source_errors
    assert source is not None
    if kind == "report_model":
        if approved_content_path is None:
            return None, None, [_error(
                "approved_content_required", "$.approved_content_filename",
                "report QA requires the approved-content package",
            )]
        approved_path = Path(approved_content_path)
        approved, approved_errors = _load_json_source(approved_path, kind="approved_content")
        if approved_errors:
            return None, None, approved_errors
        assert approved is not None
        try:
            validate_report_model_binding(source, approved)
        except ValueError:
            return None, None, [_error(
                "report_model_approved_content_mismatch", "$.source_filename",
                "report model is not the deterministic projection of approved content",
            )]
        evidence, evidence_errors = _report_evidence(source, inspected, forbidden_terms)
    else:
        evidence, evidence_errors = _confirmation_evidence(
            source, inspected, _sha256(docx_path), forbidden_terms
        )
    metadata = {
        "source_kind": kind,
        "source_filename": source_path.name,
        "source_sha256": _sha256(source_path),
        "approved_content_filename": approved_path.name if kind == "report_model" else None,
        "approved_content_sha256": _sha256(approved_path) if kind == "report_model" else None,
    }
    return metadata, evidence, evidence_errors


def build_qa_record(*, docx_path: Path, render_dir: Path, renderer: str,
                    inspected_pages: list[int], limitations: list[str], inspector: str,
                    report_model_path: Path | None = None,
                    pack_manifest_path: Path | None = None,
                    approved_content_path: Path | None = None,
                    forbidden_terms: list[str] | None = None) -> dict[str, Any]:
    docx_path = Path(docx_path)
    render_dir = Path(render_dir)
    metadata, evidence, errors = _derive_evidence(
        docx_path=docx_path,
        report_model_path=Path(report_model_path) if report_model_path is not None else None,
        pack_manifest_path=Path(pack_manifest_path) if pack_manifest_path is not None else None,
        approved_content_path=Path(approved_content_path) if approved_content_path is not None else None,
        forbidden_terms=sorted(set(forbidden_terms or [])),
    )
    if errors:
        raise ValueError("word_qa_evidence_invalid:" + ",".join(sorted({item["code"] for item in errors})))
    assert metadata is not None and evidence is not None
    pages = _page_files(render_dir)
    inspected_page_set = set(inspected_pages)
    return {
        "qa_schema_version": "2.0",
        "artifact_type": "word_render_qa",
        "docx_filename": docx_path.name,
        "docx_sha256": _sha256(docx_path),
        **metadata,
        "renderer": renderer,
        "page_count": len(pages),
        "pages": [
            {
                "page": number,
                "filename": path.name,
                "png_sha256": _sha256(path),
                "inspected": number in inspected_page_set,
            }
            for number, path in pages
        ],
        "required_sections": evidence["required_sections"],
        "visible_status": evidence["visible_status"],
        "expected_id_sets": evidence["expected_id_sets"],
        "sdt_tags": evidence["sdt_tags"],
        "forbidden_terms": sorted(set(forbidden_terms or [])),
        "structural_checks": evidence["structural_checks"],
        "limitations": [str(item) for item in limitations],
        "inspector": inspector,
    }


def validate_qa_record(record: Any, docx_path: Path, render_dir: Path, *,
                       report_model_path: Path | None = None,
                       pack_manifest_path: Path | None = None,
                       approved_content_path: Path | None = None,
                       forbidden_terms: list[str] | None = None) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(record, dict):
        return [_error("qa_record_required", "$", "QA record must be an object")]
    required = {
        "qa_schema_version", "artifact_type", "docx_filename", "docx_sha256",
        "source_kind", "source_filename", "source_sha256", "approved_content_filename",
        "approved_content_sha256", "renderer", "page_count",
        "pages", "required_sections", "visible_status", "expected_id_sets", "sdt_tags", "forbidden_terms",
        "structural_checks", "limitations", "inspector",
    }
    for field in sorted(required - set(record)):
        errors.append(_error("missing_qa_field", f"$.{field}", "required QA field is missing"))

    docx_path = Path(docx_path)
    render_dir = Path(render_dir)
    metadata, evidence, evidence_errors = _derive_evidence(
        docx_path=docx_path,
        report_model_path=Path(report_model_path) if report_model_path is not None else None,
        pack_manifest_path=Path(pack_manifest_path) if pack_manifest_path is not None else None,
        approved_content_path=Path(approved_content_path) if approved_content_path is not None else None,
        forbidden_terms=sorted(set(forbidden_terms or [])),
    )
    errors.extend(evidence_errors)
    if docx_path.is_file() and record.get("docx_sha256") != _sha256(docx_path):
        errors.append(_error("stale_docx_hash", "$.docx_sha256", "QA record does not match the DOCX"))
    if metadata is not None:
        for field, expected in metadata.items():
            if record.get(field) != expected:
                errors.append(_error("stale_source_evidence", f"$.{field}", "QA source evidence is stale"))
    if evidence is not None:
        for field in ("required_sections", "visible_status", "expected_id_sets", "sdt_tags"):
            if record.get(field) != evidence[field]:
                errors.append(_error("stale_structure_evidence", f"$.{field}", "recorded structure evidence is stale"))
    if record.get("forbidden_terms") != sorted(set(forbidden_terms or [])):
        errors.append(_error("stale_forbidden_terms", "$.forbidden_terms", "recorded forbidden-term configuration is stale"))

    pages = _page_files(render_dir)
    page_numbers = [number for number, _ in pages]
    if not pages:
        errors.append(_error("render_pages_missing", "$.pages", "rendered page PNGs are required"))
    elif page_numbers != list(range(1, len(pages) + 1)):
        errors.append(_error("render_page_sequence_invalid", "$.pages", "rendered pages must be consecutively numbered from one"))
    if record.get("page_count") != len(pages):
        errors.append(_error("page_count_mismatch", "$.page_count", "page count does not match rendered PNGs"))
    record_pages = record.get("pages") if isinstance(record.get("pages"), list) else []
    if [item.get("page") for item in record_pages if isinstance(item, dict)] != page_numbers:
        errors.append(_error("page_manifest_mismatch", "$.pages", "page manifest must match numbered PNGs"))
    page_paths = {number: path for number, path in pages}
    for index, item in enumerate(record_pages):
        if not isinstance(item, dict):
            errors.append(_error("invalid_page_record", f"$.pages[{index}]", "page record must be an object"))
            continue
        number = item.get("page")
        path = page_paths.get(number)
        if item.get("inspected") is not True:
            errors.append(_error("uninspected_page", f"$.pages[{index}].inspected", "every page must be inspected"))
        if path is not None:
            if item.get("filename") != path.name:
                errors.append(_error("page_filename_mismatch", f"$.pages[{index}].filename", "page filename is stale"))
            if item.get("png_sha256") != _sha256(path):
                errors.append(_error("stale_page_hash", f"$.pages[{index}].png_sha256", "page image hash is stale"))

    checks = record.get("structural_checks")
    if not isinstance(checks, dict) or not checks or any(value is not True for value in checks.values()):
        errors.append(_error("structure_check_failed", "$.structural_checks", "all recorded structural checks must pass"))
    if not isinstance(record.get("renderer"), str) or not record.get("renderer", "").strip():
        errors.append(_error("renderer_required", "$.renderer", "renderer must be recorded"))
    if not isinstance(record.get("limitations"), list):
        errors.append(_error("limitations_required", "$.limitations", "limitations must be an array"))
    if not isinstance(record.get("inspector"), str) or not record.get("inspector", "").strip():
        errors.append(_error("inspector_required", "$.inspector", "inspector must be recorded"))

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for error in errors:
        identity = (error["code"], error["path"], error["message"])
        if identity not in seen:
            seen.add(identity)
            deduped.append(error)
    return deduped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a fail-closed Word render-QA JSON record.")
    parser.add_argument("--qa", required=True, type=Path)
    parser.add_argument("--docx", required=True, type=Path)
    parser.add_argument("--render-dir", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report-model", type=Path)
    source.add_argument("--pack-manifest", type=Path)
    parser.add_argument("--approved-content", type=Path)
    parser.add_argument("--forbidden-term", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        record = json.loads(args.qa.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        errors = [_error("qa_record_unreadable", args.qa.name, "QA record is unreadable")]
    else:
        errors = validate_qa_record(
            record, args.docx, args.render_dir,
            report_model_path=args.report_model,
            pack_manifest_path=args.pack_manifest,
            approved_content_path=args.approved_content,
            forbidden_terms=args.forbidden_term,
        )
    result = {"valid": not errors, "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif errors:
        for error in errors:
            print(f"{error['code']}: {error['path']}: {error['message']}", file=sys.stderr)
    else:
        print("word QA valid")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
