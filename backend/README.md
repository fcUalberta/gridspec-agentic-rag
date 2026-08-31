# GridSpec real pipeline

This backend performs real PDF parsing, bounded Fireworks AI model calls, vector indexing, MCP
retrieval, source-quote validation, compliance evaluation, and cohesive solution generation. It
contains no sample requirements or fabricated compliance records.

## Configure Fireworks

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and replace `fw_your_key_here` with a Fireworks API key. Never commit `.env`.

## Run the complete demo

From the React project root:

```bash
chmod +x run-demo.sh
./run-demo.sh
```

Open `http://localhost:3000`, upload at least one product manual, upload an RFQ, then follow the
engineer review gates. The backend API documentation is at `http://127.0.0.1:8000/docs` and the
Product Catalog MCP endpoint is `http://127.0.0.1:8001/mcp`.

If Ollama and `llama3.1:8b` are installed, `run-demo.sh` starts the local service when needed and
uses it for ambiguous requirement candidates. Fireworks remains the fallback and powers compliance
and cohesive-solution reasoning.

## Controlled workflow

- PyMuPDF is the canonical text and bounding-box parser.
- LiteParse runs only on pages its local complexity detector flags for tables or difficult layouts.
- Explicit technical obligations are extracted deterministically without an LLM call.
- Bidder-qualification and procurement sections are excluded using propagated section context.
- Clauses split across adjacent PDF blocks are reassembled before extraction; incomplete fragments are rejected.
- Known OCR distortions are normalized in requirement wording while the verbatim source quotation is preserved.
- Near-duplicate requirements are merged only when their numeric ratings and referenced standards also match.
- Fireworks reviews only ambiguous structured candidates and cannot provide source citations.
- Page numbers, quotations, and bounding boxes always come from the local parsers.
- LangGraph controls the extraction, compliance, and cohesive-solution graphs.
- LangChain `ChatFireworks` nodes are used only for structured interpretation and reasoning.
- Product manual indexing and retrieval are exposed through the Product Catalog MCP server.
- Model evidence quotes are accepted only when found verbatim in retrieved manual text.
- Empty or unverifiable evidence forces an `Unknown` decision.
- Compliance is persisted in eight-requirement checkpoints and resumes only incomplete batches.
- One batched MCP request retrieves catalog evidence for each checkpoint.
- Deterministic lexical, vector, standard, and numeric-value gates reject weak matches before reasoning.
- Ollama evaluates evidence-qualified requirements first; Fireworks receives only low-confidence,
  conflicting, or consequential cases.
- Fireworks decisions below the confidence threshold are conservatively persisted as `Unknown`.
