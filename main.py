
from flask import Flask, request
import openai
import requests
import os
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

TELEGRAM_TOKEN = "7942085031:AAERWupDOXiDvqA1LE-EWTE8JM9n3Qa0v44"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

sessions = {}
lead_progress = {}
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("avalon-424200-6e629f8957b0.json", scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read()[:3000])
    return "\n\n".join(context_parts)

def load_system_prompt():
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    print("🔔 Входящее сообщение от Telegram:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    username = message.get("from", {}).get("username", "")
    language = message.get("from", {}).get("language_code", "")
    first_name = message.get("from", {}).get("first_name", "")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    if user_id in lead_progress:
        stage = lead_progress[user_id]["stage"]
        if stage == "platform":
            lead_progress[user_id]["platform"] = text
            lead_progress[user_id]["stage"] = "contact" if "whatsapp" in text.lower() else "name"
            ask = "Можете, пожалуйста, указать номер WhatsApp?" if "whatsapp" in text.lower() else "Как к вам можно обращаться?"
            send_telegram_message(chat_id, ask)
            return "ok"
        elif stage == "name":
            lead_progress[user_id]["name"] = text
            lead_progress[user_id]["stage"] = "contact"
            send_telegram_message(chat_id, "Куда вам удобнее получить ссылку — в Telegram или WhatsApp?")
            return "ok"
        elif stage == "contact":
            lead_progress[user_id]["contact"] = text if text.lower() != "telegram" else f"Telegram @{username or first_name}"
            lead_progress[user_id]["stage"] = "time"
            send_telegram_message(chat_id, "Когда вам удобнее — утром или после обеда?")
            return "ok"
        elif stage == "time":
            lead_progress[user_id]["time"] = text
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                lead_progress[user_id].get("name", first_name),
                str(user_id),
                lead_progress[user_id].get("contact", f"Telegram @{username or first_name}"),
                lead_progress[user_id].get("platform", ""),
                lead_progress[user_id].get("time", ""),
                "—",
                language
            ]
            sheet.append_row(row)
            send_telegram_message(chat_id, "Спасибо! Я передал информацию нашему менеджеру — он скоро свяжется с вами.")
            lead_progress.pop(user_id)
            return "ok"

    if text.strip().lower() in ["/start"]:
        sessions[user_id] = []
        lead_progress.pop(user_id, None)
        send_telegram_message(chat_id, "👋 Привет! Я — AI ассистент Avalon. Спросите про OM, BUDDHA, TAO или инвестиции на Бали.")
        return "ok"

    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}
    ] + history[-2:] + [{"role": "user", "content": text}]

    try:
        response = openai.chat.completions.create(model="gpt-4-turbo", messages=messages)
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        reply = f"Произошла ошибка при обращении к OpenAI:\n\n{e}"
        print("❌ Ошибка GPT:", e)

    sessions[user_id] = (history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]

    if "звонок" in text.lower() or "созвон" in text.lower() or "встретиться" in text.lower():
        lead_progress[user_id] = {"stage": "platform"}
        send_telegram_message(chat_id, "Могу согласовать звонок с нашим менеджером. Удобнее в Zoom, Google Meet или мессенджере?")
        return "ok"

    send_telegram_message(chat_id, reply)
    return "ok"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT бот работает и собирает лиды."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
