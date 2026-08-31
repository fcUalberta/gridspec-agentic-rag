from fastapi.testclient import TestClient

from app import db, main
from app.config import settings
from app.main import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_status_reports_missing_key_without_dummy_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fireworks_api_key", "")
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_upload_stops_when_fireworks_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "fireworks_api_key", "")
    response = client.post(
        "/documents",
        data={"kind": "rfq"},
        files={"file": ("sample.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 503
    assert "FIREWORKS_API_KEY" in response.json()["detail"]


def test_extraction_start_returns_background_job_without_json_preflight(monkeypatch) -> None:
    job = {
        "id": "job-1",
        "document_id": "rfq-1",
        "status": "completed",
        "total_batches": 2,
        "completed_batches": 2,
        "failed_batches": 0,
        "requirements_found": 4,
        "progress_percent": 100,
        "current_page_range": None,
        "error": None,
    }
    monkeypatch.setattr(main, "create_or_resume_job", lambda _document_id, force=False: job)
    monkeypatch.setattr(main, "get_job", lambda _job_id: job)

    response = client.post("/extract", data={"documentId": "rfq-1"})

    assert response.status_code == 202
    assert response.json()["job"]["status"] == "completed"


def test_compliance_start_returns_checkpointed_job(monkeypatch) -> None:
    job = {
        "id": "compliance-1",
        "status": "completed",
        "total_requirements": 4,
        "completed_requirements": 4,
        "progress_percent": 100,
    }
    monkeypatch.setattr(main, "create_or_resume_compliance_job", lambda force=False: job)
    monkeypatch.setattr(main, "get_compliance_job", lambda _job_id: job)

    response = client.post("/compliance")

    assert response.status_code == 202
    assert response.json()["job"]["id"] == "compliance-1"


def test_assessment_guard_uses_compliance_job_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "guard.db"))
    db.initialize()
    db.execute(
        """INSERT INTO compliance_jobs
           (id, status, input_hash, pipeline_version)
           VALUES ('current-job', 'running', 'hash', ?)""",
        (main.COMPLIANCE_PIPELINE_VERSION,),
    )
    main.install_assessment_write_guards()

    db.upsert_assessments(
        [{
            "requirement_id": "req-1",
            "decision": "Unknown",
            "product_name": "",
            "rationale": "Guard regression test",
            "evidence": [],
            "confidence": 95,
            "evaluation_method": "test",
        }],
        "current-job",
    )

    stored = db.row("SELECT compliance_job_id FROM assessments WHERE requirement_id = 'req-1'")
    assert stored == {"compliance_job_id": "current-job"}
