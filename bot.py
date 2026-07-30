import json
import os
import time

from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# --------------------------------------------------
# Environment variables
# --------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]

# Public URL where the run log can be downloaded
LOG_URL = "https://raw.githubusercontent.com/23f2005546/data-analyst-telegram-bot/main/run.jsonl"


# --------------------------------------------------
# AI Pipe client
# --------------------------------------------------

client = OpenAI(
    base_url="https://aipipe.org/openai/v1",
    api_key=AIPIPE_TOKEN,
)


# --------------------------------------------------
# Local log file
# --------------------------------------------------

LOG_FILE = "run.jsonl"


# --------------------------------------------------
# Conversation history
# --------------------------------------------------

conversation_history = {}


# --------------------------------------------------
# Logging
# --------------------------------------------------

def log_event(event):
    event["timestamp"] = time.time()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


# --------------------------------------------------
# /start
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Data Analyst Bot is ready. Send me a data-analysis question."
    )


# --------------------------------------------------
# Main message handler
# --------------------------------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text

    # Log incoming message
    log_event({
        "type": "incoming",
        "chat_id": chat_id,
        "text": user_text,
    })

    # Get conversation history for this chat
    history = conversation_history.setdefault(chat_id, [])

    history.append({
        "role": "user",
        "content": user_text,
    })

    # Keep only recent context
    recent_history = history[-6:]

    system_prompt = f"""
You are a careful data analyst.

The user's LAST message contains a data-analysis question and specifies
the exact JSON object shape that must be returned.

Solve the question correctly.

IMPORTANT RULES:

1. Answer the LAST user message.
2. Use earlier messages only when they are necessary context.
3. Return ONLY one valid JSON object.
4. Do NOT use markdown.
5. Do NOT use code fences.
6. Do NOT add explanations.
7. Do NOT add extra JSON keys.
8. Match the requested JSON structure exactly.
9. If the requested object contains a log_url field, use this exact URL:
   {LOG_URL}
10. If the requested object does NOT contain log_url, do NOT add log_url.
11. The final response must be valid JSON.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                }
            ] + recent_history,
        )

        reply_text = response.choices[0].message.content.strip()

    except Exception as e:
        print("AI error:", e)

        error_response = {
            "error": "AI request failed"
        }

        final_reply = json.dumps(error_response)

        log_event({
            "type": "outgoing",
            "chat_id": chat_id,
            "text": final_reply,
        })

        await update.message.reply_text(final_reply)
        return

    # Save AI response to conversation history
    history.append({
        "role": "assistant",
        "content": reply_text,
    })

    # --------------------------------------------------
    # Parse JSON
    # --------------------------------------------------

    try:
        parsed = json.loads(reply_text)

    except json.JSONDecodeError:

        # Try extracting the JSON object
        start = reply_text.find("{")
        end = reply_text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            final_reply = json.dumps({
                "error": "Invalid JSON response"
            })

            log_event({
                "type": "outgoing",
                "chat_id": chat_id,
                "text": final_reply,
            })

            await update.message.reply_text(final_reply)
            return

        try:
            parsed = json.loads(
                reply_text[start:end + 1]
            )

        except json.JSONDecodeError:
            final_reply = json.dumps({
                "error": "Invalid JSON response"
            })

            log_event({
                "type": "outgoing",
                "chat_id": chat_id,
                "text": final_reply,
            })

            await update.message.reply_text(final_reply)
            return

    # Make sure the AI returned a JSON object
    if not isinstance(parsed, dict):
        parsed = {
            "answer": parsed
        }

    # --------------------------------------------------
    # Send exactly the JSON object returned by the model
    # --------------------------------------------------

    final_reply = json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":")
    )

    # Log outgoing answer
    log_event({
        "type": "outgoing",
        "chat_id": chat_id,
        "text": final_reply,
    })

    # Send answer to Telegram
    await update.message.reply_text(final_reply)


# --------------------------------------------------
# Telegram application
# --------------------------------------------------

app = ApplicationBuilder().token(
    TELEGRAM_BOT_TOKEN
).build()


# /start command
app.add_handler(
    CommandHandler("start", start)
)


# Normal text messages
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)


print("Bot is running...")

app.run_polling()