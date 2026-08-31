import re

OBLIGATION_RE = re.compile(
    r"\b(shall|must|required|requires?|supplier|vendor|contractor|provide|furnish|"
    r"install|design|submit|include|comply|capable|rated)\b",
    re.IGNORECASE,
)
MODAL_RE = re.compile(
    r"\b(shall|shal[lij]|sba[lu]|must|required|requires?|is\s+to|are\s+to)\b",
    re.IGNORECASE,
)
ACTOR_ACTION_RE = re.compile(
    r"\b(supplier|vendor|contractor|bidder|system integrator|si)\b.{0,100}"
    r"\b(provide|furnish|install|design|submit|include|comply|supply)\b",
    re.IGNORECASE,
)
TECHNICAL_RE = re.compile(
    r"\b(relay|panel|protection|control|breaker|substation|transformer|bus|feeder|trip|"
    r"interlock|scada|iec\s*61850|dnp3|modbus|ethernet|fiber|ct|vt|current transformer|"
    r"voltage transformer|dc|battery|wiring|terminal|meter|alarm|synchroni[sz]|testing|fat|"
    r"drawing|documentation|manual|training|commissioning|enclosure|nameplate|contact|"
    r"input|output|frequency|temperature|voltage|current|accuracy|burden)\b",
    re.IGNORECASE,
)
VALUE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:v|kv|a|ma|ka|hz|ms|mm|°c|ohm|k[oΩ]|%|bit/s)\b|"
    r"\b(?:iec|ieee|ansi|en|iso)\s*[-:]?\s*\d+",
    re.IGNORECASE,
)
ADMIN_RE = re.compile(
    r"\b(proposal|tender|invitation to bid|bid submission|bidder|deadline|before noon|"
    r"official letter|power of attorney|bid security|tax|price schedule|payment terms|"
    r"eligibility|joint venture|consortium|shareholder|voting right|procurement)\b",
    re.IGNORECASE,
)
DOMAIN_RE = re.compile(
    r"\b(relay|panel|protection|breaker|substation|transformer|feeder|trip|scada|"
    r"iec\s*61850|dnp3|modbus|ct|vt|current transformer|voltage transformer|battery|"
    r"wiring|terminal|meter|commissioning|enclosure|nameplate)\b",
    re.IGNORECASE,
)
QUALIFICATION_RE = re.compile(
    r"\b(having practical experience|years? of experience|qualification of bidders?|"
    r"eligible bidder|similar contracts?|reference projects?)\b",
    re.IGNORECASE,
)
EXCLUDED_SECTION_RE = re.compile(
    r"\b(eligibility|qualification of bidders?|invitation(?: to bid)?|instructions? to bidders?|"
    r"preparation and delivery of bids?|bid submission|joint venture|consortium|"
    r"price schedule|payment terms?|bid security|proposal forms?|evaluation of bids?)\b",
    re.IGNORECASE,
)
OWNER_ACTION_RE = re.compile(
    r"^\s*(?:the\s+)?(?:owner|customer|purchaser|utility|egat)\s+(?:shall|must|will|may)\b",
    re.IGNORECASE,
)
SUPPLIER_ACTOR_RE = re.compile(
    r"\b(supplier|vendor|contractor|bidder|system integrator|\bsi\b|equipment|panel|relay|system)\b",
    re.IGNORECASE,
)
CONTINUATION_END_RE = re.compile(
    r"\b(and|or|including|include|with|without|for|of|to|the|as|per|consisting of)\s*[:,-]?$",
    re.IGNORECASE,
)
OCR_REPAIRS = (
    (re.compile(r"\bsba[lu]\b", re.IGNORECASE), "shall"),
    (re.compile(r"\bshal[ilj]\b", re.IGNORECASE), "shall"),
    (re.compile(r"\b[lJ]EDs?\b"), "IED"),
    (re.compile(r"\bJEC(?=\s*61850)"), "IEC"),
    (re.compile(r"[!l]EC(?=\s*61850)", re.IGNORECASE), "IEC"),
    (re.compile(r"\bmeg(?:ing|lng)\b", re.IGNORECASE), "merging"),
    (re.compile(r"\bmcging\b", re.IGNORECASE), "merging"),
    (re.compile(r"\bench\b", re.IGNORECASE), "each"),
    (re.compile(r"\bMd\b"), "and"),
    (re.compile(r"\bHM!"), "HMI"),
    (re.compile(r"\bdalll\b", re.IGNORECASE), "data"),
    (re.compile(r"\bnil\b", re.IGNORECASE), "all"),
    (re.compile(r"\bran\b", re.IGNORECASE), "run"),
    (re.compile(r"\bsubslntion\b", re.IGNORECASE), "substation"),
    (re.compile(r"\be!?eclrooic\w*\b", re.IGNORECASE), "electronic file"),
    (re.compile(r"\bsy\W*i?tcm\b", re.IGNORECASE), "system"),
    (re.compile(r"\bconfonn\b", re.IGNORECASE), "conform"),
    (re.compile(r"\bsl(?:t|1)all\b", re.IGNORECASE), "shall"),
    (re.compile(r"\bsystc~", re.IGNORECASE), "system"),
    (re.compile(r"\bhyEGAT\b", re.IGNORECASE), "by EGAT"),
    (re.compile(r"\bstandard lo coordinate\b", re.IGNORECASE), "standard to coordinate"),
    (re.compile(r"\blcle protection\b", re.IGNORECASE), "teleprotection"),
    (re.compile(r"\bniong\b", re.IGNORECASE), "along"),
    (re.compile(r"\bcxisliog\b", re.IGNORECASE), "existing"),
    (re.compile(r"\bhardcopyand\b", re.IGNORECASE), "hardcopy and"),
    (re.compile(r"\bdigiL['’]ll\b", re.IGNORECASE), "digital"),
    (re.compile(r"\bIIMI\b"), "HMI"),
    (re.compile(r"\b(SSD|SCD|ICD|CID)\s+mes\b", re.IGNORECASE), r"\1 files"),
    (re.compile(r"\bprogrammable:\s+", re.IGNORECASE), "programmable "),
)
GARBLED_TEXT_RE = re.compile(
    r"(?:[A-Za-z][!;][A-Za-z]|\b(?:ench|JED|Md|dalll|nil|JEC|subslntion|"
    r"eclrooic|sy\W*tcm|meging|mcging|swithcing|confonn)\b)",
    re.IGNORECASE,
)
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?;])\s+(?=(?:\(?[A-Z0-9]))")
SECTION_RE = re.compile(r"^\s*(?:\d+(?:[.-]\d+){1,6}|[A-Z]\.[0-9.]+)\s+(.{3,100})$")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _category(text: str) -> str:
    rules = (
        ("Testing", r"\b(test|testing|fat|commissioning)\b"),
        ("Documentation", r"\b(document|drawing|manual|report|submit)\b"),
        ("Communications", r"\b(scada|iec\s*61850|dnp3|modbus|ethernet|fiber|communication)\b"),
        ("Panel Construction", r"\b(panel|enclosure|wiring|terminal|nameplate)\b"),
        ("Protection and Control", r"\b(relay|protection|trip|breaker|interlock|bus|feeder)\b"),
        ("Electrical Interface", r"\b(ct|vt|current|voltage|dc|battery|burden|contact|input|output)\b"),
    )
    for category, pattern in rules:
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return "Technical"


def _section(page: dict, quote: str, block: dict | None = None) -> str:
    if block and normalize(block.get("section", "")):
        return normalize(block["section"])[:170]
    if normalize(page.get("section", "")):
        return normalize(page["section"])[:170]
    for line in reversed(page["text"].splitlines()):
        line = normalize(line)
        if line and line in quote:
            continue
        match = SECTION_RE.match(line)
        if match:
            return normalize(line)[:140]
    return f"RFQ page {page['page_number']}"


def _candidate(
    page: dict,
    quote: str,
    candidate_type: str,
    bbox: list[float] | None,
    index: int,
    section: str | None = None,
) -> dict:
    quote = normalize(quote)
    return {
        "candidate_id": f"p{page['page_number']}-{candidate_type}-{index}",
        "candidate_type": candidate_type,
        "page_number": page["page_number"],
        "section": section or _section(page, quote),
        "source_quote": quote,
        "source_bbox": bbox,
        "category": _category(quote),
        "criticality": (
            "Mandatory"
            if re.search(r"\b(shall|must|required)\b", quote, re.IGNORECASE)
            else "Preferred"
        ),
        "confidence": 92 if candidate_type == "explicit" else 65,
    }


def _clean_requirement_text(text: str) -> str:
    cleaned = normalize(text)
    for pattern, replacement in OCR_REPAIRS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def _excluded_context(section: str, quote: str) -> bool:
    context = f"{section} {quote}"
    if EXCLUDED_SECTION_RE.search(section):
        return True
    if QUALIFICATION_RE.search(context):
        return True
    return bool(OWNER_ACTION_RE.search(quote) and not SUPPLIER_ACTOR_RE.search(quote))


def _is_complete_obligation(quote: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z0-9/-]*", quote)
    if len(words) < 6:
        return False
    if CONTINUATION_END_RE.search(quote):
        return False
    if quote.count("|") >= 4 or re.search(r"\.{4,}\s*\d+", quote):
        return False
    printable = sum(character.isalnum() or character.isspace() or character in ".,;:()/%+-" for character in quote)
    return printable / max(len(quote), 1) >= 0.9


def _bbox_union(left: list[float] | None, right: list[float] | None) -> list[float] | None:
    if not left:
        return right
    if not right:
        return left
    return [min(left[0], right[0]), min(left[1], right[1]), max(left[2], right[2]), max(left[3], right[3])]


def _stitch_continuation_blocks(blocks: list[dict]) -> list[dict]:
    """Join PDF blocks only when a modal clause visibly continues in the next block."""
    stitched = []
    index = 0
    while index < len(blocks):
        block = dict(blocks[index])
        text = normalize(block.get("text", ""))
        consumed = index
        while (
            consumed + 1 < len(blocks)
            and len(text) < 1600
            and (MODAL_RE.search(text) or ACTOR_ACTION_RE.search(text))
            and not re.search(r"[.!?;][\"')\]]?$", text)
        ):
            following = normalize(blocks[consumed + 1].get("text", ""))
            if not following or re.match(
                r"^\d+(?:\.\d+)*[.)]?\s+\S+\s+(?:shall|must)\b",
                following,
                re.IGNORECASE,
            ):
                break
            continuation = bool(
                CONTINUATION_END_RE.search(text)
                or re.match(r"^[a-z]", following)
                or re.search(r"\b(?:on|in|by|from)\s*$", text, re.IGNORECASE)
                or re.search(r"[,(:]\s*$", text)
            )
            if not continuation:
                break
            consumed += 1
            text = normalize(f"{text} {following}")
            block["bbox"] = _bbox_union(block.get("bbox"), blocks[consumed].get("bbox"))
        block["text"] = text
        stitched.append(block)
        index = consumed + 1
    return stitched


def _explicit_candidates(page: dict) -> list[dict]:
    result = []
    seen = set()
    blocks = _stitch_continuation_blocks(
        page.get("blocks") or [{"text": page["text"], "bbox": None}]
    )
    for block in blocks:
        block_text = normalize(block.get("text", ""))
        section = _section(page, block_text, block)
        for sentence in SENTENCE_BREAK_RE.split(block_text):
            quote = normalize(sentence)
            identity = quote.lower()
            if not 25 <= len(quote) <= 1600 or identity in seen:
                continue
            if quote.endswith(":") and len(quote) < 300:
                continue
            if _excluded_context(section, quote):
                continue
            if not (MODAL_RE.search(quote) or ACTOR_ACTION_RE.search(quote)):
                continue
            if re.search(r"\bscope of\s*work\b", quote, re.IGNORECASE) and not MODAL_RE.search(quote):
                continue
            if not TECHNICAL_RE.search(quote):
                continue
            if ADMIN_RE.search(quote) and not DOMAIN_RE.search(quote):
                continue
            if not _is_complete_obligation(quote):
                continue
            seen.add(identity)
            cleaned_quote = _clean_requirement_text(quote)
            candidate_type = "ambiguous" if GARBLED_TEXT_RE.search(cleaned_quote) else "explicit"
            result.append(
                _candidate(page, quote, candidate_type, block.get("bbox"), len(result), section)
            )
    return result


def _table_text(block: dict) -> str:
    lines = []
    header = block.get("header") or []
    if header:
        lines.append(" | ".join(normalize(cell.get("text", "")) for cell in header))
    for row in block.get("rows") or []:
        lines.append(" | ".join(normalize(cell.get("text", "")) for cell in row))
    return "\n".join(line for line in lines if line.replace("|", "").strip())


def _implicit_table_candidates(page: dict) -> list[dict]:
    result = []
    for block in page.get("layout_blocks", []):
        if block.get("kind") != "table":
            continue
        quote = _table_text(block)
        section = _section(page, quote, block)
        if not 20 <= len(quote) <= 6000:
            continue
        if _excluded_context(section, quote):
            continue
        if re.search(r"\b(table of contents|page\s+no\.?|price schedule)\b", quote, re.IGNORECASE):
            continue
        if not (TECHNICAL_RE.search(quote) or VALUE_RE.search(quote)):
            continue
        result.append(_candidate(page, quote, "table", block.get("bbox"), len(result), section))
    return result


def requirement_candidates(page: dict) -> list[dict]:
    candidates = _explicit_candidates(page) + _implicit_table_candidates(page)
    seen = set()
    unique = []
    for candidate in candidates:
        identity = normalize(candidate["source_quote"]).lower()
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
    return unique


def direct_requirement(candidate: dict) -> dict:
    quote = normalize(candidate["source_quote"])
    return {
        "requirement_key": "",
        "section": candidate["section"],
        "requirement_text": _clean_requirement_text(quote),
        "source_quote": quote,
        "source_bbox": candidate.get("source_bbox"),
        "page_number": candidate["page_number"],
        "category": candidate["category"],
        "criticality": candidate["criticality"],
        "confidence": candidate["confidence"],
    }
