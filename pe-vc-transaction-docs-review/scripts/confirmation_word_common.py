"""Deterministic OOXML helpers for the lawyer-confirmation Word gate."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import posixpath
import re
import tempfile
from typing import Any
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from lxml import etree

from lawyer_confirmation_schema import canonical_json_sha256


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
VT = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
PACKAGE_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_PART_BYTES = 10 * 1024 * 1024
MAX_DOCX_MEMBERS = 2048
MAX_COMPRESSION_RATIO = 200
MAX_MEMBER_NAME_LENGTH = 240
PLACEHOLDERS = {"（请填写）", "（可填写）", "（如有，请填写）", "（未填写）"}
SAFE_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


class DocxInspectionError(Exception):
    """A stable fail-closed DOCX inspection error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def safe_basename(value: str) -> bool:
    return bool(SAFE_BASENAME.fullmatch(value)) and value not in {".", ".."}


def _parse_xml(data: bytes, part: str) -> etree._Element:
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)
        return etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise DocxInspectionError("malformed_docx", f"invalid XML in {part}") from exc


def _preflight_zip_infos(infos: list[Any]) -> None:
    if len(infos) > MAX_DOCX_MEMBERS:
        raise DocxInspectionError("docx_member_count_exceeded", "DOCX contains too many package members")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise DocxInspectionError("duplicate_docx_member", "DOCX contains duplicate package members")
    for info in infos:
        name = info.filename
        components = name.rstrip("/").split("/")
        if (
            not name
            or len(name) > MAX_MEMBER_NAME_LENGTH
            or "\x00" in name
            or "\\" in name
            or name.startswith("/")
            or any(component in {"", ".", ".."} for component in components)
            or (components and ":" in components[0])
        ):
            raise DocxInspectionError("unsafe_docx_member_name", "DOCX contains an unsafe package member name")
        if info.flag_bits & 0x1:
            raise DocxInspectionError("encrypted_docx_member", "encrypted DOCX package members are not supported")
        if info.file_size > 0 and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
            raise DocxInspectionError("docx_compression_ratio_exceeded", "DOCX package member compression ratio exceeds the safety limit")


def _text_without_sdts(paragraph: etree._Element) -> str:
    fragments: list[str] = []
    for text in paragraph.xpath(".//w:t", namespaces=NS):
        if text.xpath("ancestor::w:sdt", namespaces=NS):
            continue
        fragments.append(text.text or "")
    return normalize_whitespace("".join(fragments))


def _table_identity(table: etree._Element, fallback_index: int) -> str:
    first_cells = table.xpath("w:tr[1]/w:tc[1]", namespaces=NS)
    visible = _all_text(first_cells[0]) if first_cells else ""
    for prefix in ("Issue", "Batch"):
        match = re.search(rf"(?:^|\s){prefix} ID[：:]\s*([^\s｜]+)", visible)
        if match:
            return f"{prefix.lower()}:{match.group(1)}"
    confirmation = re.search(r"Confirmation ID[：:]\s*(OVERALL|LAWYER-NEW)", visible)
    if confirmation:
        return f"reserved:{confirmation.group(1)}"
    return f"anonymous:{fallback_index:04d}"


def _immutable_units(parts: dict[str, etree._Element]) -> list[dict[str, str]]:
    """Bind immutable text to its part, card, row role, and cell position.

    Units are sorted by a stable key so entire identified cards may move without
    changing the digest.  Text cannot, however, be reassigned to another issue
    or another row role without changing the digest.
    """

    units: list[dict[str, str]] = []
    for part_name in sorted(parts):
        root = parts[part_name]
        outside_index = 0
        for paragraph in root.xpath(".//w:p[not(ancestor::w:tbl)]", namespaces=NS):
            value = _text_without_sdts(paragraph)
            if value:
                units.append({"key": f"{part_name}|paragraph:{outside_index:04d}", "value": value})
                outside_index += 1
        for table_index, table in enumerate(root.xpath(".//w:tbl[not(ancestor::w:tbl)]", namespaces=NS)):
            identity = _table_identity(table, table_index)
            role_counts: Counter[str] = Counter()
            for row_index, row in enumerate(table.xpath("w:tr", namespaces=NS)):
                cells = row.xpath("w:tc", namespaces=NS)
                role = _text_without_sdts(cells[0]) if cells else ""
                role = role or "<blank-role>"
                occurrence = role_counts[role]
                role_counts[role] += 1
                for cell_index, cell in enumerate(cells):
                    value = normalize_whitespace(
                        "".join(
                            _text_without_sdts(paragraph)
                            for paragraph in cell.xpath(".//w:p", namespaces=NS)
                        )
                    )
                    units.append(
                        {
                            "key": (
                                f"{part_name}|table:{identity}|row:{row_index:04d}|"
                                f"role:{role}|occurrence:{occurrence:03d}|cell:{cell_index:03d}"
                            ),
                            "value": value,
                        }
                    )
    return sorted(units, key=lambda item: item["key"])


def _all_text(element: etree._Element) -> str:
    return normalize_whitespace("".join(element.xpath(".//w:t/text()", namespaces=NS)))


def _visible_confirmation_id(sdt: etree._Element) -> str | None:
    rows = sdt.xpath("ancestor::w:tr[1]", namespaces=NS)
    if not rows:
        return None
    cells = rows[0].xpath("w:tc", namespaces=NS)
    if not cells:
        return None
    match = re.search(r"Confirmation ID[：:]\s*([^\s｜]+)", _all_text(cells[0]))
    return match.group(1) if match else None


def _card_issue_id(sdt: etree._Element) -> str | None:
    tables = sdt.xpath("ancestor::w:tbl[1]", namespaces=NS)
    if not tables:
        return None
    first_cells = tables[0].xpath("w:tr[1]/w:tc[1]", namespaces=NS)
    card_label = _all_text(first_cells[0]) if first_cells else ""
    match = re.search(r"(?:^|\s)Issue ID[：:]\s*([^\s｜]+)", card_label)
    if match:
        return match.group(1)
    match = re.search(r"(?:^|\s)Batch ID[：:]\s*([^\s｜]+)", card_label)
    if match:
        return match.group(1)
    visible = _visible_confirmation_id(sdt)
    return visible if visible in {"OVERALL", "LAWYER-NEW"} else None


def _response_cell_merged(sdt: etree._Element) -> bool:
    cells = sdt.xpath("ancestor::w:tc[1]", namespaces=NS)
    if not cells:
        return False
    return bool(cells[0].xpath("w:tcPr/w:gridSpan | w:tcPr/w:vMerge", namespaces=NS))


def _sdt_value(sdt: etree._Element) -> str:
    paragraphs = sdt.xpath("w:sdtContent//w:p", namespaces=NS)
    if paragraphs:
        value = "\n".join("".join(p.xpath(".//w:t/text()", namespaces=NS)) for p in paragraphs)
    else:
        value = "".join(sdt.xpath("w:sdtContent//w:t/text()", namespaces=NS))
    value = normalize_whitespace(value)
    return "" if value in PLACEHOLDERS else value


def _sdt_control_type(sdt: etree._Element) -> str:
    properties = sdt.find(f"{{{W}}}sdtPr")
    if properties is None:
        return "missing"
    recognized = {
        "text", "richText", "dropDownList", "comboBox", "date", "checkbox", "checkBox",
        "picture", "group", "docPartObj", "docPartList", "citation", "equation",
        "bibliography", "repeatingSection", "repeatingSectionItem",
    }
    found = [etree.QName(child).localname for child in properties if etree.QName(child).localname in recognized]
    if len(found) == 1:
        return found[0]
    if not found:
        return "unknown"
    return "ambiguous:" + ",".join(sorted(found))


def _active_story_parts(archive: ZipFile, names: set[str], document: etree._Element) -> tuple[dict[str, etree._Element], list[dict[str, str]]]:
    """Resolve section header/footer references through document relationships."""

    parts = {"word/document.xml": document}
    units: list[dict[str, str]] = []
    sections = document.xpath(".//w:sectPr", namespaces=NS)
    if not sections:
        return parts, units
    rels_name = "word/_rels/document.xml.rels"
    if rels_name not in names:
        raise DocxInspectionError("malformed_docx", "section stories have no document relationships part")
    rels_root = _parse_xml(archive.read(rels_name), rels_name)
    relationships = {
        node.get("Id"): node
        for node in rels_root.findall(f"{{{PACKAGE_RELS}}}Relationship")
        if node.get("Id")
    }
    inherited: dict[tuple[str, str], tuple[str, str]] = {}
    for section_index, section in enumerate(sections):
        for reference in section.xpath("w:headerReference | w:footerReference", namespaces=NS):
            kind = "header" if etree.QName(reference).localname == "headerReference" else "footer"
            variant = reference.get(f"{{{W}}}type", "default")
            relationship_id = reference.get(f"{{{OFFICE_RELS}}}id")
            relationship = relationships.get(relationship_id)
            if relationship is None or relationship.get("TargetMode") == "External":
                raise DocxInspectionError("malformed_docx", f"unresolved active {kind} relationship")
            relation_type = relationship.get("Type") or ""
            if not relation_type.endswith(f"/{kind}"):
                raise DocxInspectionError("malformed_docx", f"active {kind} relationship has the wrong type")
            target = posixpath.normpath(posixpath.join("word", relationship.get("Target") or ""))
            if not target.startswith("word/") or target not in names:
                raise DocxInspectionError("malformed_docx", f"active {kind} target is missing")
            inherited[(kind, variant)] = (relationship_id or "", target)
        for (kind, variant), (relationship_id, target) in sorted(inherited.items()):
            units.append(
                {
                    "key": f"word/document.xml|story:section:{section_index:04d}|{kind}:{variant}",
                    "value": f"{relationship_id}|{target}",
                }
            )
            if target not in parts:
                parts[target] = _parse_xml(archive.read(target), target)
    return parts, units


def document_part_sha256(path: Path) -> str:
    """Digest the generated main document part before editable responses."""

    try:
        with ZipFile(path) as archive:
            return hashlib.sha256(archive.read("word/document.xml")).hexdigest()
    except (BadZipFile, OSError, KeyError) as exc:
        raise DocxInspectionError("malformed_docx", "main document part is unreadable") from exc


def set_custom_properties(path: Path, properties: dict[str, str]) -> None:
    """Add deterministic package-level provenance properties to a DOCX."""

    custom_root = etree.Element(f"{{{CUSTOM}}}Properties", nsmap={None: CUSTOM, "vt": VT})
    for pid, name in enumerate(sorted(properties), start=2):
        prop = etree.SubElement(
            custom_root,
            f"{{{CUSTOM}}}property",
            fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}",
            pid=str(pid),
            name=name,
        )
        etree.SubElement(prop, f"{{{VT}}}lpwstr").text = properties[name]

    temporary = tempfile.NamedTemporaryFile(prefix="pevc-custom-", suffix=".docx", dir=path.parent, delete=False)
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with ZipFile(path) as source, ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as target:
            content_types = _parse_xml(source.read("[Content_Types].xml"), "[Content_Types].xml")
            overrides = content_types.findall(f"{{{CONTENT_TYPES}}}Override")
            if not any(node.get("PartName") == "/docProps/custom.xml" for node in overrides):
                etree.SubElement(
                    content_types,
                    f"{{{CONTENT_TYPES}}}Override",
                    PartName="/docProps/custom.xml",
                    ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml",
                )

            root_rels = _parse_xml(source.read("_rels/.rels"), "_rels/.rels")
            relation_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
            if not any(node.get("Type") == relation_type for node in root_rels):
                existing_ids = {node.get("Id") for node in root_rels}
                relation_id = "rIdPEVCCustomProps"
                suffix = 1
                while relation_id in existing_ids:
                    relation_id = f"rIdPEVCCustomProps{suffix}"
                    suffix += 1
                etree.SubElement(
                    root_rels,
                    f"{{{PACKAGE_RELS}}}Relationship",
                    Id=relation_id,
                    Type=relation_type,
                    Target="docProps/custom.xml",
                )

            replacements = {
                "[Content_Types].xml": etree.tostring(content_types, xml_declaration=True, encoding="UTF-8", standalone=True),
                "_rels/.rels": etree.tostring(root_rels, xml_declaration=True, encoding="UTF-8", standalone=True),
                "docProps/custom.xml": etree.tostring(custom_root, xml_declaration=True, encoding="UTF-8", standalone=True),
            }
            for info in source.infolist():
                if info.filename not in replacements:
                    target.writestr(info, source.read(info.filename))
            for name, data in replacements.items():
                target.writestr(name, data)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def inspect_docx(path: Path) -> dict[str, Any]:
    """Inspect the main Word part without trusting python-docx repair behavior."""

    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            _preflight_zip_infos(infos)
            if sum(info.file_size for info in infos) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocxInspectionError("docx_size_exceeded", "DOCX exceeds the inspection size limit")
            if any(info.file_size > MAX_PART_BYTES for info in infos):
                raise DocxInspectionError("docx_member_size_exceeded", "DOCX member exceeds the inspection size limit")
            names = {info.filename for info in infos}
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise DocxInspectionError("malformed_docx", "required DOCX parts are missing")
            document = _parse_xml(archive.read("word/document.xml"), "word/document.xml")
            parts, active_story_units = _active_story_parts(archive, names, document)
            revision_parts = {
                name: _parse_xml(archive.read(name), name)
                for name in sorted(names)
                if name.startswith("word/") and name.endswith(".xml")
            }
            custom_properties: dict[str, str] = {}
            custom_properties_linked = False
            if "docProps/custom.xml" in names:
                custom_root = _parse_xml(archive.read("docProps/custom.xml"), "docProps/custom.xml")
                for prop in custom_root.findall(f"{{{CUSTOM}}}property"):
                    name = prop.get("name")
                    if name and len(prop):
                        custom_properties[name] = normalize_whitespace("".join(prop[0].itertext()))
                content_types = _parse_xml(archive.read("[Content_Types].xml"), "[Content_Types].xml")
                typed = any(
                    node.get("PartName") == "/docProps/custom.xml"
                    and node.get("ContentType")
                    == "application/vnd.openxmlformats-officedocument.custom-properties+xml"
                    for node in content_types.findall(f"{{{CONTENT_TYPES}}}Override")
                )
                linked = False
                if "_rels/.rels" in names:
                    root_rels = _parse_xml(archive.read("_rels/.rels"), "_rels/.rels")
                    linked = any(
                        node.get("Type")
                        == "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
                        and (node.get("Target") or "").lstrip("/") == "docProps/custom.xml"
                        for node in root_rels.findall(f"{{{PACKAGE_RELS}}}Relationship")
                    )
                custom_properties_linked = typed and linked
    except (BadZipFile, OSError, KeyError) as exc:
        raise DocxInspectionError("malformed_docx", "file is not a readable DOCX package") from exc

    document = parts["word/document.xml"]
    tracked_names = {
        "ins", "del", "conflictIns", "conflictDel", "moveFrom", "moveTo",
        "cellIns", "cellDel", "cellMerge",
    }
    tracked = [
        node
        for root in revision_parts.values()
        for node in root.iter()
        if etree.QName(node).namespace == W
        and (
            etree.QName(node).localname in tracked_names
            or etree.QName(node).localname.endswith("Change")
            or (
                etree.QName(node).localname.endswith(("RangeStart", "RangeEnd"))
                and etree.QName(node).localname.startswith(("move", "customXml"))
            )
        )
    ]
    records: list[dict[str, Any]] = []
    for part_name in sorted(parts):
        for sdt in parts[part_name].xpath(".//w:sdt", namespaces=NS):
            tags = sdt.xpath("w:sdtPr/w:tag/@w:val", namespaces=NS)
            tag = tags[0] if len(tags) == 1 else ""
            components = tag.split("/") if tag else []
            batch_id, confirmation_id, field = (components + ["", "", ""])[:3]
            records.append(
                {
                    "part": part_name,
                    "tag": tag,
                    "batch_id": batch_id,
                    "confirmation_id": confirmation_id,
                    "field": field,
                    "control_type": _sdt_control_type(sdt),
                    "visible_confirmation_id": _visible_confirmation_id(sdt),
                    "card_issue_id": _card_issue_id(sdt),
                    "value": _sdt_value(sdt),
                    "merged_response_cell": _response_cell_merged(sdt),
                    "tag_component_count": len(components),
                }
            )
    units = sorted(_immutable_units(parts) + active_story_units, key=lambda item: item["key"])
    all_visible = [_text_without_sdts(p) for p in document.xpath(".//w:p", namespaces=NS)]
    matter_values = [value.split("：", 1)[1] for value in all_visible if value.startswith("事项编号：")]
    batch_values = [value.split("：", 1)[1] for value in all_visible if value.startswith("确认批次：")]
    round_values = [value.split("：", 1)[1] for value in all_visible if value.startswith("审阅轮次：")]
    return {
        "sdts": records,
        "duplicate_sdt_tags": sorted(tag for tag, count in Counter(item["tag"] for item in records).items() if count > 1),
        "tracked_changes_count": len(tracked),
        "immutable_atoms": [item["value"] for item in units],
        "immutable_units": units,
        "immutable_visible_content_sha256": canonical_json_sha256(units),
        "custom_properties": custom_properties,
        "custom_properties_linked": custom_properties_linked,
        "matter_ids": sorted(set(matter_values)),
        "confirmation_batch_ids": sorted(set(batch_values)),
        "review_rounds": sorted(set(round_values)),
    }


__all__ = [
    "DocxInspectionError",
    "canonical_json_sha256",
    "document_part_sha256",
    "inspect_docx",
    "normalize_whitespace",
    "safe_basename",
    "set_custom_properties",
    "sha256_file",
]
