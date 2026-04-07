import os
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_TOKEN")
API_URL = os.getenv("API_URL", "http://localhost:8000")

SUPPORTED_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json",
                  ".csv", ".html", ".css", ".xml", ".pdf"}

MODE_LABEL = {
    "chat":        "💬",
    "code_review": "🔍",
    "web_search":  "🌐",
    "doc_query":   "📄",
    "doc_edit":    "✏️",
    "error":       "❌",
}

# ───────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────

async def call_chat(user_id: str, message: str, username: str = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{API_URL}/chat",
                json={"user_id": user_id, "message": message, "username": username},
            )
            r.raise_for_status()
            return r.json()
    except httpx.TimeoutException:
        return {"reply": "⏱️ Timeout nih, coba lagi ya.", "mode": "error"}
    except Exception as e:
        return {"reply": f"❌ Error: {e}", "mode": "error"}

async def send_long(update: Update, text: str):
    if len(text) <= 4096:
        try:
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(text)
        return
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(chunk)

# ───────────────────────────────────────────
# COMMANDS
# ───────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Yo! Aku *dapoAI* — asisten pribadi lo 🤖\n\n"
        "*Kemampuan:*\n"
        "💬 Ngobrol & tanya apapun\n"
        "🔍 Review & debug kode\n"
        "🌐 Cari info terbaru dari internet\n"
        "📄 Baca & analisis dokumen\n"
        "✏️ Edit dokumen\n\n"
        "*Commands:*\n"
        "/reset — hapus history chat\n"
        "/docs — lihat dokumen tersimpan\n\n"
        "Kirim file langsung buat upload dokumen 📎\n\nGas!",
        parse_mode="Markdown",
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.delete(f"{API_URL}/memory/{user_id}")
            r.raise_for_status()
        await update.message.reply_text("✅ Memory di-reset. Fresh start!")
    except Exception:
        await update.message.reply_text("❌ Gagal reset, coba lagi.")

async def list_docs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{API_URL}/docs/{user_id}")
            r.raise_for_status()
            docs = r.json()
            
        if not docs:
            await update.message.reply_text("📭 Belum ada dokumen tersimpan.")
            return
        lines = ["📚 *Dokumen tersimpan:*\n"]
        for d in docs:
            lines.append(
                f"• `{d['filename']}` — {d['total_lines']} baris · {d['total_chunks']} chunk"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ───────────────────────────────────────────
# PESAN TEKS
# ───────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    text     = update.message.text

    await update.message.chat.send_action("typing")

    result = await call_chat(user_id, text, username)
    reply  = result.get("reply", "❌ Tidak ada respon.")
    mode   = result.get("mode", "chat")

    await send_long(update, f"{reply}\n\n{MODE_LABEL.get(mode, '💬')}")

# ───────────────────────────────────────────
# UPLOAD FILE
# ───────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = str(update.effective_user.id)
    doc      = update.message.document
    filename = doc.file_name or "file.txt"
    ext      = os.path.splitext(filename)[1].lower()

    if ext not in SUPPORTED_EXTS:
        await update.message.reply_text(
            f"❌ Format `{ext}` belum didukung.\n"
            f"Yang bisa: {', '.join(sorted(SUPPORTED_EXTS))}",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("⏳ Lagi proses file lo, tunggu sebentar...")
    await update.message.chat.send_action("upload_document")

    try:
        file       = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()
        mime       = "application/pdf" if ext == ".pdf" else "text/plain"

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": (filename, bytes(file_bytes), mime)}
            r = await client.post(
                f"{API_URL}/upload/{user_id}",
                files=files
            )
            r.raise_for_status()
            result = r.json()

        if "error" in result:
            await update.message.reply_text(f"❌ {result['error']}")
            return

        await update.message.reply_text(
            f"✅ *{filename}* berhasil diupload!\n"
            f"📊 {result['lines']} baris · {result['chunks']} chunk\n\n"
            f"Sekarang tanya aja tentang isinya!",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal upload: {e}")

# ───────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("docs", list_docs))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 dapoAI bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()