import asyncio
import json
import re
import uuid

from . import db
from .agents import (
    StructuredOutputFailure,
    interpret_requirement_candidates,
    validate_and_dedupe_requirements,
)
from .candidates import direct_requirement, requirement_candidates
from .config import settings
from .pdf import extract_pages

PIPELINE_VERSION = "controlled-v2"
MAX_CONCURRENCY = 3
MAX_PAGES_PER_BATCH = 12
CANDIDATE_CHARACTER_TARGET = 12000

OBLIGATION_RE = re.compile(
    r"\b(shall|must|required|requires?|supplier|vendor|contractor|provide|furnish|install|"
    r"design|submit|include|comply|capable|rated)\b",
    re.IGNORECASE,
)
TECHNICAL_RE = re.compile(
    r"\b(relay|panel|protection|control|breaker|substation|transformer|bus|feeder|trip|"
    r"interlock|scada|iec\s*61850|dnp3|modbus|ethernet|fiber|ct|vt|current transformer|"
    r"voltage transformer|dc|battery|wiring|terminal|meter|alarm|synchroni[sz]|testing|fat)\b",
    re.IGNORECASE,
)
TABLE_RE = re.compile(r"(?:\|.*\|)|(?:\b\d+(?:\.\d+)?\s*(?:v|kv|a|ka|hz|ms|mm|°c)\b)", re.IGNORECASE)


def _page_signals(page: dict) -> tuple[int, int, int]:
    text = page["text"]
    return (
        len(OBLIGATION_RE.findall(text)),
        len(TECHNICAL_RE.findall(text)),
        len(TABLE_RE.findall(text)),
    )


def _is_relevant(page: dict) -> bool:
    if requirement_candidates(page):
        return True
    obligations, technical, table = _page_signals(page)
    return (
        (obligations >= 2 and technical >= 2)
        or technical >= 10
        or (technical >= 3 and table >= 5)
    )


def _triage_pages(pages: list[dict]) -> list[dict]:
    """Retain pages with strong evidence of technical supplier requirements."""
    return [page for page in pages if _is_relevant(page)]


def _dynamic_batches(pages: list[dict]) -> list[list[dict]]:
    """Batch compact candidates rather than sending full RFQ pages to a model."""
    if not pages:
        return []
    batches = []
    current: list[dict] = []
    current_characters = 0
    for page in pages:
        candidates = requirement_candidates(page)
        ambiguous_characters = sum(
            len(candidate["source_quote"])
            for candidate in candidates
            if candidate["candidate_type"] != "explicit"
        )
        would_overflow = current and (
            current_characters + ambiguous_characters > CANDIDATE_CHARACTER_TARGET
            or len(current) >= MAX_PAGES_PER_BATCH
        )
        if would_overflow:
            batches.append(current)
            current = []
            current_characters = 0
        current.append(page)
        current_characters += ambiguous_characters
    if current:
        batches.append(current)
    return batches


def _page_batches(pages: list[dict]) -> list[list[dict]]:
    return _dynamic_batches(_triage_pages(pages))


def _is_complex(pages: list[dict]) -> bool:
    if any(page.get("layout_complexity") for page in pages):
        return True
    obligations = technical = tables = 0
    for page in pages:
        page_obligations, page_technical, page_tables = _page_signals(page)
        obligations += page_obligations
        technical += page_technical
        tables += page_tables
    return tables >= 30 or obligations >= 35 or technical >= 100


def serialize_job(job: dict | None) -> dict | None:
    if not job:
        return None
    total = int(job["total_batches"])
    completed = int(job["completed_batches"])
    job["progress_percent"] = round(completed / total * 100) if total else 0
    states = db.row(
        """SELECT
           SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS active,
           SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending
           FROM extraction_batches WHERE job_id = ?""",
        (job["id"],),
    )
    job["active_batches"] = int(states["active"] or 0) if states else 0
    job["pending_batches"] = int(states["pending"] or 0) if states else 0
    current = db.row(
        """SELECT start_page, end_page FROM extraction_batches
           WHERE job_id = ? AND status = 'running' ORDER BY batch_index LIMIT 1""",
        (job["id"],),
    )
    job["current_page_range"] = (
        f"{current['start_page']}-{current['end_page']}" if current else None
    )
    return job


def _replan_remaining_batches(job_id: str, pages: list[dict]) -> None:
    """Preserve checkpoints while rebuilding unfinished work with the current strategy."""
    completed = db.rows(
        """SELECT start_page, end_page FROM extraction_batches
           WHERE job_id = ? AND status = 'completed'""",
        (job_id,),
    )
    covered = {
        page_number
        for batch in completed
        for page_number in range(batch["start_page"], batch["end_page"] + 1)
    }
    relevant_remaining = [
        page for page in _triage_pages(pages) if page["page_number"] not in covered
    ]
    desired = _dynamic_batches(relevant_remaining)
    last = db.row(
        """SELECT COALESCE(MAX(batch_index), -1) AS value FROM extraction_batches
           WHERE job_id = ? AND status = 'completed'""",
        (job_id,),
    )
    next_index = int(last["value"]) + 1

    db.execute("DELETE FROM extraction_batches WHERE job_id = ? AND status != 'completed'", (job_id,))
    for offset, batch in enumerate(desired):
        db.execute(
            """INSERT INTO extraction_batches
               (id, job_id, batch_index, start_page, end_page, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (
                str(uuid.uuid4()), job_id, next_index + offset,
                batch[0]["page_number"], batch[-1]["page_number"],
            ),
        )
    completed_count = len(completed)
    db.execute(
        """UPDATE extraction_jobs SET total_batches = ?, completed_batches = ?,
           failed_batches = 0, requirements_found = 0, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (completed_count + len(desired), completed_count, job_id),
    )
    _refresh_counts(job_id)


def get_job(job_id: str) -> dict | None:
    return serialize_job(db.row("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,)))


def latest_job(document_id: str | None = None) -> dict | None:
    if document_id:
        return serialize_job(db.row(
            "SELECT * FROM extraction_jobs WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
            (document_id,),
        ))
    return serialize_job(db.row("SELECT * FROM extraction_jobs ORDER BY created_at DESC LIMIT 1"))


def create_or_resume_job(document_id: str, force: bool = False) -> dict:
    document = db.row("SELECT * FROM documents WHERE id = ? AND kind = 'rfq'", (document_id,))
    if not document:
        raise ValueError("RFQ document not found")

    existing = None if force else latest_job(document_id)
    if existing and existing.get("pipeline_version") != PIPELINE_VERSION:
        existing = None
    if existing and existing["status"] in {"queued", "running", "failed", "interrupted"}:
        if existing["status"] in {"failed", "interrupted"}:
            db.execute(
                """UPDATE extraction_jobs SET status = 'queued', failed_batches = 0, error = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (existing["id"],),
            )
            db.execute(
                """UPDATE extraction_batches SET status = 'pending', error = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE job_id = ? AND status != 'completed'""",
                (existing["id"],),
            )
        return get_job(existing["id"])
    if existing and existing["status"] == "completed":
        return existing

    pages = extract_pages(document["path"], include_complex_layout=True)
    batches = _page_batches(pages)
    job_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO extraction_jobs
           (id, document_id, status, total_batches, pipeline_version)
           VALUES (?, ?, 'queued', ?, ?)""",
        (job_id, document_id, len(batches), PIPELINE_VERSION),
    )
    for index, batch in enumerate(batches):
        db.execute(
            """INSERT INTO extraction_batches
               (id, job_id, batch_index, start_page, end_page, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (str(uuid.uuid4()), job_id, index, batch[0]["page_number"], batch[-1]["page_number"]),
        )
    db.execute("UPDATE documents SET status = 'extraction_queued', error = NULL WHERE id = ?", (document_id,))
    return get_job(job_id)


async def _extract_resilient(pages: list[dict], semaphore: asyncio.Semaphore) -> list[dict]:
    candidates = [
        candidate
        for page in pages
        for candidate in requirement_candidates(page)
    ]
    direct = [
        direct_requirement(candidate)
        for candidate in candidates
        if candidate["candidate_type"] == "explicit"
    ]
    ambiguous = [
        candidate
        for candidate in candidates
        if candidate["candidate_type"] != "explicit"
    ]
    if not ambiguous:
        return direct
    try:
        async with semaphore:
            interpreted = await interpret_requirement_candidates(
                ambiguous,
                model_name=settings.ollama_candidate_model,
                provider="ollama",
            )
            return direct + interpreted
    except Exception as local_error:
        final_error = local_error
        try:
            async with semaphore:
                interpreted = await interpret_requirement_candidates(
                    ambiguous,
                    model_name=settings.fireworks_chat_model,
                    provider="fireworks",
                )
                return direct + interpreted
        except Exception as primary_error:
            final_error = primary_error
        if isinstance(final_error, StructuredOutputFailure) and _is_complex(pages):
            try:
                async with semaphore:
                    interpreted = await interpret_requirement_candidates(
                        ambiguous,
                        model_name=settings.fireworks_strong_model,
                        provider="fireworks",
                    )
                    return direct + interpreted
            except Exception as fallback_error:
                final_error = fallback_error
        if len(pages) == 1:
            if isinstance(final_error, StructuredOutputFailure):
                raise ValueError(
                    f"Requirement extraction could not parse RFQ page {pages[0]['page_number']} after retries."
                ) from final_error
            raise RuntimeError(str(final_error)) from final_error
        midpoint = len(pages) // 2
        left, right = await asyncio.gather(
            _extract_resilient(pages[:midpoint], semaphore),
            _extract_resilient(pages[midpoint:], semaphore),
        )
        return left + right


def _refresh_counts(job_id: str) -> None:
    counts = db.row(
        """SELECT COUNT(*) AS total,
           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
           SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
           FROM extraction_batches WHERE job_id = ?""",
        (job_id,),
    )
    found = db.row(
        """SELECT COALESCE(SUM(json_array_length(requirements_json)), 0) AS count
           FROM extraction_batches WHERE job_id = ? AND status = 'completed'""",
        (job_id,),
    )
    db.execute(
        """UPDATE extraction_jobs SET total_batches = ?, completed_batches = ?, failed_batches = ?,
           requirements_found = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (counts["total"], counts["completed"] or 0, counts["failed"] or 0, found["count"], job_id),
    )


async def run_job(job_id: str) -> None:
    job = db.row("SELECT * FROM extraction_jobs WHERE id = ?", (job_id,))
    if not job or job["status"] == "completed":
        return
    document = db.row("SELECT * FROM documents WHERE id = ?", (job["document_id"],))
    if not document:
        return

    db.execute(
        "UPDATE extraction_jobs SET status = 'running', error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    db.execute("UPDATE documents SET status = 'extracting', error = NULL WHERE id = ?", (job["document_id"],))
    pages = extract_pages(document["path"], include_complex_layout=True)
    _replan_remaining_batches(job_id, pages)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    pending = db.rows(
        "SELECT * FROM extraction_batches WHERE job_id = ? AND status != 'completed' ORDER BY batch_index",
        (job_id,),
    )

    async def process(batch: dict) -> Exception | None:
        page_batch = [
            page for page in pages
            if batch["start_page"] <= page["page_number"] <= batch["end_page"]
        ]
        db.execute(
            """UPDATE extraction_batches SET status = 'running', attempts = attempts + 1,
               error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (batch["id"],),
        )
        try:
            requirements = await _extract_resilient(page_batch, semaphore)
            db.execute(
                """UPDATE extraction_batches SET status = 'completed', requirements_json = ?, error = NULL,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (json.dumps(requirements), batch["id"]),
            )
            _refresh_counts(job_id)
            return None
        except Exception as error:
            db.execute(
                """UPDATE extraction_batches SET status = 'failed', error = ?,
                   updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
                (str(error), batch["id"]),
            )
            _refresh_counts(job_id)
            return error

    queue: asyncio.Queue[dict] = asyncio.Queue()
    for batch in pending:
        queue.put_nowait(batch)
    results: list[Exception | None] = []

    async def worker() -> None:
        while True:
            try:
                batch = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                results.append(await process(batch))
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(min(MAX_CONCURRENCY, len(pending)))))
    errors = [error for error in results if error]
    if errors:
        message = f"{len(errors)} extraction batch(es) failed. Resume to retry only those batches."
        db.execute(
            """UPDATE extraction_jobs SET status = 'failed', error = ?,
               updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (message, job_id),
        )
        db.execute(
            "UPDATE documents SET status = 'extraction_failed', error = ? WHERE id = ?",
            (message, job["document_id"]),
        )
        return

    extracted = []
    for batch in db.rows(
        "SELECT requirements_json FROM extraction_batches WHERE job_id = ? ORDER BY batch_index",
        (job_id,),
    ):
        extracted.extend(json.loads(batch["requirements_json"] or "[]"))
    requirements = validate_and_dedupe_requirements(extracted, pages)
    persisted = db.replace_requirements(job["document_id"], requirements)
    db.execute(
        """UPDATE extraction_jobs SET status = 'completed', completed_batches = total_batches,
           requirements_found = ?, error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (len(persisted), job_id),
    )
    db.execute(
        "UPDATE documents SET status = 'extracted', error = NULL WHERE id = ?",
        (job["document_id"],),
    )
