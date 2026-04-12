import os
import requests
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ── Config ──────────────────────────────────────────────
BOT_TOKEN   = "8503780301:AAEyT4dTCDic_Lye9zfxDi1LEo0Q1VWmsNU"
UPLOAD_URL  = "https://host.orange-print-tools.workers.dev/upload"
API_KEY     = "nxt_aiprime_B4rT9kP2Xy7aQ8sLm5VnD1ZcW3"
# ────────────────────────────────────────────────────────


def upload_to_host(file_bytes: bytes, filename: str) -> dict:
    """Upload raw bytes to the image host and return JSON response."""
    response = requests.post(
        UPLOAD_URL,
        headers={"X-API-Key": API_KEY},
        files={"file": (filename, file_bytes, "image/jpeg")},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Image Hosting Bot এ স্বাগতম!*\n\n"
        "📸 যেকোনো ছবি পাঠাও — আমি সেটা হোস্ট করে direct link দিয়ে দেবো!\n\n"
        "📌 Commands:\n"
        "/start — এই message\n"
        "/help  — সাহায্য",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 *কীভাবে ব্যবহার করবে:*\n\n"
        "1️⃣ Bot কে যেকোনো ছবি পাঠাও\n"
        "2️⃣ Bot সেটা upload করবে\n"
        "3️⃣ তুমি একটা permanent link পাবে\n\n"
        "⚠️ শুধু image file সাপোর্ট করে (JPG, PNG, WEBP, GIF)।",
        parse_mode="Markdown",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photos sent as compressed Telegram images."""
    msg = await update.message.reply_text("⏳ Upload হচ্ছে...")

    # Telegram gives multiple sizes — সবচেয়ে বড়টা নাও
    photo = update.message.photo[-1]
    file  = await context.bot.get_file(photo.file_id)

    file_bytes = await file.download_as_bytearray()
    filename   = f"{photo.file_unique_id}.jpg"

    try:
        result = upload_to_host(bytes(file_bytes), filename)
        if result.get("success"):
            image_url = result["url"]
            await msg.edit_text(
                f"✅ *Upload সফল!*\n\n"
                f"🔗 [Direct Link]({image_url})\n"
                f"`{image_url}`",
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        else:
            await msg.edit_text(f"❌ Upload ব্যর্থ হয়েছে: `{result}`", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle images sent as files/documents (uncompressed)."""
    doc = update.message.document

    # শুধু image MIME type check করো
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        await update.message.reply_text("⚠️ শুধু image file পাঠাও (JPG, PNG, WEBP, GIF)।")
        return

    msg  = await update.message.reply_text("⏳ Upload হচ্ছে...")
    file = await context.bot.get_file(doc.file_id)

    file_bytes = await file.download_as_bytearray()
    filename   = doc.file_name or f"{doc.file_unique_id}.jpg"

    try:
        result = upload_to_host(bytes(file_bytes), filename)
        if result.get("success"):
            image_url = result["url"]
            await msg.edit_text(
                f"✅ *Upload সফল!*\n\n"
                f"🔗 [Direct Link]({image_url})\n"
                f"`{image_url}`",
                parse_mode="Markdown",
                disable_web_page_preview=False,
            )
        else:
            await msg.edit_text(f"❌ Upload ব্যর্থ হয়েছে: `{result}`", parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 শুধু ছবি পাঠাও — text বা অন্য file নয়।")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO,    handle_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other))

    print("🤖 Bot চালু হয়েছে...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
