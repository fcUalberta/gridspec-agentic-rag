import asyncio
import hashlib
import json
import re
import uuid

from . import db
from .agents import evaluate_controlled_compliance
from .config import settings
from .mcp_client import call_catalog_tool

PIPELINE_VERSION = "controlled-compliance-v4"
BATCH_SIZE = 8
MAX_BATCH_WORKERS = 4
LOCAL_MODEL_CONCURRENCY = 1
FIREWORKS_CONCURRENCY = 2
LOCAL_EVALUATION_TIMEOUT_SECONDS = 75

CONSEQUENTIAL_PACKAGES = {
    "Protection and Control System",
    "Process Bus and Instrument Interfaces",
    "Station Communications Network",
    "HMI, SCADA and Automation",
    "Panels and Auxiliary Electrical Systems",
}
CONFLICT_TERMS = ("conflict", "contradict", "inconsistent", "incompatible")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "each", "for", "from", "in", "is",
    "it", "of", "on", "or", "shall", "should", "that", "the", "this", "to", "with",
}
MATERIAL_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:kv|v|ka|ma|a|hz|ms|mm|°c|ohm|%|mbps)?|"
    r"iec\s*\d+|ieee\s*[a-z0-9.\-]+|ansi\s*[a-z0-9.\-]+|dnp3|modbus|irig-b|ptp|ntp)\b",
    re.IGNORECASE,
)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def _material_tokens(text: str) -> set[str]:
    return {re.sub(r"\s+", "", item.lower()) for item in MATERIAL_RE.findall(text)}


def pre_match_evidence(requirement: dict, retrieved: list[dict]) -> list[dict]:
    """Apply conservative lexical, vector, and hard-value gates before model evaluation."""
    requirement_tokens = _tokens(requirement["requirement_text"])
    materials = _material_tokens(requirement["requirement_text"])
    numeric_materials = {item for item in materials if item[0].isdigit()}
    ranked = []
    for item in retrieved:
        text = item.get("text", "")
        evidence_tokens = _tokens(text)
        overlap = len(requirement_tokens & evidence_tokens) / max(len(requirement_tokens), 1)
        vector_score = float(item.get("score", 0))
        evidence_materials = _material_tokens(text)
        material_overlap = len(materials & evidence_materials) / max(len(materials), 1) if materials else 1.0
        passes_similarity = (
            vector_score >= settings.compliance_vector_threshold
            and overlap >= settings.compliance_lexical_threshold
        )
        passes_materials = (
            (not materials or material_overlap > 0)
            and numeric_materials.issubset(evidence_materials)
        )
        if not (passes_similarity and passes_materials):
            continue
        enriched = dict(item)
        enriched["lexical_overlap"] = round(overlap, 4)
        enriched["material_overlap"] = round(material_overlap, 4)
        enriched["prematch_score"] = round(vector_score * 0.7 + overlap * 0.3, 4)
        ranked.append(enriched)
    ranked.sort(key=lambda item: item["prematch_score"], reverse=True)
    return ranked[: settings.compliance_evidence_limit]


def _input_hash(requirements: list[dict], products: list[dict]) -> str:
    payload = {
        "requirements": [
            (
                item["id"],
                item["requirement_text"],
                item.get("solution_package"),
                item.get("subcategory"),
                item.get("evidence_scope"),
            )
            for item in requirements
        ],
        "products": [(item["id"], item["file_name"], item["byte_size"]) for item in products],
        "pipeline": PIPELINE_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def serialize_job(job: dict | None) -> dict | None:
    if not job:
        return None
    total = int(job["total_requirements"])
    completed = int(job["completed_requirements"])
    job["progress_percent"] = round(completed / total * 100) if total else 0
    states = db.row(
        """SELECT
           SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS active,
           SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
           FROM compliance_batches WHERE job_id = ?""",
        (job["id"],),
    )
    job["active_batches"] = int(states["active"] or 0) if states else 0
    job["pending_batches"] = int(states["pending"] or 0) if states else 0
    current = db.row(
        """SELECT batch_index, requirement_ids_json FROM compliance_batches
           WHERE job_id = ? AND status = 'running' ORDER BY batch_index LIMIT 1""",
        (job["id"],),
    )
    job["current_batch"] = int(current["batch_index"]) + 1 if current else None
    return job


def get_job(job_id: str) -> dict | None:
    return serialize_job(db.row("SELECT * FROM compliance_jobs WHERE id = ?", (job_id,)))


def latest_job() -> dict | None:
    job = serialize_job(db.row("SELECT * FROM compliance_jobs ORDER BY created_at DESC LIMIT 1"))
    if not job:
        return None
    requirements = db.rows(
        """SELECT id, requirement_text, solution_package, subcategory, evidence_scope
           FROM requirements ORDER BY manual_match_applicable, package_order,
           subcategory_order, page_number, requirement_key"""
    )
    products = db.rows(
        "SELECT id, file_name, byte_size FROM documents WHERE kind = 'product' AND status = 'indexed' ORDER BY id"
    )
    job["stale"] = not requirements or not products or job["input_hash"] != _input_hash(requirements, products)
    return job


def create_or_resume_job(force: bool = False) -> dict:
    requirements = db.rows(
        """SELECT id, requirement_text, solution_package, subcategory, evidence_scope
           FROM requirements ORDER BY manual_match_applicable, package_order,
           subcategory_order, page_number, requirement_key"""
    )
    if not requirements:
        raise ValueError("Extract at least one requirement before compliance evaluation")
    products = db.rows(
        "SELECT id, file_name, byte_size FROM documents WHERE kind = 'product' AND status = 'indexed' ORDER BY id"
    )
    if not products:
        raise ValueError("Index at least one product manual before compliance evaluation")
    input_hash = _input_hash(requirements, products)
    existing = None if force else latest_job()
    if (
        existing
        and existing["pipeline_version"] == PIPELINE_VERSION
        and existing["input_hash"] == input_hash
    ):
        if existing["status"] in {"failed", "interrupted"}:
            db.execute(
                """UPDATE compliance_jobs SET status = 'queued', failed_batches = 0,
                   error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (existing["id"],),
            )
            db.execute(
                """UPDATE compliance_batches SET status = 'pending', error = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE job_id = ? AND status != 'completed'""",
                (existing["id"],),
            )
        return get_job(existing["id"])

    job_id = str(uuid.uuid4())
    batches = [requirements[index:index + BATCH_SIZE] for index in range(0, len(requirements), BATCH_SIZE)]
    db.execute("DELETE FROM assessments")
    db.execute("DELETE FROM solutions")
    db.execute(
        """INSERT INTO compliance_jobs
           (id, status, input_hash, total_batches, total_requirements, pipeline_version)
           VALUES (?, 'queued', ?, ?, ?, ?)""",
        (job_id, input_hash, len(batches), len(requirements), PIPELINE_VERSION),
    )
    for index, batch in enumerate(batches):
        db.execute(
            """INSERT INTO compliance_batches
               (id, job_id, batch_index, requirement_ids_json, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (str(uuid.uuid4()), job_id, index, json.dumps([item["id"] for item in batch])),
        )
    return get_job(job_id)


def _deterministic_unknown(requirement: dict) -> dict:
    return {
        "requirement_id": requirement["id"],
        "decision": "Unknown",
        "product_name": "",
        "rationale": (
            "No product-manual passage passed the deterministic similarity and hard-value gates. "
            "No model evaluation was performed."
        ),
        "evidence": [],
        "alternate_product": None,
        "alternate_rationale": None,
        "confidence": 95,
        "evaluation_method": "deterministic-no-evidence",
    }


def _non_product_evidence_route(requirement: dict) -> dict:
    scope = requirement.get("evidence_scope", "engineer_confirmation")
    messages = {
        "system_design": (
            "This requirement must be evaluated against the offered system architecture, schematic, "
            "or configuration design; product manuals alone cannot establish compliance."
        ),
        "engineering_deliverable": (
            "This requirement is a supplier deliverable or commitment. Compliance requires the submitted "
            "engineering package or an explicit bid commitment, not a product-manual match."
        ),
        "test_report": (
            "This requirement must be verified by an approved test procedure and signed FAT, SAT, or "
            "commissioning report; product manuals alone cannot establish completion."
        ),
        "engineer_confirmation": (
            "The requirement is not sufficiently product-specific for automated manual matching and "
            "requires engineer confirmation."
        ),
    }
    methods = {
        "system_design": "system-design-review",
        "engineering_deliverable": "deliverable-review",
        "test_report": "verification-review",
        "engineer_confirmation": "engineer-review",
    }
    return {
        "requirement_id": requirement["id"],
        "decision": "Unknown",
        "product_name": "",
        "rationale": messages.get(scope, messages["engineer_confirmation"]),
        "evidence": [],
        "alternate_product": None,
        "alternate_rationale": None,
        "confidence": 95,
        "evaluation_method": methods.get(scope, "engineer-review"),
    }


def _apply_evidence_scope(requirement: dict, result: dict) -> dict:
    if (
        requirement.get("evidence_scope") == "hybrid"
        and result.get("decision") in {"Compliant", "Conditional"}
    ):
        result["decision"] = "Conditional"
        result["confidence"] = min(int(result.get("confidence", 0)), 85)
        result["rationale"] = (
            f"{result.get('rationale', '').rstrip()} Product evidence supports the component; "
            "the offered architecture or schematic must also verify the system-level condition."
        ).strip()
    return result


def _should_escalate(requirement: dict, result: dict) -> bool:
    """Reserve cloud review for consequential decisions that another model can resolve."""
    if requirement.get("criticality") != "Mandatory":
        return False
    if requirement.get("solution_package") not in CONSEQUENTIAL_PACKAGES:
        return False

    decision = result.get("decision")
    if decision == "Non-compliant":
        return True

    reason = str(result.get("escalation_reason") or "").lower()
    explicit_conflict = any(term in reason for term in CONFLICT_TERMS)
    supported_ambiguity = (
        decision in {"Compliant", "Conditional"}
        and bool(result.get("evidence"))
        and bool(result.get("needs_escalation"))
    )
    return explicit_conflict or supported_ambiguity


async def _evaluate_one(
    requirement: dict,
    candidates: list[dict],
    local_semaphore: asyncio.Semaphore,
    fireworks_semaphore: asyncio.Semaphore,
) -> tuple[dict, dict]:
    if not requirement.get("manual_match_applicable"):
        return _non_product_evidence_route(requirement), {"deterministic_unknowns": 1}
    if not candidates:
        return _deterministic_unknown(requirement), {"deterministic_unknowns": 1}
    local_error = None
    local_result = None
    try:
        async with local_semaphore:
            async with asyncio.timeout(LOCAL_EVALUATION_TIMEOUT_SECONDS):
                local_result = await evaluate_controlled_compliance(
                    requirement, candidates, "ollama"
                )
    except TimeoutError:
        return {
            "requirement_id": requirement["id"],
            "decision": "Unknown",
            "product_name": "",
            "rationale": (
                "The bounded local-model evaluation exceeded its time limit. No cloud escalation "
                "was performed; engineer review or a later retry is required."
            ),
            "evidence": [],
            "alternate_product": None,
            "alternate_rationale": None,
            "confidence": 90,
            "evaluation_method": "ollama-timeout",
        }, {"ollama_evaluations": 1}
    except Exception as error:
        local_error = error

    if local_result is not None and not _should_escalate(requirement, local_result):
        if local_result.get("needs_escalation"):
            local_result["evaluation_method"] = "ollama-engineer-review"
            if local_result.get("decision") != "Unknown":
                local_result["decision"] = "Unknown"
                local_result["confidence"] = min(int(local_result.get("confidence", 0)), 50)
            local_result["rationale"] = (
                f"{local_result.get('rationale', '').rstrip()} "
                "Cloud escalation was skipped by the controlled criticality policy; "
                "engineer review is required."
            ).strip()
        local_result.pop("needs_escalation", None)
        local_result.pop("escalation_reason", None)
        return _apply_evidence_scope(requirement, local_result), {"ollama_evaluations": 1}

    try:
        async with fireworks_semaphore:
            escalated = await evaluate_controlled_compliance(requirement, candidates, "fireworks")
        escalated["evaluation_method"] = "fireworks-escalation"
        escalated.pop("needs_escalation", None)
        escalated.pop("escalation_reason", None)
        if (
            escalated.get("decision") in {"Compliant", "Conditional", "Non-compliant"}
            and int(escalated.get("confidence", 0)) < 60
        ):
            escalated.update({
                "decision": "Unknown",
                "rationale": (
                    "Escalation returned a consequential decision below the minimum confidence threshold; "
                    "the result is conservatively Unknown."
                ),
                "product_name": "",
                "alternate_product": None,
                "alternate_rationale": None,
                "evaluation_method": "fireworks-unresolved",
            })
        return _apply_evidence_scope(requirement, escalated), {
            "ollama_evaluations": 1 if local_result is not None else 0,
            "fireworks_escalations": 1,
        }
    except Exception as fireworks_error:
        if local_result is not None:
            return {
                **local_result,
                "decision": "Unknown",
                "rationale": (
                    f"Local evaluation required escalation, but the escalation provider was unavailable: "
                    f"{type(fireworks_error).__name__}. The result is conservatively Unknown."
                ),
                "confidence": min(int(local_result.get("confidence", 0)), 30),
                "evaluation_method": "ollama-unresolved",
            }, {"ollama_evaluations": 1, "fireworks_escalations": 1}
        raise RuntimeError(
            "Both compliance evaluators failed: "
            f"Ollama {type(local_error).__name__}; Fireworks {type(fireworks_error).__name__}."
        ) from fireworks_error


def _refresh_counts(job_id: str) -> None:
    batches = db.rows(
        "SELECT status, assessments_json, metrics_json FROM compliance_batches WHERE job_id = ?",
        (job_id,),
    )
    metrics = {"deterministic_unknowns": 0, "ollama_evaluations": 0, "fireworks_escalations": 0}
    completed_requirements = 0
    for batch in batches:
        if batch["status"] == "completed":
            completed_requirements += len(json.loads(batch["assessments_json"] or "[]"))
            for key, value in json.loads(batch["metrics_json"] or "{}").items():
                metrics[key] = metrics.get(key, 0) + int(value)
    db.execute(
        """UPDATE compliance_jobs SET completed_batches = ?, failed_batches = ?,
           completed_requirements = ?, deterministic_unknowns = ?, ollama_evaluations = ?,
           fireworks_escalations = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (
            sum(batch["status"] == "completed" for batch in batches),
            sum(batch["status"] == "failed" for batch in batches),
            completed_requirements,
            metrics["deterministic_unknowns"],
            metrics["ollama_evaluations"],
            metrics["fireworks_escalations"],
            job_id,
        ),
    )


async def run_job(job_id: str) -> None:
    job = db.row("SELECT * FROM compliance_jobs WHERE id = ?", (job_id,))
    if not job or job["status"] == "completed":
        return
    db.execute(
        "UPDATE compliance_jobs SET status = 'running', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    pending = db.rows(
        """SELECT * FROM compliance_batches WHERE job_id = ? AND status != 'completed'
           ORDER BY batch_index""",
        (job_id,),
    )
    local_semaphore = asyncio.Semaphore(LOCAL_MODEL_CONCURRENCY)
    fireworks_semaphore = asyncio.Semaphore(FIREWORKS_CONCURRENCY)
    queue: asyncio.Queue[dict] = asyncio.Queue()
    for batch in pending:
        queue.put_nowait(batch)
    errors: list[Exception] = []

    async def process(batch: dict) -> None:
        requirement_ids = json.loads(batch["requirement_ids_json"])
        placeholders = ",".join("?" for _ in requirement_ids)
        requirements = db.rows(
            f"""SELECT * FROM requirements WHERE id IN ({placeholders})
                ORDER BY package_order, subcategory_order, page_number, requirement_key""",
            tuple(requirement_ids),
        )
        db.execute(
            """UPDATE compliance_batches SET status = 'running', attempts = attempts + 1,
               error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (batch["id"],),
        )
        try:
            manual_requirements = [
                item for item in requirements if item.get("manual_match_applicable")
            ]
            queries = [
                {"requirement_id": item["id"], "query": item["requirement_text"]}
                for item in manual_requirements
            ]
            retrieval = {"queries": []}
            if queries:
                try:
                    retrieval = await call_catalog_tool(
                        "search_manual_evidence_batch",
                        {"queries": queries, "limit": settings.compliance_retrieval_limit},
                    )
                except Exception:
                    # Supports an already-running pre-v1 MCP server until the user can restart it.
                    legacy_results = await asyncio.gather(*(
                        call_catalog_tool(
                            "search_manual_evidence",
                            {"query": item["query"], "limit": settings.compliance_retrieval_limit},
                        )
                        for item in queries
                    ))
                    retrieval = {
                        "queries": [
                            {
                                "requirement_id": item["requirement_id"],
                                "results": result.get("results", []),
                            }
                            for item, result in zip(queries, legacy_results, strict=True)
                        ]
                    }
            by_requirement = {
                item["requirement_id"]: item.get("results", [])
                for item in retrieval.get("queries", [])
            }
            results = await asyncio.gather(*(
                _evaluate_one(
                    requirement,
                    pre_match_evidence(requirement, by_requirement.get(requirement["id"], [])),
                    local_semaphore,
                    fireworks_semaphore,
                )
                for requirement in requirements
            ))
            assessments = [result[0] for result in results]
            metrics: dict[str, int] = {}
            for _, item_metrics in results:
                for key, value in item_metrics.items():
                    metrics[key] = metrics.get(key, 0) + value
            db.upsert_assessments(assessments, job_id)
            db.execute(
                """UPDATE compliance_batches SET status = 'completed', assessments_json = ?,
                   metrics_json = ?, error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (json.dumps(assessments), json.dumps(metrics), batch["id"]),
            )
            _refresh_counts(job_id)
        except Exception as error:
            error_message = str(error).strip() or type(error).__name__
            db.execute(
                """UPDATE compliance_batches SET status = 'failed', error = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (error_message, batch["id"]),
            )
            _refresh_counts(job_id)
            errors.append(error)

    async def worker() -> None:
        while True:
            try:
                batch = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await process(batch)
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(min(MAX_BATCH_WORKERS, len(pending)))))
    if errors:
        message = f"{len(errors)} compliance batch(es) failed. Resume to retry only those batches."
        db.execute(
            """UPDATE compliance_jobs SET status = 'failed', error = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (message, job_id),
        )
        return
    _refresh_counts(job_id)
    db.execute(
        """UPDATE compliance_jobs SET status = 'completed', completed_batches = total_batches,
           completed_requirements = total_requirements, error = NULL,
           updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (job_id,),
    )
