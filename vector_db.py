import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from fastembed import TextEmbedding
from config import QDRANT_URL, QDRANT_API_KEY, COLLECTION_NAME, EMBED_MODEL, EMBED_SIZE

# Initialize clients globally
embedder = None
qdrant = None

def init_vector_db():
    global embedder, qdrant
    # Lazy initializations
    if not embedder:
        embedder = TextEmbedding(EMBED_MODEL)
    
    if not qdrant:
        qdrant = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        existing = [c.name for c in qdrant.get_collections().collections]
        if COLLECTION_NAME not in existing:
            qdrant.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBED_SIZE, distance=Distance.COSINE),
            )
            print(f"✅ Qdrant collection '{COLLECTION_NAME}' dibuat")
        else:
            print(f"✅ Qdrant collection '{COLLECTION_NAME}' sudah ada")
        
        # Buat index untuk field metadata (idempotent, tidak apa-apa dipanggil ulang)
        # Menghindari error "Bad request: Index required but not found for user_id"
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="user_id",
            field_schema="keyword"
        )
        qdrant.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="filename",
            field_schema="keyword"
        )

def embed(texts: list) -> list:
    """Generate embedding untuk list of texts."""
    return list(embedder.embed(texts))

def upsert_chunks(user_id: str, filename: str, chunks: list):
    """Simpan chunks ke Qdrant dengan vector embedding."""
    # Delete old chunks
    qdrant.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                FieldCondition(key="filename", match=MatchValue(value=filename)),
            ]
        )
    )

    vectors = embed(chunks)
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vectors[i].tolist(),
            payload={
                "user_id": user_id,
                "filename": filename,
                "chunk_index": i,
                "text": chunks[i],
            }
        )
        for i in range(len(chunks))
    ]

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

def search_chunks(user_id: str, query: str, top_k: int = 5) -> str:
    """Semantic search chunk dokumen user."""
    query_vec = embed([query])[0].tolist()
    query_filter = Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    )

    if hasattr(qdrant, "search"):
        results = qdrant.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vec,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
    else:
        # Untuk qdrant-client versi terbaru yang sudah tidak mensupport .search()
        resp = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vec,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        results = resp.points

    if not results:
        return ""

    formatted = []
    for r in results:
        p = r.payload
        score_pct = int(r.score * 100)
        formatted.append(f"[📄 {p['filename']} | bagian {p['chunk_index']+1} | relevansi {score_pct}%]\n{p['text']}")

    return "\n\n---\n\n".join(formatted)

def delete_chunks(user_id: str, filename: str):
    qdrant.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                FieldCondition(key="filename", match=MatchValue(value=filename)),
            ]
        )
    )
