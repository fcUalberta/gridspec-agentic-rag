import asyncio

from app import agents
from app.graphs import extract_requirements
from app.models import CandidateDecisionBatch, RequirementBatch


class FakeStructuredModel:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    async def ainvoke(self, _: str) -> dict:
        return self.responses.pop(0)


class FakeModel:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    def with_structured_output(self, *_args, **_kwargs) -> FakeStructuredModel:
        return FakeStructuredModel(self.responses)


def test_batch_falls_back_when_first_structured_response_is_none(monkeypatch) -> None:
    valid = RequirementBatch(requirements=[])
    responses = [
        {"raw": object(), "parsed": None, "parsing_error": None},
        {"raw": object(), "parsed": valid, "parsing_error": None},
    ]
    monkeypatch.setattr(agents, "model", lambda _model_name=None: FakeModel(responses))

    result = asyncio.run(agents.extract_requirement_batch([{"page_number": 7, "text": "Background"}]))

    assert result == []
    assert responses == []


def test_candidate_interpretation_uses_deterministic_citation(monkeypatch) -> None:
    valid = CandidateDecisionBatch(decisions=[{
        "candidate_id": "p8-table-0",
        "accept": True,
        "requirement_text": "The secondary current input rating shall be 5 A.",
        "category": "Electrical Interface",
        "criticality": "Mandatory",
        "confidence": 91,
    }])
    responses = [{"raw": object(), "parsed": valid, "parsing_error": None}]
    monkeypatch.setattr(agents, "model", lambda _model_name=None: FakeModel(responses))
    candidate = {
        "candidate_id": "p8-table-0",
        "section": "Line current differential relay",
        "source_quote": "Secondary Current Input Rating: 5 A",
        "source_bbox": [10.0, 20.0, 100.0, 40.0],
        "page_number": 8,
    }

    result = asyncio.run(agents.interpret_requirement_candidates([candidate]))

    assert result[0]["source_quote"] == candidate["source_quote"]
    assert result[0]["source_bbox"] == candidate["source_bbox"]
    assert result[0]["page_number"] == 8
    assert result[0]["confidence"] == 88


def test_graph_splits_failed_batch_and_preserves_successful_results(monkeypatch) -> None:
    calls = []

    async def fake_extract(batch: list[dict]) -> list[dict]:
        calls.append([page["page_number"] for page in batch])
        if len(batch) > 1:
            raise agents.StructuredOutputFailure("malformed")
        page = batch[0]["page_number"]
        return [{
            "requirement_key": "",
            "section": "Test",
            "requirement_text": f"Requirement on page {page}",
            "source_quote": f"Supplier shall provide item {page}.",
            "page_number": page,
            "category": "Technical",
            "criticality": "Mandatory",
            "confidence": 90,
        }]

    pages = [
        {"page_number": page, "text": f"Supplier shall provide item {page}."}
        for page in range(1, 5)
    ]
    monkeypatch.setattr("app.graphs.extract_requirement_batch", fake_extract)

    result = asyncio.run(extract_requirements({"pages": pages}))

    assert [item["page_number"] for item in result["requirements"]] == [1, 2, 3, 4]
    assert calls == [[1, 2, 3, 4], [1, 2], [3, 4], [1], [2], [3], [4]]
