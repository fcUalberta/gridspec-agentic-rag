import asyncio

from app import db, extraction_jobs
from app.agents import validate_and_dedupe_requirements
from app.candidates import direct_requirement, requirement_candidates
from app.config import settings
from app.pdf import _annotate_sections


def setup_database(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "jobs.db"))
    db.initialize()
    db.execute(
        """INSERT INTO documents (id, kind, file_name, path, byte_size, status)
           VALUES ('rfq-1', 'rfq', 'rfq.pdf', 'rfq.pdf', 100, 'ready')"""
    )


def pages() -> list[dict]:
    return [
        {"page_number": page, "text": f"Supplier shall provide relay panel item {page}."}
        for page in range(1, 10)
    ]


def test_background_job_checkpoints_and_persists_requirements(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path)
    monkeypatch.setattr(extraction_jobs, "extract_pages", lambda *_args, **_kwargs: pages())

    async def unexpected_model_call(*_args, **_kwargs) -> list[dict]:
        raise AssertionError("Explicit requirements must not call the model")

    monkeypatch.setattr(
        extraction_jobs,
        "interpret_requirement_candidates",
        unexpected_model_call,
    )
    job = extraction_jobs.create_or_resume_job("rfq-1")

    asyncio.run(extraction_jobs.run_job(job["id"]))

    completed = extraction_jobs.get_job(job["id"])
    assert completed["status"] == "completed"
    assert completed["total_batches"] == 1
    assert completed["completed_batches"] == 1
    assert completed["requirements_found"] == 9
    assert completed["progress_percent"] == 100
    assert len(db.rows("SELECT * FROM requirements")) == 9


def test_resume_keeps_completed_batches(monkeypatch, tmp_path) -> None:
    setup_database(monkeypatch, tmp_path)
    monkeypatch.setattr(extraction_jobs, "extract_pages", lambda *_args, **_kwargs: pages()[:3])
    monkeypatch.setattr(
        extraction_jobs,
        "_page_batches",
        lambda source: [[source[0]], [source[1]], [source[2]]],
    )
    job = extraction_jobs.create_or_resume_job("rfq-1")
    batches = db.rows(
        "SELECT * FROM extraction_batches WHERE job_id = ? ORDER BY batch_index",
        (job["id"],),
    )
    db.execute(
        "UPDATE extraction_batches SET status = 'completed', requirements_json = '[]' WHERE id = ?",
        (batches[0]["id"],),
    )
    db.execute(
        "UPDATE extraction_batches SET status = 'failed', error = 'bad output' WHERE id = ?",
        (batches[1]["id"],),
    )
    db.execute("UPDATE extraction_jobs SET status = 'failed' WHERE id = ?", (job["id"],))

    resumed = extraction_jobs.create_or_resume_job("rfq-1")
    statuses = db.rows(
        "SELECT status FROM extraction_batches WHERE job_id = ? ORDER BY batch_index",
        (job["id"],),
    )

    assert resumed["id"] == job["id"]
    assert resumed["status"] == "queued"
    assert [item["status"] for item in statuses] == ["completed", "pending", "pending"]


def test_triage_excludes_nontechnical_administration() -> None:
    source = [
        {"page_number": 1, "text": "Proposals must arrive before noon."},
        {"page_number": 2, "text": "The supplier shall provide a protection relay panel."},
        {"page_number": 3, "text": "The panel shall include CT test terminals."},
        {"page_number": 4, "text": "General company history and background."},
    ]

    assert [page["page_number"] for page in extraction_jobs._triage_pages(source)] == [2, 3]


def test_dynamic_batches_combine_explicit_pages_without_model_payload() -> None:
    sparse = {"page_number": 1, "text": "Relay panel shall be supplied."}
    dense = {
        "page_number": 2,
        "text": " ".join(["The relay panel shall provide CT 5 A testing."] * 40),
    }
    tail = {"page_number": 3, "text": "Protection relay shall support trip outputs."}

    batches = extraction_jobs._dynamic_batches([sparse, dense, tail])

    assert [[page["page_number"] for page in batch] for batch in batches] == [[1, 2, 3]]


def test_qualification_section_is_not_extracted() -> None:
    page = {
        "page_number": 43,
        "text": "8.1.2 Eligibility of Bidders: Technical Requirements\nThe substation shall be overseas.",
        "section": "8.1.2 Eligibility of Bidders: Technical Requirements",
        "blocks": [{
            "text": "The substation shall be an overseas utility.",
            "bbox": [1, 2, 3, 4],
            "section": "8.1.2 Eligibility of Bidders: Technical Requirements",
        }],
    }

    assert requirement_candidates(page) == []


def test_incomplete_clause_is_not_extracted() -> None:
    page = {
        "page_number": 10,
        "text": "The contractor shall provide complete wiring diagrams including",
        "blocks": [{
            "text": "The contractor shall provide complete wiring diagrams including",
            "bbox": None,
            "section": "Technical Requirements",
        }],
    }

    assert requirement_candidates(page) == []


def test_clause_split_across_pdf_blocks_is_joined() -> None:
    page = {
        "page_number": 10,
        "text": "The contractor shall provide wiring diagrams including connection details.",
        "blocks": [
            {"text": "The contractor shall provide wiring diagrams including", "bbox": [1, 1, 10, 2],
             "section": "Technical Requirements"},
            {"text": "connection details.", "bbox": [1, 3, 10, 4],
             "section": "Technical Requirements"},
        ],
    }

    candidates = requirement_candidates(page)

    assert len(candidates) == 1
    assert candidates[0]["source_quote"] == (
        "The contractor shall provide wiring diagrams including connection details."
    )
    assert candidates[0]["source_bbox"] == [1, 1, 10, 4]


def test_source_quote_stays_verbatim_while_known_ocr_errors_are_normalized() -> None:
    candidate = {
        "source_quote": "SI sbaU configure each JED for the !EC 61850 protection system.",
        "source_bbox": None,
        "page_number": 10,
        "section": "Protection system",
        "category": "Protection and Control",
        "criticality": "Preferred",
        "confidence": 92,
    }

    requirement = direct_requirement(candidate)

    assert requirement["source_quote"] == candidate["source_quote"]
    assert requirement["requirement_text"] == "SI shall configure each IED for the IEC 61850 protection system."


def test_garbled_obligation_is_routed_to_bounded_interpretation() -> None:
    page = {
        "page_number": 10,
        "text": "SI shall c0nf!gure each IED for the IEC 61850 protection system.",
        "blocks": [{
            "text": "SI shall c0nf!gure each IED for the IEC 61850 protection system.",
            "bbox": None,
            "section": "Protection system",
        }],
    }

    candidates = requirement_candidates(page)

    assert len(candidates) == 1
    assert candidates[0]["candidate_type"] == "ambiguous"
    assert candidates[0]["confidence"] == 65


def test_near_duplicates_merge_but_different_ratings_remain() -> None:
    pages = [{
        "page_number": 1,
        "text": (
            "The relay shall support a nominal input of 115 V. "
            "The relay sbaU support a nominal input of 115 V. "
            "The relay shall support a nominal input of 230 V."
        ),
    }]
    base = {
        "requirement_key": "",
        "section": "Relay inputs",
        "source_bbox": None,
        "page_number": 1,
        "category": "Electrical Interface",
        "criticality": "Mandatory",
        "confidence": 90,
    }
    items = [
        {**base, "requirement_text": "The relay shall support a nominal input of 115 V.",
         "source_quote": "The relay shall support a nominal input of 115 V."},
        {**base, "requirement_text": "The relay sbaU support a nominal input of 115 V.",
         "source_quote": "The relay sbaU support a nominal input of 115 V."},
        {**base, "requirement_text": "The relay shall support a nominal input of 230 V.",
         "source_quote": "The relay shall support a nominal input of 230 V."},
    ]

    result = validate_and_dedupe_requirements(items, pages)

    assert len(result) == 2
    assert [item["requirement_key"] for item in result] == ["REQ-001", "REQ-002"]


def test_administrative_section_context_ends_at_next_major_section() -> None:
    source = [
        {"page_number": 1, "blocks": [
            {"text": "A-3.\nEligibility of Bidders: Technical Requirements"},
            {"text": "SUPPLY OF PROTECTION EQUIPMENT"},
            {"text": "The substation shall be an overseas utility."},
        ]},
        {"page_number": 2, "blocks": [
            {"text": "SECTION C"},
            {"text": "The relay panel shall include CT test terminals."},
        ]},
    ]

    _annotate_sections(source)

    assert "Eligibility of Bidders" in source[0]["blocks"][2]["section"]
    assert "Eligibility of Bidders" not in source[1]["blocks"][1]["section"]
