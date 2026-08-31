import asyncio
import json
import uuid
from itertools import pairwise

from langgraph.graph import END, START, StateGraph

from . import db
from .agents import (
    StructuredOutputFailure,
    build_solution,
    evaluate_requirements,
    extract_requirement_batch,
    validate_and_dedupe_requirements,
)
from .models import PipelineState
from .pdf import extract_pages


async def parse_rfq(state: PipelineState) -> dict:
    document = db.row("SELECT * FROM documents WHERE id = ? AND kind = 'rfq'", (state["document_id"],))
    if not document:
        raise ValueError("RFQ document not found")
    return {"pages": extract_pages(document["path"], include_complex_layout=True)}


async def extract_requirements(state: PipelineState) -> dict:
    pages = state["pages"]
    batches = [pages[index:index + 8] for index in range(0, len(pages), 8)]
    semaphore = asyncio.Semaphore(3)

    async def invoke(batch: list[dict]) -> list[dict]:
        async with semaphore:
            return await extract_requirement_batch(batch)

    async def run(batch: list[dict]) -> list[dict]:
        try:
            return await invoke(batch)
        except StructuredOutputFailure as error:
            if len(batch) == 1:
                page_number = batch[0]["page_number"]
                raise ValueError(
                    f"Requirement extraction could not parse RFQ page {page_number}. "
                    "The model returned invalid structured output after retries. "
                    "Check that page for unusually dense tables or malformed extracted text."
                ) from error
            midpoint = len(batch) // 2
            left, right = await asyncio.gather(run(batch[:midpoint]), run(batch[midpoint:]))
            return left + right

    extracted = []
    for group in await asyncio.gather(*(run(batch) for batch in batches)):
        extracted.extend(group)
    return {"requirements": validate_and_dedupe_requirements(extracted, pages)}


async def persist_requirements(state: PipelineState) -> dict:
    requirements = db.replace_requirements(state["document_id"], state["requirements"])
    db.execute("UPDATE documents SET status = 'extracted', error = NULL WHERE id = ?", (state["document_id"],))
    return {"requirements": requirements}


async def evaluate_compliance(_: PipelineState) -> dict:
    requirements = db.rows("SELECT * FROM requirements ORDER BY requirement_key")
    if not requirements:
        raise ValueError("Extract at least one requirement before compliance evaluation")
    return {"requirements": requirements, "assessments": await evaluate_requirements(requirements)}


async def persist_compliance(state: PipelineState) -> dict:
    return {"assessments": db.replace_assessments(state["assessments"])}


async def assemble_solution(_: PipelineState) -> dict:
    requirements = db.rows("SELECT * FROM requirements ORDER BY requirement_key")
    raw_assessments = db.rows("SELECT * FROM assessments ORDER BY created_at")
    assessments = []
    for item in raw_assessments:
        item["evidence"] = json.loads(item.pop("evidence_json"))
        item["alternate"] = json.loads(item.pop("alternate_json"))
        assessments.append(item)
    if not assessments:
        raise ValueError("Run compliance evaluation before solution assembly")
    return {"solution": await build_solution(requirements, assessments)}


async def persist_solution(state: PipelineState) -> dict:
    solution_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO solutions (id, solution_json, review_status) VALUES (?, ?, 'Needs review')",
        (solution_id, json.dumps(state["solution"])),
    )
    return {"solution": state["solution"]}


def compile_graph(nodes: list[tuple[str, object]]):
    graph = StateGraph(PipelineState)
    for name, node in nodes:
        graph.add_node(name, node)
    graph.add_edge(START, nodes[0][0])
    for current, following in pairwise(nodes):
        graph.add_edge(current[0], following[0])
    graph.add_edge(nodes[-1][0], END)
    return graph.compile()


extraction_graph = compile_graph([
    ("parse_rfq", parse_rfq),
    ("requirement_extraction_agent", extract_requirements),
    ("persist_requirements", persist_requirements),
])
compliance_graph = compile_graph([
    ("compliance_evaluation_agent", evaluate_compliance),
    ("persist_compliance", persist_compliance),
])
solution_graph = compile_graph([
    ("cohesive_solution_agent", assemble_solution),
    ("persist_solution", persist_solution),
])
