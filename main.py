from flask import Flask, request
import openai
import requests
import os
import re
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

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

call_request_triggers = [
    "созвон", "поговорить", "менеджер", "хочу звонок", "можно позвонить",
    "звонок", "давайте созвонимся", "обсудить", "свяжитесь со мной"
]

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read())
    return "\n\n".join(context_parts)

def load_system_prompt(lang):
    fallback = "Ты — AI Assistant отдела продаж компании Avalon..."
    try:
        with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
            full_text = f.read()
            match = re.search(rf"### {lang}\n(.*?)\n###", full_text, re.DOTALL)
            if match:
                return match.group(1).strip()
    except:
        pass
    return fallback

def send_telegram_message(chat_id, text, photo_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
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
    lang_code = message.get("from", {}).get("language_code", "ru")

    if text.lower() == "/start":
        send_telegram_message(chat_id, "👋 Здравствуйте! Я — AI ассистент компании Avalon. Чем могу быть полезен?")
        return "ok"

    if user_id not in lead_data and any(w in text.lower() for w in call_request_triggers):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\n👋 Как к вам можно обращаться?")
        return "ok"

    if user_id in lead_data:
        lead = lead_data[user_id]
        if "name" not in lead:
            lead["name"] = text.capitalize()
            send_telegram_message(chat_id, "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif "platform" not in lead:
            lead["platform"] = text.capitalize()
            if lead["platform"].lower() == "whatsapp":
                send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:")
            else:
                send_telegram_message(chat_id, "🗓 Когда удобно созвониться?")
            return "ok"
        elif lead.get("platform", "").lower() == "whatsapp" and "phone" not in lead:
            lead["phone"] = text
            send_telegram_message(chat_id, "🗓 Когда удобно созвониться?")
            return "ok"
        elif "datetime" not in lead:
            lead["datetime"] = text
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            wa_url = f"https://wa.me/{lead.get('phone')}" if lead.get("platform").lower() == "whatsapp" else ""
            sheet.append_row([
                now, lead.get("name"), f"@{username}", lead.get("platform"),
                wa_url, lead.get("datetime"), "", lang_code
            ])
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
            lead_data.pop(user_id, None)
            return "ok"

    if "avalon" in text.lower():
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        send_telegram_message(chat_id, "Avalon – современная недвижимость на Бали.", photo_path=photo_path)
        return "ok"

    # GPT-ответ
    documents_context = load_documents()
    system_prompt = load_system_prompt(lang_code)
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"},
        *history[-6:],
        {"role": "user", "content": text}
    ]
    try:
        response = openai.chat.completions.create(model="gpt-4o", messages=messages)
        reply = response.choices[0].message.content.strip()
    except Exception:
        reply = "Произошла ошибка при обращении к OpenAI."

    sessions[user_id] = history[-8:] + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/")
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
