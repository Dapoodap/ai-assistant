import requests, os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")

API_URL = "http://localhost:8000/chat"

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = str(update.effective_user.id)
    text = update.message.text

    res = requests.post(API_URL, json={
        "user_id": user,
        "message": text
    })

    reply = res.json()["reply"]

    await update.message.reply_text(reply)

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, handle))

app.run_polling()