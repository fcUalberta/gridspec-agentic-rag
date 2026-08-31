from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class Requirement(BaseModel):
    requirement_key: str
    section: str
    requirement_text: str
    source_quote: str
    source_bbox: list[float] | None = None
    page_number: int | None
    category: str
    criticality: Literal["Mandatory", "Preferred", "Informational"]
    confidence: int = Field(ge=0, le=100)


class RequirementBatch(BaseModel):
    requirements: list[Requirement]


class CandidateDecision(BaseModel):
    candidate_id: str
    accept: bool
    requirement_text: str = ""
    category: str = "Technical"
    criticality: Literal["Mandatory", "Preferred", "Informational"] = "Mandatory"
    confidence: int = Field(default=80, ge=0, le=100)


class CandidateDecisionBatch(BaseModel):
    decisions: list[CandidateDecision]


class Evidence(BaseModel):
    file_name: str
    quote: str
    location: str
    score: float


class ComplianceDecision(BaseModel):
    requirement_id: str
    decision: Literal["Compliant", "Conditional", "Non-compliant", "Unknown"]
    product_name: str
    rationale: str
    evidence: list[Evidence]
    alternate_product: str | None
    alternate_rationale: str | None
    confidence: int = Field(ge=0, le=100)


class ControlledComplianceDecision(BaseModel):
    decision: Literal["Compliant", "Conditional", "Non-compliant", "Unknown"]
    product_name: str = ""
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    alternate_product: str | None = None
    alternate_rationale: str | None = None
    confidence: int = Field(ge=0, le=100)
    needs_escalation: bool = False
    escalation_reason: str | None = None


class BomItem(BaseModel):
    item: str
    product: str
    quantity: int = Field(ge=1)
    purpose: str


class CohesionCheck(BaseModel):
    interface: str
    status: Literal["Pass", "Review", "Conflict"]
    finding: str


class CohesiveSolution(BaseModel):
    name: str
    summary: str
    bill_of_material: list[BomItem]
    cohesion_checks: list[CohesionCheck]
    assumptions: list[str]
    deviations: list[str]


class PipelineState(TypedDict, total=False):
    document_id: str
    pages: list[dict]
    requirements: list[dict]
    assessments: list[dict]
    solution: dict
