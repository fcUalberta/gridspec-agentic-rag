# GridSpec six-minute demo script

This script allocates three minutes to the solution diagrams and three minutes to the live application.

## Part 1: Solution and architecture, 3 minutes

### 0:00 to 0:45 | Solution overview

"GridSpec helps tendering and proposal teams turn a customer RFQ and product documentation into an evidence-backed compliance response and a cohesive technical solution.

The workflow has five major stages.

First, we upload the customer RFQ and the approved product manuals.

Second, GridSpec extracts the technical requirements and organizes them into an engineering story. An engineer can review and edit the requirements before continuing.

Third, the Agentic RAG compliance process retrieves relevant product evidence and evaluates each requirement. RAG provides the evidence, the agent performs bounded reasoning only when needed, and MCP controls access to the approved tools and data.

Fourth, the system checks whether the individual product selections form a cohesive solution. It identifies interface issues, assumptions, deviations, and potential alternatives.

Finally, it produces the compliance matrix, recommended solution, BOQ or BOM, and machine-readable exports.

The key design principle is control. Deterministic processing is used wherever possible, agents are introduced only for reasoning tasks, and engineers review the major outputs."

### 0:45 to 1:40 | Decision path

"This diagram shows how a requirement moves through the system.

The RFQ and product documents are first parsed locally. This preserves the original quotation, page number, and citation metadata.

Requirements are then extracted, normalized, classified, and presented to the engineer for review. The engineer does not need to approve every requirement. They can edit any requirement and then continue at the stage level.

For each approved requirement, the system builds a search query and determines the correct evidence scope. This is important because a product capability should be checked against a product manual, while system design, testing, and deliverable requirements may need engineering evidence instead.

The workflow then calls approved MCP tools to retrieve evidence. RAG combines semantic retrieval, lexical matching, numeric and standards filters, product-family checks, and bounded context selection.

If valid evidence is found, the compliance agent evaluates only that evidence. It returns a structured status, rationale, confidence, and citations. Citations are validated before a positive result can be saved.

If evidence is missing, the result remains unknown or is routed for clarification. The system does not manufacture a positive compliance claim.

After all requirements are evaluated, a cohesion agent checks compatibility across the complete solution. Conflicts can trigger an alternate product search. The system then builds the consolidated BOQ or BOM and sends the final package to the engineer."

### 1:40 to 3:00 | Detailed architecture

"The detailed architecture is divided into five sections.

The first section contains the inputs: the customer RFQ, product manuals, supporting technical documents, and the engineer working through the React interface.

The second section is the document and requirement pipeline. FastAPI receives the documents. PyMuPDF is the canonical parser, LiteParse is used selectively for difficult layouts, and OCR can support image-based pages. A deterministic requirement engine performs clause splitting, text repair, deduplication, taxonomy assignment, and citation preservation. Model assistance is limited to genuinely ambiguous candidates.

The third section is the Agentic RAG compliance layer. For each requirement, the system selects an evidence scope, performs hybrid semantic and lexical retrieval, applies hard numeric and standards filters, bounds the evidence context, and invokes the compliance evaluator. Qdrant stores the product-manual vectors, while SQLite stores workflow state, decisions, jobs, and audit information.

The MCP server forms a controlled tool boundary. It exposes only approved catalog indexing, evidence retrieval, batch search, and status functions. Agents do not receive unrestricted access to files or databases.

For model routing, Ollama is the primary local evaluator. Fireworks AI supplies embeddings and is used selectively for difficult or low-confidence cases. This reduces hosted API calls while preserving an escalation path.

The fourth section assembles the complete solution. The cohesion agent checks interfaces, dependencies, alternatives, deviations, and assumptions. Deterministic code then builds the BOQ or BOM.

The fifth section contains the outputs: the compliance matrix, cohesive recommended solution, alternate and deviation register, BOQ or BOM, unresolved items, and CSV and JSON exports.

LangGraph connects these sections as a controlled state graph with checkpoints, timeouts, retries, resumable batches, and human review."

## Transition to the live demo

"That is the design. I will now show the same workflow running in the application."

## Part 2: Live application, 3 minutes

### 3:00 to 3:30 | Sources

Open the **Sources** page.

"This is the source workspace. I have uploaded one real utility RFQ and two real GE Vernova product manuals.

The RFQ is parsed into page-aware requirements, while the product manuals are indexed as evidence sources. The workflow has completed 21 extraction batches and identified 1,110 candidate requirements.

The work runs in the background, persists its progress, and can resume after an interruption."

Point to:

- RFQ and manual upload controls
- Document status
- Extraction progress
- Model connection indicator

### 3:30 to 4:10 | Requirements

Open the **Requirements** page.

"The extracted requirements are presented as a cohesive engineering story rather than a flat list.

They are grouped into solution packages such as design basis, protection and control, process bus, station communications, panels, metering, engineering services, and verification.

Within each package, the requirements are ordered by engineering subcategory. Every item retains its RFQ page citation and expected evidence route.

The engineer can edit any requirement, but individual approvals are not required. When ready, the engineer continues from this stage-level checkpoint."

Demonstrate:

- Selecting a solution package
- Opening one requirement
- Pointing to its page reference and evidence route
- Briefly showing the edit capability

### 4:10 to 5:05 | Compliance

Open the **Compliance** page.

"This is the completed compliance assessment for all 1,110 requirements.

The summary separates product compliance, product exceptions, unresolved product evidence, and engineering evidence that cannot be proven from a product manual.

In this run, 574 requirements were handled deterministically or routed without a product-model evaluation. Ollama evaluated 536 product cases, and 112 difficult cases were selectively escalated to Fireworks.

The table is ordered using the same engineering structure as the requirement review. Each row shows the requirement, status, evidence route, and source document.

A compliant result must have validated evidence. Non-compliant results show the identified conflict. Evidence-insufficient items remain visible rather than being forced into an unsupported conclusion."

Expand one compliant row and one unresolved or non-compliant row.

"For example, this result cites the B30 product manual and its source page. This unresolved result clearly states that the required evidence was not found or must come from an engineering deliverable.

If processing is interrupted, the run can resume from incomplete checkpoints. Individual results or failed batches can also be re-evaluated."

### 5:05 to 5:40 | Cohesive solution

Open the **Solution** page.

"After requirement-level compliance, GridSpec assembles a complete protection-panel solution.

The proposed solution combines the GE UR B30 busbar differential relay, UR communications gateway, power-supply components, and supporting panel elements.

The BOQ or BOM is shown beside the interface and cohesion checks. These checks look across requirements for protection independence, CT and VT interfaces, communications, power, synchronization, testing, and panel construction.

Assumptions and deviations remain explicit. They are not hidden inside the generated narrative."

Scroll briefly to the assumptions and deviations.

### 5:40 to 6:00 | Outputs and close

Open the **Outputs** page.

"The final stage exports the live analysis.

The compliance matrix is available as CSV, including requirement context, decision, evidence, rationale, and confidence.

The complete solution package is available as JSON, including the BOM, cohesion checks, assumptions, deviations, and unresolved items.

The result is an initial bid package produced in less than an hour instead of several days, while remaining traceable and reviewable at every major stage.

GridSpec is not replacing the engineer. It is giving the engineer a faster, controlled, and evidence-backed starting point."

