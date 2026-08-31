import asyncio
import json

from app import compliance_jobs, db
from app.config import settings


def setup_database(monkeypatch, tmp_path, requirement_count: int = 2) -> None:
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "compliance.db"))
    db.initialize()
    db.execute(
        """INSERT INTO documents (id, kind, file_name, path, byte_size, status)
           VALUES ('manual-1', 'product', 'relay.pdf', 'relay.pdf', 100, 'indexed')"""
    )
    for index in range(requirement_count):
        db.execute(
            """INSERT INTO requirements
               (id, document_id, requirement_key, section_name, requirement_text, source_quote,
                page_number, category, criticality, confidence, review_status,
                solution_package, package_order, subcategory, subcategory_order,
                compliance_object, requirement_type, lifecycle_phase, evidence_scope,
                expected_evidence, manual_match_applicable, classification_version)
               VALUES (?, 'rfq-1', ?, 'Relay', ?, ?, 1, 'Protection and Control',
                       'Mandatory', 90, 'Extracted', 'Protection and Control System', 2,
                       'Functional requirements', 30, 'Protection relay / IED',
                       'Functional requirements', 'Supply', 'product_manual',
                       'Product manual or certified datasheet', 1, 'test')""",
            (
                f"req-{index}",
                f"REQ-{index + 1:03d}",
                f"The relay shall support IEC 61850 function {index}.",
                f"The relay shall support IEC 61850 function {index}.",
            ),
        )


def test_pre_match_rejects_missing_hard_value(monkeypatch) -> None:
    monkeypatch.setattr(settings, "compliance_vector_threshold", 0.3)
    monkeypatch.setattr(settings, "compliance_lexical_threshold", 0.01)
    requirement = {"requirement_text": "The relay shall accept 115 V IEC 61850 inputs."}
    retrieved = [{
        "text": "The relay accepts 230 V inputs and supports IEC 61850.",
        "score": 0.9,
    }]

    assert compliance_jobs.pre_match_evidence(requirement, retrieved) == []


def test_no_evidence_checkpoints_unknown_without_model(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path)

    async def no_results(_name: str, arguments: dict) -> dict:
        return {
            "queries": [
                {"requirement_id": item["requirement_id"], "results": []}
                for item in arguments["queries"]
            ]
        }

    async def unexpected_model(*_args, **_kwargs) -> dict:
        raise AssertionError("No-evidence requirements must not call a model")

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", no_results)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", unexpected_model)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    completed = compliance_jobs.get_job(job["id"])
    assessments = db.rows("SELECT * FROM assessments ORDER BY requirement_id")
    assert completed["status"] == "completed"
    assert completed["completed_requirements"] == 2
    assert completed["deterministic_unknowns"] == 2
    assert {item["decision"] for item in assessments} == {"Unknown"}
    assert {item["evaluation_method"] for item in assessments} == {"deterministic-no-evidence"}


def test_system_design_requirement_bypasses_catalog_and_models(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    db.execute(
        """UPDATE requirements SET evidence_scope = 'system_design',
           expected_evidence = 'System architecture drawing', manual_match_applicable = 0
           WHERE id = 'req-0'"""
    )

    async def unexpected_call(*_args, **_kwargs) -> dict:
        raise AssertionError("System-design review must not call catalog retrieval or a model")

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", unexpected_call)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", unexpected_call)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    assessment = db.row("SELECT * FROM assessments WHERE requirement_id = 'req-0'")
    assert assessment["decision"] == "Unknown"
    assert assessment["evaluation_method"] == "system-design-review"
    assert "architecture" in assessment["rationale"].lower()


def test_hybrid_positive_requires_architecture_evidence() -> None:
    requirement = {"evidence_scope": "hybrid"}
    result = {
        "decision": "Compliant",
        "confidence": 94,
        "rationale": "The product manual confirms redundant communications.",
    }

    scoped = compliance_jobs._apply_evidence_scope(requirement, result)

    assert scoped["decision"] == "Conditional"
    assert scoped["confidence"] == 85
    assert "architecture or schematic" in scoped["rationale"].lower()


def test_local_timeout_does_not_spend_a_fireworks_call(monkeypatch) -> None:
    requirement = {
        "id": "req-timeout",
        "manual_match_applicable": 1,
        "evidence_scope": "product_manual",
    }

    async def slow_local(*_args, **_kwargs) -> dict:
        await asyncio.sleep(0.05)
        raise AssertionError("The application deadline should cancel this evaluation")

    monkeypatch.setattr(compliance_jobs, "LOCAL_EVALUATION_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", slow_local)
    result, metrics = asyncio.run(
        compliance_jobs._evaluate_one(
            requirement,
            [{"text": "evidence"}],
            asyncio.Semaphore(1),
            asyncio.Semaphore(1),
        )
    )

    assert result["decision"] == "Unknown"
    assert result["evaluation_method"] == "ollama-timeout"
    assert metrics == {"ollama_evaluations": 1}


def test_noncompliant_local_decision_escalates_to_fireworks(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    monkeypatch.setattr(settings, "compliance_vector_threshold", 0.1)
    monkeypatch.setattr(settings, "compliance_lexical_threshold", 0.01)

    async def retrieval(_name: str, arguments: dict) -> dict:
        return {"queries": [{
            "requirement_id": arguments["queries"][0]["requirement_id"],
            "results": [{
                "file_name": "relay.pdf",
                "page_number": 10,
                "text": "The relay supports IEC 61850 function 0.",
                "score": 0.91,
            }],
        }]}

    providers = []

    async def evaluation(requirement: dict, _evidence: list[dict], provider: str) -> dict:
        providers.append(provider)
        return {
            "requirement_id": requirement["id"],
            "decision": "Non-compliant" if provider == "ollama" else "Compliant",
            "product_name": "Relay",
            "rationale": "Controlled test decision.",
            "evidence": [{
                "file_name": "relay.pdf", "quote": "IEC 61850", "location": "Page 10", "score": 0.91,
            }],
            "alternate_product": None,
            "alternate_rationale": None,
            "confidence": 90,
            "needs_escalation": False,
            "escalation_reason": None,
            "evaluation_method": provider,
        }

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", retrieval)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", evaluation)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    completed = compliance_jobs.get_job(job["id"])
    assessment = db.row("SELECT * FROM assessments WHERE requirement_id = 'req-0'")
    assert providers == ["ollama", "fireworks"]
    assert completed["fireworks_escalations"] == 1
    assert assessment["decision"] == "Compliant"
    assert assessment["evaluation_method"] == "fireworks-escalation"


def test_low_confidence_local_positive_with_evidence_does_not_escalate(
    monkeypatch, tmp_path
) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    monkeypatch.setattr(settings, "compliance_vector_threshold", 0.1)
    monkeypatch.setattr(settings, "compliance_lexical_threshold", 0.01)

    async def retrieval(_name: str, arguments: dict) -> dict:
        return {"queries": [{
            "requirement_id": arguments["queries"][0]["requirement_id"],
            "results": [{
                "file_name": "relay.pdf", "page_number": 10,
                "text": "The relay supports IEC 61850 function 0.", "score": 0.91,
            }],
        }]}

    providers = []

    async def evaluation(requirement: dict, _evidence: list[dict], provider: str) -> dict:
        providers.append(provider)
        return {
            "requirement_id": requirement["id"], "decision": "Compliant",
            "product_name": "Relay", "rationale": "Explicitly supported.",
            "evidence": [{
                "file_name": "relay.pdf", "quote": "IEC 61850",
                "location": "Page 10", "score": 0.91,
            }],
            "alternate_product": None, "alternate_rationale": None,
            "confidence": 0, "needs_escalation": False,
            "escalation_reason": None, "evaluation_method": provider,
        }

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", retrieval)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", evaluation)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    assessment = db.row("SELECT * FROM assessments WHERE requirement_id = 'req-0'")
    assert providers == ["ollama"]
    assert assessment["evaluation_method"] == "ollama"


def test_preferred_noncompliance_routes_to_engineer_instead_of_cloud(
    monkeypatch, tmp_path
) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    db.execute("UPDATE requirements SET criticality = 'Preferred' WHERE id = 'req-0'")
    monkeypatch.setattr(settings, "compliance_vector_threshold", 0.1)
    monkeypatch.setattr(settings, "compliance_lexical_threshold", 0.01)

    async def retrieval(_name: str, arguments: dict) -> dict:
        return {"queries": [{
            "requirement_id": arguments["queries"][0]["requirement_id"],
            "results": [{
                "file_name": "relay.pdf", "page_number": 10,
                "text": "The relay supports IEC 61850 function 0.", "score": 0.91,
            }],
        }]}

    providers = []

    async def evaluation(requirement: dict, _evidence: list[dict], provider: str) -> dict:
        providers.append(provider)
        return {
            "requirement_id": requirement["id"], "decision": "Non-compliant",
            "product_name": "Relay", "rationale": "A product limit conflicts.",
            "evidence": [{
                "file_name": "relay.pdf", "quote": "IEC 61850",
                "location": "Page 10", "score": 0.91,
            }],
            "alternate_product": None, "alternate_rationale": None,
            "confidence": 85, "needs_escalation": True,
            "escalation_reason": "Consequential non-compliance",
            "evaluation_method": provider,
        }

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", retrieval)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", evaluation)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    assessment = db.row("SELECT * FROM assessments WHERE requirement_id = 'req-0'")
    assert providers == ["ollama"]
    assert assessment["decision"] == "Unknown"
    assert assessment["evaluation_method"] == "ollama-engineer-review"


def test_mandatory_unknown_without_explicit_conflict_does_not_escalate() -> None:
    requirement = {
        "criticality": "Mandatory",
        "solution_package": "Protection and Control System",
    }
    result = {
        "decision": "Unknown",
        "needs_escalation": True,
        "escalation_reason": "The available evidence is insufficient.",
        "evidence": [],
    }

    assert compliance_jobs._should_escalate(requirement, result) is False


def test_mandatory_explicit_conflict_escalates() -> None:
    requirement = {
        "criticality": "Mandatory",
        "solution_package": "Protection and Control System",
    }
    result = {
        "decision": "Unknown",
        "needs_escalation": True,
        "escalation_reason": "Two manual passages contradict each other.",
        "evidence": [],
    }

    assert compliance_jobs._should_escalate(requirement, result) is True


def test_resume_preserves_completed_batches(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=9)
    job = compliance_jobs.create_or_resume_job()
    batches = db.rows(
        "SELECT * FROM compliance_batches WHERE job_id = ? ORDER BY batch_index",
        (job["id"],),
    )
    db.execute(
        """UPDATE compliance_batches SET status = 'completed', assessments_json = ?, metrics_json = '{}'
           WHERE id = ?""",
        (json.dumps([{"requirement_id": f"req-{index}"} for index in range(8)]), batches[0]["id"]),
    )
    db.execute("UPDATE compliance_jobs SET status = 'failed' WHERE id = ?", (job["id"],))

    resumed = compliance_jobs.create_or_resume_job()
    statuses = db.rows(
        "SELECT status FROM compliance_batches WHERE job_id = ? ORDER BY batch_index",
        (job["id"],),
    )

    assert resumed["id"] == job["id"]
    assert [item["status"] for item in statuses] == ["completed", "pending"]


def test_low_confidence_escalated_positive_is_forced_unknown(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    monkeypatch.setattr(settings, "compliance_vector_threshold", 0.1)
    monkeypatch.setattr(settings, "compliance_lexical_threshold", 0.01)

    async def retrieval(_name: str, arguments: dict) -> dict:
        return {"queries": [{
            "requirement_id": arguments["queries"][0]["requirement_id"],
            "results": [{
                "file_name": "relay.pdf", "page_number": 10,
                "text": "The relay supports IEC 61850 function 0.", "score": 0.91,
            }],
        }]}

    async def evaluation(requirement: dict, _evidence: list[dict], provider: str) -> dict:
        return {
            "requirement_id": requirement["id"], "decision": "Compliant",
            "product_name": "Relay", "rationale": "Low confidence.",
            "evidence": [{
                "file_name": "relay.pdf", "quote": "IEC 61850", "location": "Page 10", "score": 0.91,
            }],
            "alternate_product": None, "alternate_rationale": None,
            "confidence": 0, "needs_escalation": provider == "ollama",
            "escalation_reason": "uncertain", "evaluation_method": provider,
        }

    monkeypatch.setattr(compliance_jobs, "call_catalog_tool", retrieval)
    monkeypatch.setattr(compliance_jobs, "evaluate_controlled_compliance", evaluation)
    job = compliance_jobs.create_or_resume_job()

    asyncio.run(compliance_jobs.run_job(job["id"]))

    assessment = db.row("SELECT * FROM assessments WHERE requirement_id = 'req-0'")
    assert assessment["decision"] == "Unknown"
    assert assessment["evaluation_method"] == "fireworks-unresolved"


def test_latest_job_is_stale_after_requirement_edit(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path, requirement_count=1)
    job = compliance_jobs.create_or_resume_job()
    db.execute(
        "UPDATE requirements SET requirement_text = 'The relay shall support PTP.' WHERE id = 'req-0'"
    )

    latest = compliance_jobs.latest_job()

    assert latest["id"] == job["id"]
    assert latest["stale"] is True
