import uuid

from langchain_fireworks import FireworksEmbeddings
from mcp.server.fastmcp import FastMCP
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings

COLLECTION = "product_manual_evidence"
mcp = FastMCP(
    "GridSpec Product Catalog",
    instructions="Indexes product manuals and returns exact evidence chunks with page metadata.",
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=settings.mcp_port,
)
qdrant = QdrantClient(path=settings.qdrant_path)
embeddings = FireworksEmbeddings(model=settings.fireworks_embedding_model, api_key=settings.fireworks_api_key)
# Bound provider requests so one call cannot wedge the synchronous MCP worker.
embeddings.client = embeddings.client.with_options(timeout=30.0, max_retries=2)


def ensure_collection(vector_size: int) -> None:
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(COLLECTION, vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE))


@mcp.tool()
def index_product_manual(chunks: list[dict]) -> dict:
    """Index page-aware chunks from one product manual in the evidence catalog."""
    if not chunks:
        return {"indexed": 0}
    vectors = embeddings.embed_documents([chunk["text"] for chunk in chunks])
    ensure_collection(len(vectors[0]))
    points = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk["id"]))
        points.append(PointStruct(id=point_id, vector=vector, payload=chunk))
    qdrant.upsert(COLLECTION, points=points, wait=True)
    return {"indexed": len(points), "document_id": chunks[0]["document_id"]}


@mcp.tool()
def search_manual_evidence(query: str, limit: int = 8) -> dict:
    """Search indexed product manuals and return exact text, filename, page, and relevance score."""
    if not qdrant.collection_exists(COLLECTION):
        return {"results": []}
    vector = embeddings.embed_query(query)
    response = qdrant.query_points(COLLECTION, query=vector, limit=max(1, min(limit, 20)), with_payload=True)
    results = []
    for point in response.points:
        payload = point.payload or {}
        results.append({
            "file_name": payload.get("file_name", ""),
            "page_number": payload.get("page_number"),
            "text": payload.get("text", ""),
            "score": float(point.score),
            "document_id": payload.get("document_id", ""),
        })
    return {"results": results}


@mcp.tool()
def search_manual_evidence_batch(queries: list[dict], limit: int = 8) -> dict:
    """Search evidence for several requirements with one embedding request."""
    if not queries:
        return {"queries": []}
    if not qdrant.collection_exists(COLLECTION):
        return {
            "queries": [
                {"requirement_id": item.get("requirement_id", ""), "results": []}
                for item in queries
            ]
        }
    vectors = embeddings.embed_documents([str(item.get("query", "")) for item in queries])
    bounded_limit = max(1, min(limit, 20))
    response = []
    for item, vector in zip(queries, vectors, strict=True):
        points = qdrant.query_points(
            COLLECTION,
            query=vector,
            limit=bounded_limit,
            with_payload=True,
        ).points
        results = []
        for point in points:
            payload = point.payload or {}
            results.append({
                "file_name": payload.get("file_name", ""),
                "page_number": payload.get("page_number"),
                "text": payload.get("text", ""),
                "score": float(point.score),
                "document_id": payload.get("document_id", ""),
            })
        response.append({"requirement_id": item.get("requirement_id", ""), "results": results})
    return {"queries": response}


@mcp.tool()
def catalog_status() -> dict:
    """Return whether the product evidence collection exists and its indexed point count."""
    if not qdrant.collection_exists(COLLECTION):
        return {"ready": True, "indexed_chunks": 0}
    info = qdrant.get_collection(COLLECTION)
    return {"ready": True, "indexed_chunks": info.points_count or 0}


if __name__ == "__main__":
    if not settings.fireworks_api_key:
        raise SystemExit("FIREWORKS_API_KEY is missing. Copy .env.example to .env and add the key.")
    mcp.run(transport="streamable-http")
