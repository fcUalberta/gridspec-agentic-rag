import asyncio
import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .compliance_jobs import (
    PIPELINE_VERSION as COMPLIANCE_PIPELINE_VERSION,
)
from .compliance_jobs import (
    create_or_resume_job as create_or_resume_compliance_job,
)
from .compliance_jobs import (
    get_job as get_compliance_job,
)
from .compliance_jobs import (
    latest_job as latest_compliance_job,
)
from .compliance_jobs import (
    run_job as run_compliance_job,
)
from .config import settings
from .extraction_jobs import (
    PIPELINE_VERSION,
    create_or_resume_job,
    get_job,
    latest_job,
    run_job,
)
from .graphs import solution_graph
from .mcp_client import call_catalog_tool
from .pdf import chunk_pages, safe_upload_path


def install_assessment_write_guards() -> None:
    """Allow assessment writes only from the current compliance pipeline."""
    # A stale API process can still finish an older background job against the same
    # SQLite file. Prevent it from overwriting assessments produced by this pipeline.
    db.execute("DROP TRIGGER IF EXISTS guard_outdated_assessment_insert")
    db.execute("DROP TRIGGER IF EXISTS guard_outdated_assessment_update")
    db.execute(
        f"""CREATE TRIGGER guard_outdated_assessment_insert
        BEFORE INSERT ON assessments
        WHEN COALESCE((SELECT pipeline_version FROM compliance_jobs WHERE id = NEW.compliance_job_id), '')
             != '{COMPLIANCE_PIPELINE_VERSION}'
        BEGIN SELECT RAISE(IGNORE); END"""
    )
    db.execute(
        f"""CREATE TRIGGER guard_outdated_assessment_update
        BEFORE UPDATE ON assessments
        WHEN COALESCE((SELECT pipeline_version FROM compliance_jobs WHERE id = NEW.compliance_job_id), '')
             != '{COMPLIANCE_PIPELINE_VERSION}'
        BEGIN SELECT RAISE(IGNORE); END"""
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    install_assessment_write_guards()
    db.execute("UPDATE extraction_batches SET status = 'pending' WHERE status = 'running'")
    db.execute(
        """UPDATE extraction_jobs SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP
           WHERE status = 'running'"""
    )
    for job in db.rows(
        """SELECT id FROM extraction_jobs
           WHERE status IN ('queued', 'interrupted') AND pipeline_version = ?""",
        (PIPELINE_VERSION,),
    ):
        db.execute(
            "UPDATE extraction_jobs SET status = 'queued', error = NULL WHERE id = ?",
            (job["id"],),
        )
        schedule_extraction(job["id"])
    db.execute("UPDATE compliance_batches SET status = 'pending' WHERE status = 'running'")
    db.execute(
        """UPDATE compliance_jobs SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP
           WHERE status = 'running'"""
    )
    for job in db.rows(
        """SELECT id FROM compliance_jobs
           WHERE status IN ('queued', 'interrupted') AND pipeline_version = ?""",
        (COMPLIANCE_PIPELINE_VERSION,),
    ):
        db.execute(
            "UPDATE compliance_jobs SET status = 'queued', error = NULL WHERE id = ?",
            (job["id"],),
        )
        schedule_compliance(job["id"])
    yield
    tasks = list(active_extractions.values()) + list(active_compliance_jobs.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    db.execute("UPDATE extraction_batches SET status = 'pending' WHERE status = 'running'")
    db.execute(
        """UPDATE extraction_jobs SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP
           WHERE status = 'running'"""
    )
    db.execute("UPDATE compliance_batches SET status = 'pending' WHERE status = 'running'")
    db.execute(
        """UPDATE compliance_jobs SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP
           WHERE status = 'running'"""
    )


app = FastAPI(title="GridSpec Pipeline", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def fail(error: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail=str(error))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
async def status() -> dict:
    mcp_ready = False
    indexed_chunks = 0
    if settings.fireworks_api_key:
        try:
            async with asyncio.timeout(5):
                catalog = await call_catalog_tool("catalog_status", {})
            mcp_ready = bool(catalog.get("ready"))
            indexed_chunks = int(catalog.get("indexed_chunks", 0))
        except Exception as error:
            mcp_error = str(error) or type(error).__name__
        else:
            mcp_error = None
    else:
        mcp_error = "FIREWORKS_API_KEY is missing"
    return {
        "configured": bool(settings.fireworks_api_key),
        "model": settings.fireworks_chat_model if settings.fireworks_api_key else None,
        "candidate_model": settings.ollama_candidate_model,
        "provider": "Fireworks AI",
        "extraction_strategy": "PyMuPDF + selective LiteParse + local candidate model",
        "compliance_strategy": "Deterministic pre-match + Ollama-first + selective Fireworks escalation",
        "mcp_ready": mcp_ready,
        "indexed_chunks": indexed_chunks,
        "mcp_error": mcp_error,
    }


@app.get("/documents")
async def list_documents() -> dict:
    return {"documents": db.rows("SELECT * FROM documents ORDER BY created_at DESC")}


@app.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), kind: str = Form(...)) -> dict:
    if kind not in {"rfq", "product"}:
        raise HTTPException(400, "kind must be rfq or product")
    if file.content_type != "application/pdf":
        raise HTTPException(415, "Only PDF documents are supported")
    if not settings.fireworks_api_key:
        raise HTTPException(503, "FIREWORKS_API_KEY is not configured in backend/.env")
    document_id = str(uuid.uuid4())
    target = Path(settings.upload_dir) / safe_upload_path(file.filename or "document.pdf", document_id)
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    byte_size = target.stat().st_size
    db.execute(
        "INSERT INTO documents (id, kind, file_name, path, byte_size, status) VALUES (?, ?, ?, ?, ?, ?)",
        (document_id, kind, file.filename, str(target), byte_size, "uploaded"),
    )
    try:
        if kind == "product":
            chunks = chunk_pages(str(target), document_id, file.filename or "document.pdf")
            for index in range(0, len(chunks), 20):
                await call_catalog_tool("index_product_manual", {"chunks": chunks[index:index + 20]})
            db.execute("UPDATE documents SET status = 'indexed' WHERE id = ?", (document_id,))
        else:
            db.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (document_id,))
    except Exception as error:
        db.execute("UPDATE documents SET status = 'failed', error = ? WHERE id = ?", (str(error), document_id))
        raise fail(error)
    return {"document": db.row("SELECT * FROM documents WHERE id = ?", (document_id,))}


class ExtractRequest(BaseModel):
    documentId: str


active_extractions: dict[str, asyncio.Task] = {}
active_compliance_jobs: dict[str, asyncio.Task] = {}


async def run_extraction_safely(job_id: str) -> None:
    try:
        await run_job(job_id)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        job = get_job(job_id)
        db.execute(
            """UPDATE extraction_jobs SET status = 'failed', error = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (str(error), job_id),
        )
        if job:
            db.execute(
                "UPDATE documents SET status = 'extraction_failed', error = ? WHERE id = ?",
                (str(error), job["document_id"]),
            )


def schedule_extraction(job_id: str) -> None:
    current = active_extractions.get(job_id)
    if current and not current.done():
        return
    task = asyncio.create_task(run_extraction_safely(job_id))
    active_extractions[job_id] = task
    task.add_done_callback(lambda _: active_extractions.pop(job_id, None))


async def run_compliance_safely(job_id: str) -> None:
    try:
        await run_compliance_job(job_id)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        db.execute(
            """UPDATE compliance_jobs SET status = 'failed', error = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (str(error), job_id),
        )


def schedule_compliance(job_id: str) -> None:
    current = active_compliance_jobs.get(job_id)
    if current and not current.done():
        return
    task = asyncio.create_task(run_compliance_safely(job_id))
    active_compliance_jobs[job_id] = task
    task.add_done_callback(lambda _: active_compliance_jobs.pop(job_id, None))


@app.post("/extract", status_code=202)
async def extract(documentId: str = Form(...), force: bool = Form(False)) -> dict:
    try:
        job = create_or_resume_job(documentId, force=force)
        if job["status"] != "completed":
            schedule_extraction(job["id"])
        return {"job": get_job(job["id"]), "model": settings.fireworks_chat_model}
    except Exception as error:
        raise fail(error) from error


@app.get("/extractions/latest")
async def latest_extraction(documentId: str | None = None) -> dict:
    return {"job": latest_job(documentId)}


@app.get("/extractions/{job_id}")
async def extraction_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Extraction job not found")
    return {"job": job}


def serialize_requirements() -> list[dict]:
    result = db.rows(
        """SELECT * FROM requirements
           ORDER BY package_order, subcategory_order,
                    CASE WHEN page_number IS NULL THEN 1 ELSE 0 END,
                    page_number, requirement_key"""
    )
    for item in result:
        item["section"] = item.pop("section_name")
        item["source_bbox"] = json.loads(item.pop("source_bbox_json") or "null")
    return result


@app.get("/requirements")
async def requirements() -> dict:
    return {"requirements": serialize_requirements()}


class RequirementReview(BaseModel):
    id: str
    requirementText: str | None = None
    reviewStatus: str = "Edited"
    note: str | None = None


@app.patch("/requirements")
async def review_requirement(payload: RequirementReview) -> dict:
    current = db.row("SELECT * FROM requirements WHERE id = ?", (payload.id,))
    if not current:
        raise HTTPException(404, "Requirement not found")
    requirement_text = payload.requirementText or current["requirement_text"]
    from .taxonomy import classify_requirement

    classification = classify_requirement({**current, "requirement_text": requirement_text})
    db.execute(
        """UPDATE requirements SET requirement_text = ?, review_status = ?, engineer_note = ?,
           solution_package = ?, package_order = ?, subcategory = ?, subcategory_order = ?,
           compliance_object = ?, requirement_type = ?, lifecycle_phase = ?, evidence_scope = ?,
           expected_evidence = ?, manual_match_applicable = ?, classification_version = ?
           WHERE id = ?""",
        (
            requirement_text,
            payload.reviewStatus,
            payload.note,
            classification["solution_package"],
            classification["package_order"],
            classification["subcategory"],
            classification["subcategory_order"],
            classification["compliance_object"],
            classification["requirement_type"],
            classification["lifecycle_phase"],
            classification["evidence_scope"],
            classification["expected_evidence"],
            classification["manual_match_applicable"],
            classification["classification_version"],
            payload.id,
        ),
    )
    db.execute(
        "INSERT INTO audit_events VALUES (?, 'requirement', ?, ?, ?, CURRENT_TIMESTAMP)",
        (str(uuid.uuid4()), payload.id, payload.reviewStatus, payload.note),
    )
    return {"status": "recorded"}


def serialize_assessments() -> list[dict]:
    result = db.rows("SELECT * FROM assessments ORDER BY created_at")
    for item in result:
        item["evidence"] = json.loads(item.pop("evidence_json"))
        item["alternate"] = json.loads(item.pop("alternate_json"))
    return result


@app.get("/compliance")
async def compliance_results() -> dict:
    return {"assessments": serialize_assessments()}


@app.post("/compliance", status_code=202)
async def run_compliance(force: bool = False) -> dict:
    try:
        job = create_or_resume_compliance_job(force=force)
        if job["status"] != "completed":
            schedule_compliance(job["id"])
        return {"job": get_compliance_job(job["id"])}
    except Exception as error:
        raise fail(error) from error


@app.get("/compliance/jobs/latest")
async def latest_compliance() -> dict:
    return {"job": latest_compliance_job()}


@app.get("/compliance/jobs/{job_id}")
async def compliance_status(job_id: str) -> dict:
    job = get_compliance_job(job_id)
    if not job:
        raise HTTPException(404, "Compliance job not found")
    return {"job": job}


@app.get("/solution")
async def latest_solution() -> dict:
    record = db.row("SELECT * FROM solutions ORDER BY created_at DESC LIMIT 1")
    return {"solution": {**record, "data": json.loads(record["solution_json"])} if record else None}


@app.post("/solution")
async def run_solution() -> dict:
    compliance = latest_compliance_job()
    if not compliance or compliance["status"] != "completed" or compliance.get("stale"):
        raise HTTPException(
            status_code=409,
            detail="Complete the current compliance run before generating a cohesive solution",
        )
    try:
        result = await solution_graph.ainvoke({})
        return {"solution": result["solution"], "model": settings.fireworks_chat_model}
    except Exception as error:
        raise fail(error) from error
