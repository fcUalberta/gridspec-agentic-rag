import logging
import re
import shutil
from pathlib import Path

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

HEADING_RE = re.compile(
    r"^\s*(?:(?:section|article|part)\s+)?"
    r"(?:\d+(?:[.\-]\d+){0,6}[.]?|[A-Z][-\.]\d+(?:\.\d+)*[.]?)\s+\S.{2,150}$",
    re.IGNORECASE,
)
HEADING_WORD_RE = re.compile(
    r"\b(requirements?|scope|specifications?|qualification|eligibility|"
    r"instructions?|price|payment|proposal|bid(?:der|ding)?|testing|drawings?|"
    r"documentation|protection|control|communications?|panel|equipment)\b",
    re.IGNORECASE,
)
ADMIN_HEADING_RE = re.compile(
    r"\b(eligibility|qualification of bidders?|instructions? to bidders?|"
    r"preparation and delivery of bids?|bid submission|joint venture|consortium|"
    r"price schedule|payment terms?|bid security|proposal forms?|evaluation of bids?)\b",
    re.IGNORECASE,
)
TOP_LEVEL_HEADING_RE = re.compile(r"^\s*(?:[A-Z]-\d+|section\s+[A-Z0-9]+)\b", re.IGNORECASE)
OBLIGATION_WORD_RE = re.compile(
    r"\b(shall|must|required|provide|furnish|install|design|submit|comply)\b",
    re.IGNORECASE,
)


def _bbox(value: object | None) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [round(float(item), 3) for item in value]
    x = float(value.x)
    y = float(value.y)
    return [
        round(x, 3),
        round(y, 3),
        round(x + float(value.width), 3),
        round(y + float(value.height), 3),
    ]


def _repair_encoding(text: str) -> str:
    """Repair common PDF UTF-8-as-Latin-1 artifacts without altering clean text."""
    markers = sum(text.count(marker) for marker in ("Â", "Ã", "â"))
    if not markers:
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    repaired_markers = sum(repaired.count(marker) for marker in ("Â", "Ã", "â"))
    return repaired if repaired_markers < markers else text


def _heading_from_block(text: str) -> str | None:
    """Return a conservative heading candidate from the start of a PDF block."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    first = lines[0]
    if re.fullmatch(r"(?:[A-Z][-\.]?)?\d+(?:[.\-]\d+)*[.]?", first) and len(lines) > 1:
        first = f"{first} {lines[1]}"
    if re.fullmatch(r"SECTION\s+[A-Z0-9]+", first, re.IGNORECASE):
        return first
    if TOP_LEVEL_HEADING_RE.match(first) and len(first) <= 170 and not OBLIGATION_WORD_RE.search(first):
        return first
    if len(first) > 170 or not HEADING_WORD_RE.search(first):
        return None
    if OBLIGATION_WORD_RE.search(first):
        return None
    letters = [character for character in first if character.isalpha()]
    uppercase = bool(letters) and sum(character.isupper() for character in letters) / len(letters) >= 0.8
    if HEADING_RE.match(first) or (uppercase and 2 <= len(first.split()) <= 18):
        return first[:170]
    return None


def _annotate_sections(pages: list[dict]) -> None:
    """Attach the closest preceding document heading to each source block."""
    active_section = ""
    administrative_section = ""
    for page in pages:
        page_section = active_section
        for block in page.get("blocks", []):
            heading = _heading_from_block(block.get("text", ""))
            if heading:
                letters = [character for character in heading if character.isalpha()]
                uppercase_heading = bool(letters) and (
                    sum(character.isupper() for character in letters) / len(letters) >= 0.8
                )
                major_heading = bool(TOP_LEVEL_HEADING_RE.match(heading) or uppercase_heading)
                if ADMIN_HEADING_RE.search(heading) and major_heading:
                    administrative_section = heading
                elif TOP_LEVEL_HEADING_RE.match(heading):
                    administrative_section = ""
                active_section = heading
                page_section = heading
            context = [administrative_section, active_section]
            block["section"] = " > ".join(dict.fromkeys(item for item in context if item))
        context = [administrative_section, page_section]
        page["section"] = " > ".join(dict.fromkeys(item for item in context if item)) or (
            f"RFQ page {page['page_number']}"
        )


def _serialize_layout_block(block: object) -> dict:
    result = {
        "kind": str(getattr(block, "kind", "paragraph")),
        "text": _repair_encoding(getattr(block, "text", "") or ""),
        "bbox": _bbox(getattr(block, "bbox", None)),
    }
    for name in ("level", "ordered", "marker"):
        value = getattr(block, name, None)
        if value is not None:
            result[name] = value
    header = getattr(block, "header", None)
    if header:
        result["header"] = [
            {"text": _repair_encoding(cell.text), "bbox": _bbox(cell.bbox)}
            for cell in header
        ]
    rows = getattr(block, "rows", None)
    if rows:
        result["rows"] = [
            [
                {"text": _repair_encoding(cell.text), "bbox": _bbox(cell.bbox)}
                for cell in row
            ]
            for row in rows
        ]
    if result["kind"] == "table" and not result["text"]:
        lines = []
        if result.get("header"):
            lines.append(" | ".join(cell["text"] for cell in result["header"]))
        lines.extend(
            " | ".join(cell["text"] for cell in row)
            for row in result.get("rows", [])
        )
        result["text"] = "\n".join(line for line in lines if line.replace("|", "").strip())
    return result


def _target_pages(page_numbers: list[int]) -> str:
    ranges: list[str] = []
    start = previous = page_numbers[0]
    for page_number in page_numbers[1:]:
        if page_number == previous + 1:
            previous = page_number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page_number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _add_complex_layout(path: str, pages: list[dict]) -> None:
    """Attach LiteParse structure only to pages its cheap preflight marks complex."""
    try:
        from liteparse import LiteParse
    except ImportError:
        logger.warning("LiteParse is unavailable; continuing with PyMuPDF blocks")
        return

    detector = LiteParse(ocr_enabled=False, quiet=True)
    try:
        stats = detector.is_complex(path)
        stats_by_page = {item.page_number: item for item in stats}
        complex_pages = [
            item.page_number
            for item in stats
            if item.needs_ocr
            or item.is_garbled
            or bool(item.layout and item.layout.is_complex)
        ]
        if not complex_pages:
            return
        ocr_available = bool(shutil.which("tesseract"))
        parser = LiteParse(
            ocr_enabled=ocr_available,
            quiet=True,
            target_pages=_target_pages(complex_pages),
            extract_blocks=True,
            include_complexity=True,
        )
        parsed = parser.parse(path)
    except Exception as error:
        logger.warning("LiteParse enrichment failed; using PyMuPDF only: %s", error)
        return

    by_number = {page["page_number"]: page for page in pages}
    for parsed_page in parsed.pages:
        page = by_number.get(parsed_page.page_num)
        if not page:
            continue
        page["layout_blocks"] = [
            _serialize_layout_block(block) for block in (parsed_page.blocks or [])
        ]
        complexity = parsed_page.complexity
        original_complexity = stats_by_page.get(parsed_page.page_num)
        page["layout_complexity"] = {
            "needs_ocr": bool(complexity and complexity.needs_ocr),
            "is_garbled": bool(complexity and complexity.is_garbled),
            "reasons": list(complexity.reasons) if complexity else [],
            "layout_reasons": (
                list(complexity.layout.reasons)
                if complexity and complexity.layout
                else []
            ),
        }
        page["ocr_applied"] = bool(
            ocr_available
            and original_complexity
            and (original_complexity.needs_ocr or original_complexity.is_garbled)
        )
        if page["ocr_applied"] and parsed_page.text and len(parsed_page.text.strip()) >= 20:
            page["text"] = _repair_encoding(parsed_page.text).strip()
            replacement_blocks = [
                block
                for block in page["layout_blocks"]
                if block.get("kind") != "table" and block.get("text", "").strip()
            ]
            if replacement_blocks:
                page["blocks"] = replacement_blocks

    _annotate_sections(pages)


def extract_pages(path: str, include_complex_layout: bool = False) -> list[dict]:
    document = pymupdf.open(path)
    try:
        pages = []
        for number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=False).strip()
            if not text:
                continue
            blocks = []
            for block in page.get_text("blocks", sort=False):
                if int(block[6]) != 0 or not str(block[4]).strip():
                    continue
                blocks.append({
                    "bbox": [round(float(value), 3) for value in block[:4]],
                    "text": str(block[4]).strip(),
                })
            pages.append({
                "page_number": number,
                "text": text,
                "width": round(float(page.rect.width), 3),
                "height": round(float(page.rect.height), 3),
                "blocks": blocks,
            })
    finally:
        document.close()
    if not pages:
        raise ValueError(
            "No machine-readable text was found. Run OCR on this scanned PDF before processing."
        )
    _annotate_sections(pages)
    if include_complex_layout:
        _add_complex_layout(path, pages)
    return pages


def chunk_pages(path: str, document_id: str, file_name: str) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1800, chunk_overlap=250)
    chunks = []
    for page in extract_pages(path):
        for index, text in enumerate(splitter.split_text(page["text"])):
            chunks.append({
                "id": f"{document_id}-p{page['page_number']}-c{index}",
                "text": text,
                "file_name": file_name,
                "page_number": page["page_number"],
                "document_id": document_id,
            })
    return chunks


def safe_upload_path(file_name: str, document_id: str) -> Path:
    safe_name = "".join(
        character if character.isalnum() or character in ".-_" else "-"
        for character in file_name
    )
    return Path(document_id + "-" + safe_name)
