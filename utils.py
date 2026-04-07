from typing import List, Dict
import fitz  # PyMuPDF
from config import CHUNK_SIZE, CHUNK_OVERLAP
from database import get_user_documents

def read_pdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages.append(f"[Halaman {i+1}]\n{text}")
        doc.close()
        return "\n\n".join(pages) if pages else "[PDF tidak mengandung teks]"
    except Exception as e:
        return f"[Gagal baca PDF: {e}]"

def smart_chunk(text: str) -> list:
    chunks, start = [], 0
    length = len(text)
    while start < length:
        end = start + CHUNK_SIZE
        if end < length:
            nl = text.rfind("\n", start, end)
            if nl > start + CHUNK_SIZE // 2:
                end = nl + 1
            else:
                sp = text.rfind(" ", start, end)
                if sp > start + CHUNK_SIZE // 2:
                    end = sp + 1
        chunks.append(text[start:end])
        start = end - CHUNK_OVERLAP
        # Prevent infinite loops if CHUNK_OVERLAP is large
        if start < end - CHUNK_SIZE + 1:
            start = end
    return chunks

def detect_mode(text: str, user_id: str) -> str:
    t = text.lower()
    user_docs = get_user_documents(user_id)
    doc_filenames = [d["filename"] for d in user_docs]

    doc_edit_kw = ["edit", "ubah", "tambahin", "tambah", "hapus", "revisi",
                   "update", "recreate", "buat ulang", "tulis ulang", "ganti", "modifikasi"]
    if user_docs and any(k in t for k in doc_edit_kw):
        return "doc_edit"

    doc_query_kw = ["dokumen", "file", "isi", "baca", "lihat", "konten", "jelaskan"]
    if user_docs and (any(k in t for k in doc_query_kw) or
                      any(f.lower().rsplit(".", 1)[0] in t for f in doc_filenames)):
        return "doc_query"

    code_kw = ["review", "kodingan", "kode", "code", "bug", "error", "debug",
               "perbaiki", "refactor", "fungsi", "function", "class", "script",
               "python", "javascript", "typescript", "java", "golang", "php",
               "sql", "html", "css", "docker", "git"]
    if any(k in t for k in code_kw) or "```" in text:
        return "code_review"

    search_kw = ["cari", "search", "googling", "berita", "news", "terbaru",
                 "harga", "cuaca", "jadwal", "hari ini", "sekarang", "2024",
                 "2025", "2026", "cek", "temukan", "info tentang", "apa itu",
                 "siapa", "berapa", "kapan", "dimana", "di mana", "kurs",
                 "nilai tukar", "exchange rate", "trending", "viral", "rilis"]
    if any(k in t for k in search_kw):
        return "web_search"

    return "chat"

def build_system_prompt(mode: str, extra_ctx: str = "", user_id: str = "") -> str:
    base = """Kamu adalah dapoAI — asisten pribadi cerdas milik Daffa.

Kepribadian & Aturan Penting:
- **WAJIB 100% menggunakan Bahasa Indonesia**. Jangan pernah membalas dalam bahasa Inggris meskipun konten atau dokumennya berbahasa Inggris. Kalau ada teks asing, pahami isinya dan jawab langsung dalam Bahasa Indonesia.
- Jawaban harus terstruktur rapi, singkat, dan padat.
- **FORMATTING WAJIB MAXIMAL TELEGRAM MARKDOWN**: Sebisa mungkin HANYA gunakan `*bold*`, `_italic_`, `[teks](URL)`, dan ````code block````. JANGAN GUNAKAN format HTML (seperti <b>, <i>, atau tabel <table>) karena akan merusak tampilan di Telegram.

"""
    if mode == "web_search":
        return base + f"""Mode: WEB SEARCH

Data dari internet:
{extra_ctx}

INSTRUKSI:
- Jawab LANGSUNG berdasarkan data di atas menggunakan BAHASA INDONESIA.
- Tetap gunakan format Telegram Markdown yang rapi tanpa tabel atau HTML.
- Sebutkan sumber URL kalau relevan.
"""

    elif mode == "code_review":
        return base + """Mode: CODE REVIEW

Format review dalam Bahasa Indonesia (gunakan markdown standar Telegram):
🔍 *Analisis* — gambaran umum kode
⚠️ *Masalah* — bug, security issue, bad practice
✅ *Solusi* — kode yang sudah diperbaiki
💡 *Tips* — saran optimasi/best practice
"""

    elif mode == "doc_query":
        docs = get_user_documents(user_id)
        names = ", ".join(d["filename"] for d in docs)
        return base + f"""Mode: BACA DOKUMEN

Dokumen tersedia: {names}

Konten relevan (semantic search):
{extra_ctx}

INSTRUKSI:
1. Terjemahkan dan rangkum isi dokumen. **PENTING: Jawab menggunakan Bahasa Indonesia yang baik dan benar.**
2. Jawab berdasarkan isi dokumen HANYA. Sebutkan nama file dokumen asal secara rapi (contoh: *file_anda.pdf*).
3. Gunakan formatting Telegram Markdown standar. Dilarang keras menggunakan tags HTML.
"""

    elif mode == "doc_edit":
        docs = get_user_documents(user_id)
        names = ", ".join(d["filename"] for d in docs)
        return base + f"""Mode: EDIT DOKUMEN

Dokumen tersedia: {names}

Konten dokumen:
{extra_ctx}

INSTRUKSI:
- Lakukan perubahan yang diminta dengan presisi (berbahasa Indonesia untuk komen/teks, tetapi pertahankan bahasa asli untuk sintaks kode).
- Output konten dokumen LENGKAP setelah diedit di dalam code-block yang sesuai.
"""

    else:
        return base + "Jawab dengan natural, menggunakan bahasa Indonesia, dan formatting Telegram Markdown yang rapi."
