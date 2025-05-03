from flask import Flask, request
import openai
import requests
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

sessions = {}
lead_data = {}

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read())
    return "\n\n".join(context_parts)

def load_system_prompt():
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

call_request_triggers = [
    "созвон", "поговорить", "менеджер", "хочу звонок",
    "можно позвонить", "звонок", "давайте созвонимся",
    "обсудить", "свяжитесь со мной"
]

def send_telegram_message(chat_id, text, photo_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

    if photo_path and os.path.exists(photo_path):
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            requests.post(url_photo, files={'photo': photo}, data={'chat_id': chat_id})

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")

    if text.lower() == "/start":
        welcome_text = "👋 Привет! Я — AI ассистент Avalon.\nСпросите про OM, BUDDHA, TAO или про инвестиции на Бали."
        sessions[user_id] = []
        send_telegram_message(chat_id, welcome_text)
        return "ok"

    # Обработка запроса на звонок и диалога по шагам
    if user_id not in lead_data:
        if any(w in text.lower() for w in call_request_triggers):
            lead_data[user_id] = {}
            send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\n👋 Как к вам можно обращаться?")
            return "ok"
    else:
        if "name" not in lead_data[user_id]:
            lead_data[user_id]["name"] = text
            send_telegram_message(chat_id, "📅 Когда вам удобно созвониться? (например: сегодня вечером или завтра в 10:00)")
            return "ok"
        elif "time" not in lead_data[user_id]:
            lead_data[user_id]["time"] = text
            send_telegram_message(chat_id, "✅ Спасибо! Мы свяжемся с вами в указанное время.")
            return "ok"

    # Отправка картинки Avalon, если упоминается
    if "avalon" in text.lower():
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        send_telegram_message(chat_id, "*Avalon* — современная недвижимость на Бали.", photo_path=photo_path)
        return "ok"

    # GPT-запрос с контекстом
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"},
        *history[-6:],
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(model="gpt-4o", messages=messages)
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        reply = "Произошла ошибка при обращении к OpenAI."

    sessions[user_id] = (history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-10:]
    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT bot is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
