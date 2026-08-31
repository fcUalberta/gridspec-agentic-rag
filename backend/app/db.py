import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, file_name TEXT NOT NULL, path TEXT NOT NULL,
  byte_size INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS requirements (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, requirement_key TEXT NOT NULL, section_name TEXT NOT NULL,
  requirement_text TEXT NOT NULL, source_quote TEXT NOT NULL, source_bbox_json TEXT, page_number INTEGER,
  category TEXT NOT NULL,
  criticality TEXT NOT NULL, confidence INTEGER NOT NULL, review_status TEXT NOT NULL DEFAULT 'Extracted',
  engineer_note TEXT, solution_package TEXT NOT NULL DEFAULT 'Generic / Unclassified',
  package_order INTEGER NOT NULL DEFAULT 10, subcategory TEXT NOT NULL DEFAULT 'Generic / Other',
  subcategory_order INTEGER NOT NULL DEFAULT 120, compliance_object TEXT NOT NULL DEFAULT '',
  requirement_type TEXT NOT NULL DEFAULT 'Generic / Other', lifecycle_phase TEXT NOT NULL DEFAULT 'Design and supply',
  evidence_scope TEXT NOT NULL DEFAULT 'engineer_confirmation',
  expected_evidence TEXT NOT NULL DEFAULT 'Engineer confirmation',
  manual_match_applicable INTEGER NOT NULL DEFAULT 0, classification_version TEXT NOT NULL DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS assessments (
  id TEXT PRIMARY KEY, requirement_id TEXT NOT NULL, decision TEXT NOT NULL, product_name TEXT NOT NULL,
  rationale TEXT NOT NULL, evidence_json TEXT NOT NULL, alternate_json TEXT NOT NULL,
  confidence INTEGER NOT NULL, review_status TEXT NOT NULL DEFAULT 'Needs review', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS solutions (
  id TEXT PRIMARY KEY, solution_json TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'Needs review',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL,
  note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS extraction_jobs (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, status TEXT NOT NULL,
  total_batches INTEGER NOT NULL DEFAULT 0, completed_batches INTEGER NOT NULL DEFAULT 0,
  failed_batches INTEGER NOT NULL DEFAULT 0, requirements_found INTEGER NOT NULL DEFAULT 0,
  pipeline_version TEXT NOT NULL DEFAULT 'legacy', error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS extraction_batches (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, batch_index INTEGER NOT NULL,
  start_page INTEGER NOT NULL, end_page INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, requirements_json TEXT, error TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(job_id, batch_index)
);
CREATE TABLE IF NOT EXISTS compliance_jobs (
  id TEXT PRIMARY KEY, status TEXT NOT NULL, input_hash TEXT NOT NULL,
  total_batches INTEGER NOT NULL DEFAULT 0, completed_batches INTEGER NOT NULL DEFAULT 0,
  failed_batches INTEGER NOT NULL DEFAULT 0, total_requirements INTEGER NOT NULL DEFAULT 0,
  completed_requirements INTEGER NOT NULL DEFAULT 0, deterministic_unknowns INTEGER NOT NULL DEFAULT 0,
  ollama_evaluations INTEGER NOT NULL DEFAULT 0, fireworks_escalations INTEGER NOT NULL DEFAULT 0,
  pipeline_version TEXT NOT NULL, error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS compliance_batches (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, batch_index INTEGER NOT NULL,
  requirement_ids_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, assessments_json TEXT, metrics_json TEXT, error TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(job_id, batch_index)
);
CREATE INDEX IF NOT EXISTS idx_compliance_jobs_status ON compliance_jobs(status);
CREATE INDEX IF NOT EXISTS idx_compliance_batches_job_status ON compliance_batches(job_id, status);
CREATE INDEX IF NOT EXISTS idx_assessments_requirement_id ON assessments(requirement_id);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        requirement_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(requirements)").fetchall()
        }
        if "source_bbox_json" not in requirement_columns:
            conn.execute("ALTER TABLE requirements ADD COLUMN source_bbox_json TEXT")
        requirement_migrations = {
            "solution_package": "TEXT NOT NULL DEFAULT 'Generic / Unclassified'",
            "package_order": "INTEGER NOT NULL DEFAULT 10",
            "subcategory": "TEXT NOT NULL DEFAULT 'Generic / Other'",
            "subcategory_order": "INTEGER NOT NULL DEFAULT 120",
            "compliance_object": "TEXT NOT NULL DEFAULT ''",
            "requirement_type": "TEXT NOT NULL DEFAULT 'Generic / Other'",
            "lifecycle_phase": "TEXT NOT NULL DEFAULT 'Design and supply'",
            "evidence_scope": "TEXT NOT NULL DEFAULT 'engineer_confirmation'",
            "expected_evidence": "TEXT NOT NULL DEFAULT 'Engineer confirmation'",
            "manual_match_applicable": "INTEGER NOT NULL DEFAULT 0",
            "classification_version": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in requirement_migrations.items():
            if column not in requirement_columns:
                conn.execute(f"ALTER TABLE requirements ADD COLUMN {column} {definition}")
        job_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(extraction_jobs)").fetchall()
        }
        if "pipeline_version" not in job_columns:
            conn.execute(
                "ALTER TABLE extraction_jobs ADD COLUMN pipeline_version TEXT NOT NULL DEFAULT 'legacy'"
            )
        assessment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(assessments)").fetchall()
        }
        if "evaluation_method" not in assessment_columns:
            conn.execute(
                "ALTER TABLE assessments ADD COLUMN evaluation_method TEXT NOT NULL DEFAULT 'legacy'"
            )
        if "compliance_job_id" not in assessment_columns:
            conn.execute("ALTER TABLE assessments ADD COLUMN compliance_job_id TEXT")
        conn.execute(
            """UPDATE requirements SET review_status = 'Extracted'
               WHERE review_status IN ('Needs review', 'Approved', 'Rejected')"""
        )
        from .taxonomy import TAXONOMY_VERSION, classify_requirement

        for requirement in conn.execute(
            "SELECT * FROM requirements WHERE classification_version != ?",
            (TAXONOMY_VERSION,),
        ).fetchall():
            classification = classify_requirement(dict(requirement))
            conn.execute(
                """UPDATE requirements SET solution_package = ?, package_order = ?,
                   subcategory = ?, subcategory_order = ?, compliance_object = ?,
                   requirement_type = ?, lifecycle_phase = ?, evidence_scope = ?,
                   expected_evidence = ?, manual_match_applicable = ?, classification_version = ?
                   WHERE id = ?""",
                (
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
                    requirement["id"],
                ),
            )
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_requirements_cohesive_order
               ON requirements(package_order, subcategory_order, page_number, requirement_key)"""
        )
        conn.execute("PRAGMA optimize")


def rows(query: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def row(query: str, params: tuple = ()) -> dict | None:
    result = rows(query, params)
    return result[0] if result else None


def execute(query: str, params: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(query, params)


def replace_requirements(document_id: str, requirements: list[dict]) -> list[dict]:
    from .taxonomy import classify_requirement

    with connect() as conn:
        previous: dict[tuple[int | None, str], list[dict]] = {}
        for row in conn.execute(
            """SELECT id, page_number, source_quote, review_status, engineer_note
               FROM requirements WHERE document_id = ?""",
            (document_id,),
        ).fetchall():
            key = (row["page_number"], " ".join(row["source_quote"].lower().split()))
            previous.setdefault(key, []).append(dict(row))
        conn.execute("DELETE FROM requirements WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM assessments")
        conn.execute("DELETE FROM solutions")
        inserted = []
        for item in requirements:
            classification = classify_requirement(item)
            key = (
                item.get("page_number"),
                " ".join(item["source_quote"].lower().split()),
            )
            matched = previous.get(key, []).pop(0) if previous.get(key) else None
            requirement_id = matched["id"] if matched else str(uuid.uuid4())
            review_status = (
                matched["review_status"]
                if matched and matched["review_status"] == "Edited"
                else "Extracted"
            )
            engineer_note = matched["engineer_note"] if matched else None
            conn.execute(
                """INSERT INTO requirements
                   (id, document_id, requirement_key, section_name, requirement_text,
                    source_quote, source_bbox_json, page_number, category, criticality,
                    confidence, review_status, engineer_note, solution_package, package_order,
                    subcategory, subcategory_order, compliance_object, requirement_type,
                    lifecycle_phase, evidence_scope, expected_evidence, manual_match_applicable,
                    classification_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    requirement_id,
                    document_id,
                    item["requirement_key"],
                    item["section"],
                    item["requirement_text"],
                    item["source_quote"],
                    json.dumps(item.get("source_bbox")),
                    item.get("page_number"),
                    item["category"],
                    item["criticality"],
                    item["confidence"],
                    review_status,
                    engineer_note,
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
                ),
            )
            inserted.append({
                "id": requirement_id,
                **item,
                **classification,
                "review_status": review_status,
            })
        return inserted


def replace_assessments(assessments: list[dict]) -> list[dict]:
    with connect() as conn:
        conn.execute("DELETE FROM assessments")
        inserted = []
        for item in assessments:
            assessment_id = str(uuid.uuid4())
            alternate = None
            if item.get("alternate_product"):
                alternate = {"product_name": item["alternate_product"], "rationale": item.get("alternate_rationale") or ""}
            conn.execute(
                "INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Needs review', CURRENT_TIMESTAMP)",
                (assessment_id, item["requirement_id"], item["decision"], item["product_name"], item["rationale"],
                 json.dumps(item["evidence"]), json.dumps(alternate), item["confidence"]),
            )
            inserted.append({"id": assessment_id, **item, "alternate": alternate, "review_status": "Needs review"})
        return inserted


def upsert_assessments(assessments: list[dict], job_id: str) -> list[dict]:
    """Persist completed requirement decisions without replacing other checkpoints."""
    with connect() as conn:
        inserted = []
        for item in assessments:
            conn.execute("DELETE FROM assessments WHERE requirement_id = ?", (item["requirement_id"],))
            assessment_id = str(uuid.uuid4())
            alternate = None
            if item.get("alternate_product"):
                alternate = {
                    "product_name": item["alternate_product"],
                    "rationale": item.get("alternate_rationale") or "",
                }
            conn.execute(
                """INSERT INTO assessments
                   (id, requirement_id, decision, product_name, rationale, evidence_json,
                    alternate_json, confidence, review_status, created_at,
                    evaluation_method, compliance_job_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Needs review', CURRENT_TIMESTAMP, ?, ?)""",
                (
                    assessment_id,
                    item["requirement_id"],
                    item["decision"],
                    item.get("product_name", ""),
                    item["rationale"],
                    json.dumps(item.get("evidence", [])),
                    json.dumps(alternate),
                    item["confidence"],
                    item.get("evaluation_method", "unknown"),
                    job_id,
                ),
            )
            inserted.append({
                "id": assessment_id,
                **item,
                "alternate": alternate,
                "review_status": "Needs review",
                "compliance_job_id": job_id,
            })
        return inserted


initialize()
