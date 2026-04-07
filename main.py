import json
import os
import re
import requests
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from dotenv import load_dotenv
from ddgs import DDGS
from pathlib import Path

load_dotenv()

app = FastAPI()

API_KEY = os.getenv("OPENROUTER_API_KEY")
STATE_FILE = "state.json"
DOCS_DIR = Path("user_docs")
DOCS_DIR.mkdir(exist_ok=True)

# ───────────────────────────────────────────
# STORAGE
# ───────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(data: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

state = load_state()

# ───────────────────────────────────────────
# LLM
# ───────────────────────────────────────────

MODELS = [
    "nvidia/nemotron-ultra-253b-v1:free",
    "mistralai/mistral-7b-instruct:free",
    "openrouter/auto",
]

def ask_llm(messages: list, temperature: float = 0.7) -> str:
    for model in MODELS:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://dapoai.local",
                    "X-Title": "dapoAI",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                },
                timeout=30,
            )
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            continue
    return "⚠️ Semua model lagi sibuk, coba lagi sebentar."

# ───────────────────────────────────────────
# MEMORY
# ───────────────────────────────────────────

MAX_MEMORY = 10

def get_memory(user: str) -> list:
    return state.get(user, {}).get("memory", [])

def update_memory(user: str, role: str, content: str):
    if user not in state:
        state[user] = {}
    mem = state[user].get("memory", [])
    mem.append({"role": role, "content": content})
    state[user]["memory"] = mem[-MAX_MEMORY:]
    save_state(state)

# ───────────────────────────────────────────
# WEB SEARCH — fetch konten halaman juga
# ───────────────────────────────────────────

def fetch_page_content(url: str, max_chars: int = 2000) -> str:
    """Fetch isi halaman web mentah, strip HTML kasar."""
    try:
        r = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; dapoAI/1.0)"},
        )
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""

def web_search(query: str, max_results: int = 5) -> str:
    """
    DuckDuckGo search + fetch isi 2 halaman teratas.
    Kalau query panjang gagal, coba versi singkat.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            simplified = " ".join(query.split()[:5])
            with DDGS() as ddgs:
                results = list(ddgs.text(simplified, max_results=max_results))

        if not results:
            return "Tidak ada hasil ditemukan."

        lines = []
        for i, r in enumerate(results, 1):
            entry = f"[{i}] {r['title']}\nSnippet: {r['body']}"
            # Fetch konten lengkap 2 hasil teratas
            if i <= 2:
                content = fetch_page_content(r["href"])
                if content:
                    entry += f"\nIsi halaman: {content}"
            entry += f"\nURL: {r['href']}"
            lines.append(entry)

        return "\n\n---\n\n".join(lines)

    except Exception as e:
        return f"Web search error: {e}"

# ───────────────────────────────────────────
# DOKUMEN — baca, chunk, edit, recreate
# ───────────────────────────────────────────

SUPPORTED_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css", ".xml", ".pdf"}


def read_pdf(file_bytes: bytes) -> str:
    """Extract teks dari PDF pakai PyMuPDF."""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages.append(f"[Halaman {i+1}]\n{text}")
        doc.close()
        return "\n\n".join(pages) if pages else "[PDF tidak mengandung teks yang bisa diekstrak]"
    except Exception as e:
        return f"[Gagal baca PDF: {e}]"

def smart_chunk(text: str, chunk_size: int = 1500, overlap: int = 200) -> list:
    """Chunk dengan overlap agar konteks tidak putus."""
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        if end < length:
            newline_pos = text.rfind("\n", start, end)
            if newline_pos > start + chunk_size // 2:
                end = newline_pos + 1
            else:
                space_pos = text.rfind(" ", start, end)
                if space_pos > start + chunk_size // 2:
                    end = space_pos + 1
        chunks.append(text[start:end])
        start = end - overlap

    return chunks

def save_user_doc(user: str, filename: str, content: str):
    user_dir = DOCS_DIR / user
    user_dir.mkdir(exist_ok=True)
    (user_dir / filename).write_text(content, encoding="utf-8")

    if user not in state:
        state[user] = {}
    docs = state[user].get("docs", {})
    docs[filename] = {
        "chunks": smart_chunk(content),
        "length": len(content),
        "lines": content.count("\n") + 1,
    }
    state[user]["docs"] = docs
    save_state(state)

def get_user_docs(user: str) -> dict:
    return state.get(user, {}).get("docs", {})

def search_doc_chunks(user: str, query: str, top_k: int = 5) -> str:
    """Cari chunk paling relevan dari semua dokumen."""
    docs = get_user_docs(user)
    if not docs:
        return ""

    query_words = set(query.lower().split())
    results = []

    for filename, doc_data in docs.items():
        for i, chunk in enumerate(doc_data["chunks"]):
            score = sum(1 for w in query_words if w in chunk.lower())
            if score > 0:
                results.append((score, filename, i, chunk))

    results.sort(key=lambda x: -x[0])

    if not results:
        # Fallback: ambil awal semua dokumen
        for filename, doc_data in docs.items():
            for chunk in doc_data["chunks"][:2]:
                results.append((0, filename, 0, chunk))

    formatted = []
    for _, filename, idx, chunk in results[:top_k]:
        formatted.append(f"[📄 {filename} | bagian {idx+1}]\n{chunk}")

    return "\n\n---\n\n".join(formatted)

def get_full_doc(user: str, filename: str) -> str:
    path = DOCS_DIR / user / filename
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""

# ───────────────────────────────────────────
# DETEKSI MODE
# ───────────────────────────────────────────

def detect_mode(text: str, user: str) -> str:
    t = text.lower()
    user_docs = get_user_docs(user)

    # Cek dokumen dulu
    doc_edit_kw = ["edit", "ubah", "tambahin", "tambah", "hapus", "revisi",
                   "update", "recreate", "generate ulang", "buat ulang", "tulis ulang",
                   "ganti", "perbaiki isi", "modifikasi"]
    if user_docs and any(k in t for k in doc_edit_kw):
        return "doc_edit"

    doc_query_kw = ["dokumen", "file", "isi", "baca", "lihat file", "konten"]
    if user_docs and (any(k in t for k in doc_query_kw) or
                      any(fname.lower().replace(".", "") in t.replace(".", "") for fname in user_docs)):
        return "doc_query"

    # Code review
    code_kw = ["review", "kodingan", "kode", "code", "bug", "error", "debug",
                "perbaiki", "refactor", "fungsi", "function", "class", "script",
                "python", "javascript", "typescript", "java", "golang", "php",
                "sql", "html", "css", "docker", "git"]
    if any(k in t for k in code_kw) or "```" in text:
        return "code_review"

    # Web search
    search_kw = ["cari", "search", "googling", "berita", "news", "terbaru",
                 "update", "harga", "cuaca", "jadwal", "hari ini", "sekarang",
                 "2024", "2025", "2026", "cek", "temukan", "info tentang",
                 "apa itu", "siapa", "berapa", "kapan", "dimana", "di mana",
                 "kurs", "nilai tukar", "exchange rate", "trending", "viral",
                 "rilis", "launch", "release"]
    if any(k in t for k in search_kw):
        return "web_search"

    return "chat"

# ───────────────────────────────────────────
# SYSTEM PROMPTS
# ───────────────────────────────────────────

def build_system_prompt(mode: str, extra_ctx: str = "", user: str = "") -> str:
    base = """Kamu adalah dapoAI — asisten pribadi cerdas milik Daffa.

Kepribadian:
- Santai dan chill tapi tajam dan informatif
- Bahasa Indonesia natural, boleh campur Inggris
- Singkat tapi padat, tidak bertele-tele
- Jujur kalau tidak tahu, tapi selalu berusaha bantu

"""

    if mode == "web_search":
        return base + f"""Mode: WEB SEARCH

Data dari internet yang sudah aku kumpulkan:
{extra_ctx}

INSTRUKSI:
- Jawab LANGSUNG berdasarkan data di atas
- Kalau ada angka/fakta spesifik, sebutkan dengan jelas
- Jangan bilang "tidak ada hasil" — data sudah ada di atas, olah saja
- Sebutkan sumber URL kalau relevan
- Kalau data memang tidak ada yang spesifik, akui tapi tetap berikan yang ada
"""

    elif mode == "code_review":
        return base + """Mode: CODE REVIEW

Format review:
🔍 **Analisis** — gambaran umum kode
⚠️ **Masalah** — bug, security issue, bad practice
✅ **Solusi** — kode yang sudah diperbaiki
💡 **Tips** — saran optimasi/best practice
"""

    elif mode == "doc_query":
        docs_list = list(get_user_docs(user).keys())
        return base + f"""Mode: BACA DOKUMEN

Dokumen tersedia: {', '.join(docs_list)}

Konten relevan:
{extra_ctx}

Jawab berdasarkan isi dokumen. Sebutkan nama file sumbernya.
"""

    elif mode == "doc_edit":
        docs_list = list(get_user_docs(user).keys())
        return base + f"""Mode: EDIT DOKUMEN

Dokumen tersedia: {', '.join(docs_list)}

Konten dokumen saat ini:
{extra_ctx}

INSTRUKSI EDIT:
- Lakukan perubahan yang diminta dengan presisi
- Output SELALU berupa konten dokumen LENGKAP setelah diedit
- Wrap output dalam code block dengan ekstensi yang sesuai (```python, ```md, dll)
- Jangan hilangkan bagian yang tidak diminta untuk diubah
- Kalau recreate/tulis ulang: buat versi baru yang lebih baik tapi pertahankan struktur/tujuan aslinya
"""

    else:
        return base + "Jawab dengan natural dan helpful."

# ───────────────────────────────────────────
# ENDPOINT — CHAT
# ───────────────────────────────────────────

class ChatReq(BaseModel):
    user_id: str
    message: str

@app.post("/chat")
def chat(req: ChatReq):
    user = req.user_id
    text = req.message

    mode = detect_mode(text, user)
    extra_ctx = ""

    if mode == "web_search":
        extra_ctx = web_search(text)

    elif mode in ("doc_query", "doc_edit"):
        user_docs = get_user_docs(user)

        # Cari nama file yang disebut user
        target_file = None
        for fname in user_docs:
            name_no_ext = fname.lower().rsplit(".", 1)[0]
            if name_no_ext in text.lower():
                target_file = fname
                break

        if mode == "doc_edit":
            # Edit butuh full konten
            if target_file:
                full = get_full_doc(user, target_file)
                extra_ctx = f"File: {target_file}\n\n{full}"
            else:
                # Ambil semua kalau tidak spesifik
                all_docs = []
                for fname in user_docs:
                    full = get_full_doc(user, fname)
                    all_docs.append(f"File: {fname}\n\n{full}")
                extra_ctx = "\n\n===\n\n".join(all_docs)
        else:
            extra_ctx = search_doc_chunks(user, text)

    memory = get_memory(user)
    messages = [
        {"role": "system", "content": build_system_prompt(mode, extra_ctx, user)}
    ] + memory + [
        {"role": "user", "content": text}
    ]

    reply = ask_llm(messages)
    update_memory(user, "user", text)
    update_memory(user, "assistant", reply)

    return {"reply": reply, "mode": mode}

# ───────────────────────────────────────────
# ENDPOINT — UPLOAD DOKUMEN
# ───────────────────────────────────────────

@app.post("/upload/{user_id}")
async def upload_doc(user_id: str, file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        return {"error": f"Format {ext} belum didukung. Gunakan: {', '.join(SUPPORTED_EXTS)}"}

    raw = await file.read()
    if ext == ".pdf":
        content = read_pdf(raw)
    else:
        content = raw.decode("utf-8", errors="replace")
    save_user_doc(user_id, file.filename, content)
    doc_info = get_user_docs(user_id)[file.filename]

    return {
        "status": "ok",
        "filename": file.filename,
        "lines": doc_info["lines"],
        "chunks": len(doc_info["chunks"]),
        "length": doc_info["length"],
    }

# ───────────────────────────────────────────
# ENDPOINT — SAVE DOKUMEN HASIL EDIT
# ───────────────────────────────────────────

class SaveDocReq(BaseModel):
    user_id: str
    filename: str
    content: str

@app.post("/save_doc")
def save_doc(req: SaveDocReq):
    save_user_doc(req.user_id, req.filename, req.content)
    return {"status": "ok", "filename": req.filename}

# ───────────────────────────────────────────
# ENDPOINT — LIST & DELETE DOCS
# ───────────────────────────────────────────

@app.get("/docs/{user_id}")
def list_docs(user_id: str):
    docs = get_user_docs(user_id)
    return {
        fname: {"lines": d["lines"], "chunks": len(d["chunks"]), "length": d["length"]}
        for fname, d in docs.items()
    }

@app.delete("/docs/{user_id}/{filename}")
def delete_doc(user_id: str, filename: str):
    path = DOCS_DIR / user_id / filename
    if path.exists():
        path.unlink()
    if user_id in state and filename in state[user_id].get("docs", {}):
        del state[user_id]["docs"][filename]
        save_state(state)
    return {"status": "deleted", "filename": filename}

# ───────────────────────────────────────────
# ENDPOINT — MEMORY
# ───────────────────────────────────────────

@app.get("/memory/{user_id}")
def get_user_memory(user_id: str):
    return {"memory": get_memory(user_id)}

@app.delete("/memory/{user_id}")
def clear_memory(user_id: str):
    if user_id in state:
        state[user_id]["memory"] = []
        save_state(state)
    return {"status": "ok"}

# ───────────────────────────────────────────
# ENDPOINT — TEST SEARCH
# ───────────────────────────────────────────

@app.get("/search")
def search_endpoint(q: str, max: int = 5):
    return {"results": web_search(q, max)}