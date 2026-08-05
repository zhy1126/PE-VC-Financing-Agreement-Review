"""Shared bilingual schemas for VC/PE review deliverables."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from pathlib import Path


ISSUE_FIELDS = {
    "number": ["No", "Issue ID", "编号", "问题编号"],
    "file": ["File", "文件"],
    "clause": ["Clause", "条款"],
    "location": ["Agreement Location", "File/Clause", "Location", "协议位置", "文件/条款", "位置"],
    "current_text": ["Current Text", "Current Text Summary", "Anchor Text", "当前文本", "当前文本摘要", "锚定文本"],
    "issue": ["Issue", "问题"],
    "position": ["Our Position", "Position", "我方立场"],
    "issue_type": ["Issue Type", "问题类型"],
    "market": ["Market Context", "Market Data", "Market", "市场数据", "市场基准", "市场背景"],
    "legal_basis": ["Legal Basis", "法律依据", "法律/实务依据"],
    "authority_status": [
        "Authority / Verification Status",
        "Authority Status",
        "Verification Status",
        "事实/法律依据核验状态",
        "法源/核验状态",
        "核验状态",
    ],
    "risk": ["Risk", "Risk Level", "风险", "风险等级"],
    "proposed": ["Proposed Revised Wording", "Proposed Revision", "建议修改", "修改建议"],
    "alternative": ["Alternative Wording", "Alternative", "替代方案", "备选文本"],
    "fallback": ["Fallback", "Fallback Plan", "可接受Fallback", "Fallback方案", "可接受方案"],
    "needs_client_input": ["Needs Client Input", "需客户确认", "客户确认"],
    "delivery_mode": ["Delivery Mode", "交付方式"],
    "major": ["Major", "Is Major", "Major Issue", "是否重大", "重大事项"],
}

ISSUE_HEADERS = {
    "en": [
        "No",
        "File",
        "Clause",
        "Current Text",
        "Issue",
        "Our Position",
        "Issue Type",
        "Market Context",
        "Legal Basis",
        "Authority / Verification Status",
        "Risk",
        "Proposed Revised Wording",
        "Alternative Wording",
        "Fallback",
        "Needs Client Input",
        "Delivery Mode",
        "Major",
    ],
    "zh": [
        "编号",
        "文件",
        "条款",
        "当前文本摘要",
        "问题",
        "我方立场",
        "问题类型",
        "市场数据",
        "法律依据",
        "事实/法律依据核验状态",
        "风险等级",
        "建议修改",
        "替代方案",
        "Fallback",
        "需客户确认",
        "交付方式",
        "是否重大",
    ],
}

COMMENT_KEYS = [
    "file",
    "location",
    "anchor_text",
    "risk",
    "issue_type",
    "comment_text",
    "proposed_revised_wording",
    "fallback",
    "needs_client_input",
]

COMMENT_HEADERS = {
    "en": COMMENT_KEYS,
    "zh": ["文件", "位置", "锚定文本", "风险等级", "问题类型", "批注文本", "建议修改", "Fallback", "需客户确认"],
}

COMMENT_FIELDS = {
    "file": ["file", "文件"],
    "location": ["location", "位置"],
    "anchor_text": ["anchor text", "anchor_text", "锚定文本", "锚点文本"],
    "risk": ["risk", "风险等级", "风险"],
    "issue_type": ["issue type", "issue_type", "问题类型"],
    "comment_text": ["comment text", "comment_text", "批注文本", "批注"],
    "proposed_revised_wording": ["proposed revised wording", "proposed_revised_wording", "建议修改", "修改建议"],
    "fallback": ["fallback", "Fallback", "可接受方案"],
    "needs_client_input": ["needs client input", "needs_client_input", "需客户确认", "客户确认"],
}

MAJOR_KEYS = ["issue_id", "major_issue", "position", "counterparty_status", "next_step"]

MAJOR_FIELDS = {
    "issue_id": ["Issue ID", "问题编号", "争议编号"],
    "major_issue": ["Major Issue / Clause", "Major Issue", "重大问题/条款", "主要争议/条款", "主要争议事项"],
    "position": ["Our Position", "我方立场"],
    "counterparty_status": ["Counterparty Position / Status", "对方立场/状态", "对方意见/状态"],
    "next_step": ["Next Step / Fallback", "下一步/Fallback", "下一步/可接受方案"],
}

MAJOR_HEADERS = {
    "en": ["Issue ID", "Major Issue / Clause", "Our Position", "Counterparty Position / Status", "Next Step / Fallback"],
    "zh": ["问题编号", "主要争议/条款", "我方立场", "对方立场/状态", "下一步/Fallback"],
}

RESPONSE_KEYS = [
    "issue_id",
    "original_concern",
    "revision_evidence",
    "response_status",
    "residual_or_new_risk",
    "synchronized_clauses",
    "next_step",
]

RESPONSE_FIELDS = {
    "issue_id": ["Issue ID", "Issue No.", "issue_id", "问题编号", "争议编号"],
    "original_concern": [
        "Original Concern",
        "Original Issue / Concern",
        "original_concern",
        "原始关切",
        "原始问题",
        "原问题",
    ],
    "revision_evidence": [
        "Revision Evidence",
        "Evidence of Revision",
        "revision_evidence",
        "修订证据",
        "修改证据",
        "回应证据",
    ],
    "response_status": ["Response Status", "response_status", "回应状态", "响应状态"],
    "residual_or_new_risk": [
        "Residual / New Risk",
        "Residual or New Risk",
        "residual_or_new_risk",
        "剩余/新增风险",
        "剩余或新增风险",
        "残余/新增风险",
    ],
    "synchronized_clauses": [
        "Synchronized Clauses",
        "Linked Clauses",
        "synchronized_clauses",
        "同步条款",
        "关联条款",
        "联动条款",
    ],
    "next_step": ["Next Step", "next_step", "下一步"],
}

RESPONSE_HEADERS = {
    "en": [
        "Issue ID",
        "Original Concern",
        "Revision Evidence",
        "Response Status",
        "Residual / New Risk",
        "Synchronized Clauses",
        "Next Step",
    ],
    "zh": ["问题编号", "原始关切", "修订证据", "回应状态", "剩余/新增风险", "同步条款", "下一步"],
}

STATUS_LABELS = {
    "open": {"en": "Open", "zh": "待处理"},
    "partially_accepted": {"en": "Partially Accepted", "zh": "部分接受"},
    "accepted": {"en": "Accepted", "zh": "已接受"},
    "rejected": {"en": "Rejected", "zh": "已拒绝"},
    "new_counterparty_issue": {"en": "New Counterparty Issue", "zh": "对方新增问题"},
    "reopened": {"en": "Reopened", "zh": "重新开启"},
    "deferred": {"en": "Deferred", "zh": "暂缓"},
    "closed": {"en": "Closed", "zh": "已关闭"},
}

# Response grades measure how a revision addresses a concern. They are
# deliberately separate from STATUS_LABELS, which tracks negotiation state.
RESPONSE_STATUS_LABELS = {
    "complete": {"en": "Complete", "zh": "完全回应"},
    "substantial": {"en": "Substantial", "zh": "实质回应"},
    "partial": {"en": "Partial", "zh": "部分回应"},
    "alternative_solution": {"en": "Alternative Solution", "zh": "替代方案回应"},
    "unaddressed": {"en": "Unaddressed", "zh": "未回应"},
    "reopened": {"en": "Reopened", "zh": "重新开启"},
    "new_issue": {"en": "New Issue", "zh": "新增问题"},
}

RISK_LABELS = {
    "high": {"high", "高", "高风险"},
    "medium": {"medium", "中", "中风险"},
    "low": {"low", "低", "低风险"},
}

TRUE_VALUES = {"1", "true", "yes", "y", "是", "重大", "需要"}


def validate_csv_template_structure(path: Path, expected: list[str]) -> tuple[bool, str]:
    """Strictly validate a BOM-tolerant CSV template header and every row width."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle, strict=True))
    except (OSError, UnicodeError, csv.Error) as exc:
        return False, f"could not read: {type(exc).__name__}: {exc}"
    actual = rows[0] if rows else []
    if actual != expected:
        return False, "header does not match shared schema"
    for row_number, row in enumerate(rows[1:], start=1):
        if len(row) != len(expected):
            return False, f"row {row_number} has {len(row)} cells; expected {len(expected)}"
    return True, "ok"


def norm_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("_", " "))


def value_for(row: Mapping[object, object], semantic: str, *, major: bool = False) -> str:
    aliases = MAJOR_FIELDS[semantic] if major else ISSUE_FIELDS[semantic]
    mapped = {norm_key(k): v for k, v in row.items() if k is not None}
    for alias in aliases:
        value = mapped.get(norm_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def comment_value_for(row: Mapping[object, object], semantic: str) -> str:
    aliases = COMMENT_FIELDS[semantic]
    mapped = {norm_key(k): v for k, v in row.items() if k is not None}
    for alias in aliases:
        value = mapped.get(norm_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def response_value_for(row: Mapping[object, object], semantic: str) -> str:
    aliases = RESPONSE_FIELDS[semantic]
    mapped = {norm_key(k): v for k, v in row.items() if k is not None}
    for alias in aliases:
        value = mapped.get(norm_key(alias))
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def response_semantic_for_header(header: object) -> str | None:
    normalized = norm_key(header)
    matches = [
        semantic
        for semantic, aliases in RESPONSE_FIELDS.items()
        if normalized in {norm_key(alias) for alias in aliases}
    ]
    return matches[0] if len(matches) == 1 else None


def validate_response_schema_alignment() -> None:
    for language, headers in RESPONSE_HEADERS.items():
        if len(headers) != len(RESPONSE_KEYS):
            raise ValueError(f"Response Matrix {language} header alignment has the wrong column count")
        for expected, header in zip(RESPONSE_KEYS, headers):
            actual = response_semantic_for_header(header)
            if actual != expected:
                raise ValueError(
                    f"Response Matrix {language} header alignment mismatch: "
                    f"{header!r} resolves to {actual!r}, expected {expected!r}"
                )


validate_response_schema_alignment()


def has_cjk(value: object) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def detect_language(headers: Iterable[object], rows: Iterable[Mapping[object, object]] = ()) -> str:
    header_list = [str(h or "") for h in headers]
    if any(has_cjk(header) for header in header_list):
        return "zh"
    known_english_headers = {
        norm_key(header)
        for header in [
            *ISSUE_HEADERS["en"],
            *COMMENT_HEADERS["en"],
            *MAJOR_HEADERS["en"],
            *RESPONSE_HEADERS["en"],
        ]
    }
    if any(norm_key(header) in known_english_headers for header in header_list):
        return "en"
    for row in rows:
        if any(has_cjk(value) for value in row.values()):
            return "zh"
    return "en"


def normalize_language(requested: str, headers: Iterable[object], rows: Iterable[Mapping[object, object]] = ()) -> str:
    if requested in {"zh", "en"}:
        return requested
    return detect_language(headers, rows)


def truthy(value: object) -> bool:
    return norm_key(value) in TRUE_VALUES


def canonical_risk(value: object) -> str | None:
    normalized = norm_key(value)
    for key, labels in RISK_LABELS.items():
        if normalized in labels:
            return key
    return None


def statuses_in_text(value: object) -> list[str]:
    text = str(value or "").strip().lower()
    matches: list[tuple[int, str]] = []
    for canonical, labels in STATUS_LABELS.items():
        for label in labels.values():
            label_lower = label.lower()
            if has_cjk(label):
                found = label_lower in text
            else:
                found = bool(re.search(rf"(?<![a-z]){re.escape(label_lower)}(?![a-z])", text))
            if found:
                matches.append((len(label_lower), canonical))
                break
    matches.sort(reverse=True)
    selected: list[str] = []
    for _, canonical in matches:
        if canonical not in selected:
            selected.append(canonical)
    if "partially_accepted" in selected and "accepted" in selected:
        selected.remove("accepted")
    return selected


def localized_status(canonical: str, language: str) -> str:
    return STATUS_LABELS[canonical][language]


def canonical_response_status(value: object) -> str | None:
    normalized = norm_key(value)
    for canonical, labels in RESPONSE_STATUS_LABELS.items():
        supported = {norm_key(canonical), *(norm_key(label) for label in labels.values())}
        if normalized in supported:
            return canonical
    return None


def localized_response_status(canonical: str, language: str) -> str:
    return RESPONSE_STATUS_LABELS[canonical][language]


def canonical_major_row(row: Mapping[object, object]) -> dict[str, str]:
    return {key: value_for(row, key, major=True) for key in MAJOR_KEYS}


def localized_major_row(row: Mapping[str, str], language: str) -> dict[str, str]:
    if len(MAJOR_KEYS) != len(MAJOR_HEADERS[language]):
        raise ValueError("Major Issue List schema keys and headers must have equal lengths")
    return {header: row.get(key, "") for key, header in zip(MAJOR_KEYS, MAJOR_HEADERS[language])}


def canonical_response_row(row: Mapping[object, object]) -> dict[str, str]:
    return {key: response_value_for(row, key) for key in RESPONSE_KEYS}


def localized_response_row(row: Mapping[str, str], language: str) -> dict[str, str]:
    if len(RESPONSE_KEYS) != len(RESPONSE_HEADERS[language]):
        raise ValueError("Response Matrix schema keys and headers must have equal lengths")
    return {header: row.get(key, "") for key, header in zip(RESPONSE_KEYS, RESPONSE_HEADERS[language])}
