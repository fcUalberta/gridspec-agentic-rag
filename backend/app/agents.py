import asyncio
import difflib
import json
import re
from functools import lru_cache

from langchain_fireworks import ChatFireworks
from langchain_ollama import ChatOllama

from .config import settings
from .mcp_client import call_catalog_tool
from .models import (
    CandidateDecisionBatch,
    CohesiveSolution,
    ComplianceDecision,
    ControlledComplianceDecision,
    RequirementBatch,
)


class StructuredOutputFailure(RuntimeError):
    """Raised when a model does not return a parseable structured response."""


@lru_cache(maxsize=4)
def model(model_name: str | None = None):
    if not settings.fireworks_api_key:
        raise RuntimeError("FIREWORKS_API_KEY is not configured in backend/.env")
    return ChatFireworks(
        model=model_name or settings.fireworks_chat_model,
        api_key=settings.fireworks_api_key,
        temperature=0,
        timeout=45,
        max_retries=0,
        max_tokens=12000,
    )


@lru_cache(maxsize=2)
def local_candidate_model(model_name: str | None = None):
    return ChatOllama(
        model=model_name or settings.ollama_candidate_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        num_ctx=8192,
        num_predict=4096,
        keep_alive="10m",
        async_client_kwargs={"timeout": 60},
    )


@lru_cache(maxsize=2)
def local_compliance_model(model_name: str | None = None):
    """Use a bounded generation budget for the small compliance decision schema."""
    return ChatOllama(
        model=model_name or settings.ollama_compliance_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        num_ctx=8192,
        num_predict=900,
        keep_alive="10m",
        async_client_kwargs={"timeout": 60},
    )


async def extract_requirement_batch(
    pages: list[dict], model_name: str | None = None
) -> list[dict]:
    prompt = """You are a protection-and-control RFQ analyst. Extract only atomic, testable obligations that the
supplier's offered protection, control, relay, panel, engineering, testing, documentation, or delivery solution
must satisfy. A valid item must state a verifiable deliverable, capability, limit, standard, interface, test, or
supplier action. Exclude project background, owner actions, definitions, bidder instructions, repeated boilerplate,
descriptive statements, headings, and obligations unrelated to the supplied technical solution. Do not convert
examples or contextual statements into requirements. Split a compound sentence only when each resulting item can
be evaluated independently. source_quote must be the shortest exact verbatim substring that proves the obligation;
never paraphrase it. Use the supplied page_number. Return one object matching the schema, or an empty requirements
array when no qualifying supplier obligation exists.\n\nPAGES:\n""" + json.dumps(
        pages, ensure_ascii=False
    )

    failures = []
    # Fireworks JSON Schema is the strongest constraint. Function calling is retained as an
    # independent fallback because model support can differ between deployments.
    for method in ("json_schema", "function_calling"):
        extractor = model(model_name).with_structured_output(
            RequirementBatch,
            method=method,
            include_raw=True,
        )
        response = await extractor.ainvoke(prompt)
        parsed = response.get("parsed") if isinstance(response, dict) else response
        if isinstance(parsed, RequirementBatch):
            return [item.model_dump() for item in parsed.requirements]

        parsing_error = response.get("parsing_error") if isinstance(response, dict) else None
        detail = type(parsing_error).__name__ if parsing_error else "empty parsed output"
        failures.append(f"{method}: {detail}")

    page_numbers = [page["page_number"] for page in pages]
    page_range = str(page_numbers[0]) if len(page_numbers) == 1 else f"{page_numbers[0]}-{page_numbers[-1]}"
    raise StructuredOutputFailure(
        f"Fireworks returned no valid requirement object for RFQ pages {page_range} "
        f"after two structured-output strategies ({'; '.join(failures)})."
    )


async def interpret_requirement_candidates(
    candidates: list[dict], model_name: str | None = None, provider: str = "fireworks"
) -> list[dict]:
    """Interpret bounded ambiguous candidates while keeping citations deterministic."""
    if not candidates:
        return []
    prompt = """You are a protection-and-control RFQ analyst. Review only the supplied candidate excerpts.
Accept a candidate only when it describes a product, panel, engineering, testing, documentation, delivery, or
technical interface requirement that the offered solution must satisfy. Reject legends, drawing noise, owner
actions, bidder-administration instructions, prices, and descriptive background. A table may yield multiple atomic
requirements when its rows clearly state distinct required values or equipment. Use only candidate_id values from
the input. Normalize accepted wording without adding a capability, value, standard, or condition not present in the
candidate. Do not return source quotations, page numbers, or bounding boxes; the application attaches those from
the deterministic parser. Return a decision for each accepted candidate and optionally rejected candidates.

CANDIDATES:
""" + json.dumps(candidates, ensure_ascii=False)

    failures = []
    response = None
    methods = ("json_schema",) if provider == "ollama" else ("json_schema", "function_calling")
    selected_model = (
        local_candidate_model(model_name) if provider == "ollama" else model(model_name)
    )
    for method in methods:
        interpreter = selected_model.with_structured_output(
            CandidateDecisionBatch,
            method=method,
            include_raw=True,
        )
        response = await interpreter.ainvoke(prompt)
        parsed = response.get("parsed") if isinstance(response, dict) else response
        if isinstance(parsed, CandidateDecisionBatch):
            by_id = {candidate["candidate_id"]: candidate for candidate in candidates}
            requirements = []
            for decision in parsed.decisions:
                source = by_id.get(decision.candidate_id)
                if not source or not decision.accept or not decision.requirement_text.strip():
                    continue
                if not re.search(
                    r"\b(shall|must|required|requires?|provide|provided|supply|supplied|"
                    r"include|included|capable|rated)\b",
                    decision.requirement_text,
                    re.IGNORECASE,
                ):
                    continue
                requirements.append({
                    "requirement_key": "",
                    "section": source["section"],
                    "requirement_text": decision.requirement_text.strip(),
                    "source_quote": source["source_quote"],
                    "source_bbox": source.get("source_bbox"),
                    "page_number": source["page_number"],
                    "category": decision.category,
                    "criticality": decision.criticality,
                    "confidence": min(decision.confidence, 88),
                })
            return requirements
        parsing_error = response.get("parsing_error") if isinstance(response, dict) else None
        failures.append(type(parsing_error).__name__ if parsing_error else "empty parsed output")
    raise StructuredOutputFailure(
        f"{provider.title()} returned no valid candidate decisions after structured-output validation "
        f"({'; '.join(failures)})."
    )


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _dedupe_text(text: str) -> str:
    value = normalize(text)
    repairs = (
        (r"\bsba[lu]\b", "shall"),
        (r"\bshal[ilj]\b", "shall"),
        (r"\bjeds?\b", "ied"),
        (r"[!l]ec(?=\s*61850)", "iec"),
        (r"\bmeg(?:ing|lng)\b", "merging"),
    )
    for pattern, replacement in repairs:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _material_tokens(text: str) -> tuple[str, ...]:
    """Protect quantities and standards from fuzzy-deduplication collisions."""
    return tuple(re.findall(r"\b(?:\d+(?:\.\d+)?|iec|ieee|ansi|iso|dnp3|modbus)\b", text))


def _near_duplicate(left: str, right: str) -> bool:
    if left == right:
        return True
    if _material_tokens(left) != _material_tokens(right):
        return False
    length_ratio = min(len(left), len(right)) / max(len(left), len(right), 1)
    return length_ratio >= 0.9 and difflib.SequenceMatcher(None, left, right).ratio() >= 0.965


def validate_and_dedupe_requirements(items: list[dict], pages: list[dict]) -> list[dict]:
    page_text = {
        page["page_number"]: normalize(
            page["text"]
            + "\n"
            + "\n".join(
                block.get("text", "")
                for block in page.get("layout_blocks", [])
            )
        )
        for page in pages
    }
    seen: dict[str, list[str]] = {}
    valid = []
    for item in items:
        quote = normalize(item.get("source_quote", ""))
        page = item.get("page_number")
        if not quote or page not in page_text or quote not in page_text[page]:
            continue
        identity = _dedupe_text(item["requirement_text"])
        category = item.get("category", "Technical")
        if not identity or any(_near_duplicate(identity, prior) for prior in seen.get(category, [])):
            continue
        seen.setdefault(category, []).append(identity)
        item["requirement_key"] = f"REQ-{len(valid)+1:03d}"
        valid.append(item)
    return valid


async def evaluate_requirement(requirement: dict) -> dict:
    search = await call_catalog_tool(
        "search_manual_evidence",
        {"query": requirement["requirement_text"], "limit": 10},
    )
    retrieved = search.get("results", [])
    evaluator = model().with_structured_output(ComplianceDecision)
    prompt = """You are a conservative protection-and-control compliance engineer. Evaluate the requirement only
against RETRIEVED EVIDENCE. Compliant requires explicit evidence for every material element. Conditional means a
configuration or clearly stated design condition is required. Use Unknown when evidence is insufficient. Evidence
quotes must be exact substrings copied from RETRIEVED EVIDENCE. Never infer capability from a product name.

REQUIREMENT:
""" + json.dumps(requirement, ensure_ascii=False) + "\n\nRETRIEVED EVIDENCE:\n" + json.dumps(retrieved, ensure_ascii=False)
    decision = await evaluator.ainvoke(prompt)
    data = decision.model_dump()
    data["requirement_id"] = requirement["id"]

    verified = []
    for evidence in data["evidence"]:
        for source in retrieved:
            if normalize(evidence["quote"]) and normalize(evidence["quote"]) in normalize(source["text"]):
                verified.append({
                    "file_name": source["file_name"],
                    "quote": evidence["quote"],
                    "location": f"Page {source.get('page_number', 'unknown')}",
                    "score": source["score"],
                })
                break
    data["evidence"] = verified
    if not verified:
        data.update({
            "decision": "Unknown",
            "product_name": "",
            "rationale": "No model-cited quotation could be verified against the retrieved product-manual text.",
            "confidence": min(data["confidence"], 30),
        })
    return data


def _evidence_quote(text: str, requirement_text: str, limit: int = 700) -> str:
    """Select the strongest exact sentence locally; the model never writes citations."""
    requirement_tokens = set(re.findall(r"[a-z0-9]+", normalize(requirement_text)))
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?;])\s+|\n{2,}", text)
        if sentence.strip()
    ]
    if not sentences:
        return text[:limit].strip()
    ranked = sorted(
        sentences,
        key=lambda sentence: (
            len(requirement_tokens & set(re.findall(r"[a-z0-9]+", normalize(sentence)))),
            -len(sentence),
        ),
        reverse=True,
    )
    quote = ranked[0]
    return quote if len(quote) <= limit else quote[:limit].rsplit(" ", 1)[0]


async def evaluate_controlled_compliance(
    requirement: dict,
    evidence_candidates: list[dict],
    provider: str = "ollama",
) -> dict:
    """Evaluate one pre-matched requirement and attach only deterministic evidence."""
    bounded = []
    for index, candidate in enumerate(evidence_candidates, start=1):
        bounded.append({
            "evidence_id": f"E{index}",
            "file_name": candidate.get("file_name", ""),
            "page_number": candidate.get("page_number"),
            "score": round(float(candidate.get("score", 0)), 4),
            "prematch_score": round(
                float(candidate.get("prematch_score", candidate.get("score", 0))), 4
            ),
            "lexical_overlap": round(float(candidate.get("lexical_overlap", 0)), 4),
            "text": candidate.get("text", "")[:1400],
        })
    prompt = """You are a conservative protection-and-control compliance engineer. Decide only from the
supplied evidence candidates. Compliant requires explicit support for every material requirement element.
Conditional means the evidence supports the capability only with a stated configuration or integration condition.
Non-compliant requires an explicit contradiction or insufficient product limit; otherwise use Unknown. Select only
evidence_id values from the input. Do not create quotations or page references. Set needs_escalation only for a real
conflict, unclear technical interpretation, or a consequential non-compliance decision. Never infer capability from
a filename or product name. Keep the rationale concise and technical.

REQUIREMENT:
""" + json.dumps({
        "requirement_id": requirement["id"],
        "requirement_text": requirement["requirement_text"],
        "category": requirement.get("category"),
        "criticality": requirement.get("criticality"),
    }, ensure_ascii=False) + "\n\nEVIDENCE CANDIDATES:\n" + json.dumps(bounded, ensure_ascii=False)

    selected_model = (
        local_compliance_model(settings.ollama_compliance_model)
        if provider == "ollama"
        else model(settings.fireworks_chat_model)
    )
    methods = ("json_schema",) if provider == "ollama" else ("json_schema", "function_calling")
    failures = []
    parsed = None
    for method in methods:
        evaluator = selected_model.with_structured_output(
            ControlledComplianceDecision,
            method=method,
            include_raw=True,
        )
        response = await evaluator.ainvoke(prompt)
        parsed = response.get("parsed") if isinstance(response, dict) else response
        if isinstance(parsed, ControlledComplianceDecision):
            break
        parsing_error = response.get("parsing_error") if isinstance(response, dict) else None
        failures.append(type(parsing_error).__name__ if parsing_error else "empty parsed output")
    if not isinstance(parsed, ControlledComplianceDecision):
        raise StructuredOutputFailure(
            f"{provider.title()} returned no controlled compliance decision ({'; '.join(failures)})."
        )

    by_id = {item["evidence_id"]: item for item in bounded}
    selected = [by_id[item] for item in dict.fromkeys(parsed.evidence_ids) if item in by_id]
    decision = parsed.decision
    needs_escalation = parsed.needs_escalation
    escalation_reason = parsed.escalation_reason
    if decision in {"Compliant", "Conditional"} and not selected:
        decision = "Unknown"
        needs_escalation = True
        escalation_reason = "The model returned a positive decision without selecting verifiable evidence."
    verified = [{
        "file_name": item["file_name"],
        "quote": _evidence_quote(item["text"], requirement["requirement_text"]),
        "location": f"Page {item.get('page_number', 'unknown')}",
        "score": item["score"],
    } for item in selected]
    confidence = parsed.confidence
    if confidence == 0:
        # Some structured-output models leave confidence at zero even for a complete
        # decision. Calibrate that missing value from the deterministic evidence score;
        # escalation remains controlled by explicit ambiguity and consequential outcomes.
        if selected:
            confidence = round(max(item["prematch_score"] for item in selected) * 100)
        elif decision == "Unknown":
            confidence = 70
    return {
        "requirement_id": requirement["id"],
        "decision": decision,
        "product_name": parsed.product_name.strip() or (verified[0]["file_name"] if verified else ""),
        "rationale": parsed.rationale.strip(),
        "evidence": verified,
        "alternate_product": parsed.alternate_product,
        "alternate_rationale": parsed.alternate_rationale,
        "confidence": confidence,
        "needs_escalation": needs_escalation,
        "escalation_reason": escalation_reason,
        "evaluation_method": provider,
    }


async def evaluate_requirements(requirements: list[dict]) -> list[dict]:
    semaphore = asyncio.Semaphore(4)

    async def limited(requirement: dict) -> dict:
        async with semaphore:
            return await evaluate_requirement(requirement)

    return await asyncio.gather(*(limited(requirement) for requirement in requirements))


def build_solution_context(requirements: list[dict], assessments: list[dict]) -> list[dict]:
    """Compact a large compliance matrix without hiding unresolved engineering work."""
    requirement_by_id = {item["id"]: item for item in requirements}
    grouped: dict[tuple[str, str], dict] = {}
    for assessment in assessments:
        requirement = requirement_by_id.get(assessment["requirement_id"])
        if not requirement:
            continue
        key = (
            requirement.get("solution_package") or "Generic / Unclassified",
            requirement.get("subcategory") or "Generic / Other",
        )
        group = grouped.setdefault(
            key,
            {
                "solution_package": key[0],
                "subcategory": key[1],
                "decision_counts": {},
                "compliance_objects": [],
                "offered_products": [],
                "sample_requirements": [],
                "unresolved_requirements": [],
                "verified_evidence": [],
            },
        )
        decision = assessment.get("decision", "Unknown")
        group["decision_counts"][decision] = group["decision_counts"].get(decision, 0) + 1
        for field, value in (
            ("compliance_objects", requirement.get("compliance_object")),
            ("offered_products", assessment.get("product_name")),
        ):
            if value and value not in group[field] and len(group[field]) < 12:
                group[field].append(value)
        sample = {
            "requirement_key": requirement.get("requirement_key"),
            "requirement": requirement.get("requirement_text", "")[:400],
            "decision": decision,
            "rationale": assessment.get("rationale", "")[:400],
            "expected_evidence": requirement.get("expected_evidence"),
        }
        if len(group["sample_requirements"]) < 4:
            group["sample_requirements"].append(sample)
        if decision in {"Unknown", "Non-compliant"} and len(group["unresolved_requirements"]) < 6:
            group["unresolved_requirements"].append(sample)
        for evidence in assessment.get("evidence", [])[:2]:
            item = {
                "file_name": evidence.get("file_name"),
                "location": evidence.get("location"),
                "quote": evidence.get("quote", "")[:350],
            }
            if item not in group["verified_evidence"] and len(group["verified_evidence"]) < 6:
                group["verified_evidence"].append(item)
    return [grouped[key] for key in sorted(grouped)]


async def build_solution(requirements: list[dict], assessments: list[dict]) -> dict:
    context = build_solution_context(requirements, assessments)
    prompt = """You are a protection panel solution architect. Assemble one cohesive solution from the controlled
compliance package summary below. Counts cover the full matrix; representative and unresolved requirements retain
the engineering details needed for design. Do not introduce unverified capabilities. Explicitly check
Primary A/B independence, CT/VT interfaces, DC burden, communications, time synchronization, test facilities,
environmental design, panel construction, and FAT/engineering scope. Put unresolved matters in Review or Conflict.

COMPLIANCE PACKAGE SUMMARY:
""" + json.dumps(context, ensure_ascii=False)
    result = None
    last_error: Exception | None = None
    model_names = list(
        dict.fromkeys([settings.fireworks_chat_model, settings.fireworks_strong_model])
    )
    for model_index, model_name in enumerate(model_names):
        architect = model(model_name).with_structured_output(CohesiveSolution)
        attempts = 3 if model_index == 0 else 2
        for attempt in range(attempts):
            try:
                result = await architect.ainvoke(prompt)
                break
            except Exception as error:
                last_error = error
                detail = str(error).lower()
                transient = any(
                    marker in detail
                    for marker in (
                        "429", "500", "502", "503", "504", "overload", "temporarily"
                    )
                )
                if not transient:
                    raise
                if attempt < attempts - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
        if result is not None:
            break
    if result is None and len(prompt) <= 60_000:
        try:
            local_architect = local_candidate_model(
                settings.ollama_candidate_model
            ).with_structured_output(
                CohesiveSolution,
                method="json_schema",
            )
            async with asyncio.timeout(120):
                result = await local_architect.ainvoke(prompt)
        except Exception as local_error:
            if last_error:
                raise last_error from local_error
            raise
    if result is None:
        if last_error:
            raise last_error
        raise RuntimeError("Solution generation returned no result")
    return result.model_dump()
