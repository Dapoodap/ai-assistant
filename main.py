import asyncio
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from pathlib import Path
from contextlib import asynccontextmanager

from config import SUPPORTED_EXTS
from database import (
    init_db_pool,
    close_db_pool,
    init_postgres,
    ensure_user,
    get_memory,
    save_memory,
    clear_memory_db,
    save_document_meta,
    get_user_documents,
    delete_document_meta,
)
from vector_db import (
    init_vector_db,
    upsert_chunks,
    search_chunks,
    delete_chunks,
)
from llm import ask_llm
from search import web_search
from utils import read_pdf, smart_chunk, detect_mode, build_system_prompt

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db_pool()
    init_postgres()
    init_vector_db()
    
    yield
    
    # Shutdown
    close_db_pool()

app = FastAPI(lifespan=lifespan)

class ChatReq(BaseModel):
    user_id: str
    message: str
    username: str = None

@app.post("/chat")
def chat(req: ChatReq):
    user_id = req.user_id
    text = req.message

    ensure_user(user_id, req.username)
    mode = detect_mode(text, user_id)
    extra_ctx = ""

    if mode == "web_search":
        extra_ctx = web_search(text)

    elif mode in ("doc_query", "doc_edit"):
        # Semantic search dari Qdrant
        extra_ctx = search_chunks(user_id, text, top_k=5)

    memory = get_memory(user_id)
    messages = [
        {"role": "system", "content": build_system_prompt(mode, extra_ctx, user_id)}
    ] + memory + [
        {"role": "user", "content": text}
    ]

    reply = ask_llm(messages)

    save_memory(user_id, "user", text)
    save_memory(user_id, "assistant", reply)

    return {"reply": reply, "mode": mode}

@app.post("/upload/{user_id}")
async def upload_doc(user_id: str, file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        return {"error": f"Format {ext} belum didukung. Gunakan: {', '.join(sorted(SUPPORTED_EXTS))}"}

    # Use asyncio.to_thread for database initialization/checking to avoid blocking event loop
    await asyncio.to_thread(ensure_user, user_id)
    
    raw = await file.read()

    # Extract text and chunk (CPU-bound)
    def process_content():
        if ext == ".pdf":
            content = read_pdf(raw)
        else:
            content = raw.decode("utf-8", errors="replace")
        
        chunks = smart_chunk(content)
        return content, chunks

    content, chunks = await asyncio.to_thread(process_content)

    # Simpan ke Qdrant dan Postgres di background thread untuk mencegah block
    def save_data():
        upsert_chunks(user_id, file.filename, chunks)
        save_document_meta(
            user_id=user_id,
            filename=file.filename,
            file_type=ext.lstrip("."),
            total_chunks=len(chunks),
            total_chars=len(content),
            total_lines=content.count("\n") + 1,
        )

    await asyncio.to_thread(save_data)

    return {
        "status": "ok",
        "filename": file.filename,
        "chunks": len(chunks),
        "chars": len(content),
        "lines": content.count("\n") + 1,
    }

@app.get("/docs/{user_id}")
def list_docs(user_id: str):
    docs = get_user_documents(user_id)
    # converting items into proper dictionaries
    # RealDictRow -> dict
    return [dict(d) for d in docs]

@app.delete("/docs/{user_id}/{filename}")
def delete_doc(user_id: str, filename: str):
    delete_chunks(user_id, filename)
    delete_document_meta(user_id, filename)
    return {"status": "deleted", "filename": filename}

@app.get("/memory/{user_id}")
def get_user_memory(user_id: str):
    return {"memory": get_memory(user_id)}

@app.delete("/memory/{user_id}")
def clear_memory(user_id: str):
    clear_memory_db(user_id)
    return {"status": "ok"}

@app.get("/search")
def search_endpoint(q: str, max_results: int = 5):
    return {"results": web_search(q, max_results)}