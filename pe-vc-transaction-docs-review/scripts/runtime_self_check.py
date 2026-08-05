#!/usr/bin/env python3
"""Check local runtime readiness without network access or user documents."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from review_schema import RESPONSE_HEADERS, validate_csv_template_structure


ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 9)
CORE_JSON = (
    ROOT / "references" / "benchmark-data.json",
    ROOT / "references" / "legal-authorities.json",
)
CORE_RESPONSE_TEMPLATES = {
    ROOT / "assets" / "response-matrix-template.csv": RESPONSE_HEADERS["en"],
    ROOT / "assets" / "response-matrix-template-zh.csv": RESPONSE_HEADERS["zh"],
}


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def module_importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except (ImportError, OSError, RuntimeError):
        return False


def find_render_docx() -> Path | None:
    configured = os.environ.get("PEVC_RENDER_DOCX")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.append(ROOT / "scripts" / "render_docx.py")
    candidates.extend(sorted(
        (Path.home() / ".codex" / "plugins" / "cache" / "openai-primary-runtime" / "documents").glob(
            "*/skills/documents/render_docx.py"
        ),
        reverse=True,
    ))
    return next((path.resolve() for path in candidates if path.is_file()), None)


def bundled_soffice_candidate() -> Path:
    executable = Path(sys.executable)
    dependencies = executable.parents[2] if len(executable.parents) > 2 else executable.parent
    return dependencies / "bin" / "override" / "soffice"


def probe_rendering_backend() -> tuple[bool, str]:
    candidates = []
    discovered = shutil.which("soffice")
    if discovered:
        candidates.append(Path(discovered))
    candidates.append(bundled_soffice_candidate())
    seen: set[str] = set()
    for candidate in candidates:
        identity = str(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        try:
            process = subprocess.run(
                [str(candidate), "--version"],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if process.returncode == 0:
            return True, candidate.name
    return False, "unavailable"


def find_cjk_font() -> Path | None:
    configured = os.environ.get("PEVC_CJK_FONT")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ))
    return next((path.resolve() for path in candidates if path.is_file()), None)


def writable_temp_directory() -> tuple[bool, str]:
    try:
        with tempfile.TemporaryDirectory(prefix="pevc-confirmation-") as directory:
            probe = Path(directory) / "probe"
            probe.write_text("ok", encoding="utf-8")
            return probe.read_text(encoding="utf-8") == "ok", "writable"
    except (OSError, UnicodeError) as exc:
        return False, type(exc).__name__


def load_json(path: Path) -> tuple[bool, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return False, type(exc).__name__
    if not isinstance(payload, dict):
        return False, "top-level JSON value must be an object"
    return True, "ok"


def build_report(*, confirmation_word_mode: bool = False) -> dict[str, object]:
    python_ready = sys.version_info >= MIN_PYTHON
    data_checks = {}
    for path in CORE_JSON:
        ok, detail = load_json(path)
        data_checks[str(path.relative_to(ROOT))] = {"ready": ok, "detail": detail}
    for path, expected in CORE_RESPONSE_TEMPLATES.items():
        ok, detail = validate_csv_template_structure(path, expected)
        data_checks[str(path.relative_to(ROOT))] = {"ready": ok, "detail": detail}

    optional = {
        "word_comments": {
            "ready": module_available("lxml"),
            "requires": ["lxml"],
            "fallback": "produce a comment plan instead of native Word comments",
            "fallback_zh": "改为生成完整批注计划，不影响问题清单",
        },
        "blind_evaluation": {
            "ready": all(module_available(name) for name in ("docx", "lxml", "PIL")),
            "requires": ["python-docx", "lxml", "Pillow"],
            "fallback": "skip synthetic document rendering; core review remains available",
            "fallback_zh": "跳过模拟文档渲染，核心审阅仍可使用",
        },
        "macos_ocr": {
            "ready": platform.system() == "Darwin" and shutil.which("xcrun") is not None,
            "requires": ["macOS", "xcrun", "Vision framework"],
            "fallback": "request a searchable PDF, original Word file, or clearer scans",
            "fallback_zh": "请提供带文字层PDF、原始Word或更清晰扫描件",
        },
        "cross_platform_ocr": {
            "ready": bool(
                (shutil.which("ocrmypdf") and shutil.which("pdftotext"))
                or (shutil.which("tesseract") and shutil.which("pdftoppm"))
            ),
            "requires": ["OCRmyPDF + pdftotext, or Tesseract + pdftoppm"],
            "fallback": "use macOS Vision when available, or request a searchable PDF/Word source",
            "fallback_zh": "可用时改用macOS Vision，否则请提供带文字层PDF或Word",
        },
        "pdf_text": {
            "ready": bool(shutil.which("pdftotext") or module_available("pypdf") or module_available("fitz")),
            "requires": ["pdftotext, pypdf, or PyMuPDF"],
            "fallback": "provide a searchable PDF/Word source or mark the PDF as unreadable",
            "fallback_zh": "请提供带文字层PDF或Word，否则将该PDF标记为未实质审阅",
        },
    }
    confirmation_word: dict[str, object] | None = None
    if confirmation_word_mode:
        render_backend_ready, render_backend_name = probe_rendering_backend()
        cjk_font = find_cjk_font()
        temp_ready, _ = writable_temp_directory()
        fontconfig = os.environ.get("FONTCONFIG_FILE")
        fontconfig_ready = not fontconfig or Path(fontconfig).expanduser().is_file()
        confirmation_checks = {
            "python_docx": {
                "ready": module_importable("docx"),
            },
            "ooxml": {
                "ready": module_importable("lxml") or module_importable("xml.etree.ElementTree"),
            },
            "render_backend": {
                "ready": render_backend_ready,
                "backend": render_backend_name,
            },
            "cjk_font": {
                "ready": cjk_font is not None,
            },
            "font_configuration": {
                "ready": fontconfig_ready and cjk_font is not None,
            },
            "temporary_directory": {"ready": temp_ready},
        }
        confirmation_word = {
            "mode": "confirmation_word",
            "network_install_attempted": False,
            "checks": confirmation_checks,
            "ready": all(item["ready"] for item in confirmation_checks.values()),
        }
    core_ready = (
        python_ready
        and all(item["ready"] for item in data_checks.values())
        and (not confirmation_word_mode or bool(confirmation_word and confirmation_word["ready"]))
    )
    errors = []
    if not python_ready:
        errors.append("RUNTIME-001: Python 3.9 or newer is required")
    errors.extend(
        f"RUNTIME-001: {name} is not ready ({item['detail']})"
        for name, item in data_checks.items()
        if not item["ready"]
    )
    if confirmation_word and not confirmation_word["ready"]:
        errors.extend(
            f"RUNTIME-001: confirmation Word mode {name} is not ready"
            for name, item in confirmation_word["checks"].items()
            if not item["ready"]
        )
    warnings = [
        f"Optional capability unavailable: {name}; {item['fallback']}"
        for name, item in optional.items()
        if not item["ready"]
    ]
    return {
        "check": "runtime_self_check",
        "network_used": False,
        "user_documents_read": False,
        "python": {
            "ready": python_ready,
            "version": platform.python_version(),
            "minimum": ".".join(map(str, MIN_PYTHON)),
        },
        "core_data": data_checks,
        "optional_capabilities": optional,
        "confirmation_word": confirmation_word,
        "core_ready": core_ready,
        "errors": errors,
        "warnings": warnings,
    }


def print_text(report: dict[str, object], language: str) -> None:
    if language == "zh-CN":
        print(f"核心审阅能力：{'已就绪' if report['core_ready'] else '未就绪'}")
        for error in report["errors"]:
            print(f"错误：{error}", file=sys.stderr)
        for name, item in report.get("optional_capabilities", {}).items():
            if not item["ready"]:
                print(f"可选能力暂不可用：{name}；{item.get('fallback_zh', item['fallback'])}", file=sys.stderr)
        return
    print(f"Core review ready: {'yes' if report['core_ready'] else 'no'}")
    for error in report["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    for warning in report["warnings"]:
        print(f"WARNING: {warning}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--language", choices=("zh-CN", "en"), default="zh-CN")
    parser.add_argument(
        "--confirmation-word-mode", action="store_true",
        help="require local python-docx, OOXML, render_docx.py, CJK font and temp-directory readiness",
    )
    args = parser.parse_args()
    try:
        report = build_report(confirmation_word_mode=args.confirmation_word_mode)
    except Exception as exc:  # defensive CLI boundary
        report = {
            "check": "runtime_self_check",
            "network_used": False,
            "user_documents_read": False,
            "core_ready": False,
            "errors": [f"RUNTIME-001: unexpected self-check failure ({type(exc).__name__})"],
            "warnings": [],
        }
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text(report, args.language)
    return 0 if report["core_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
