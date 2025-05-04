from flask import Flask, request
import openai
import requests
import os
import re
from datetime import datetime

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

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

def load_system_prompt():
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    lang_code = message.get("from", {}).get("language_code", "ru")

    if not chat_id:
        return "no chat_id", 400

    if text.lower() == "/start":
        welcome = "👋 Привет! Я — AI ассистент Avalon.\nСпросите про OM, BUDDHA, TAO или про инвестиции на Бали."
        sessions[user_id] = []
        lead_data.pop(user_id, None)
        send_telegram_message(chat_id, welcome)
        return "ok"

    # FSM: начало при ключевых словах
    if user_id not in lead_data and any(w in text.lower() for w in call_request_triggers):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\nКак к вам можно обращаться?")
        return "ok"

    if user_id in lead_data:
        lead = lead_data[user_id]
        if "name" not in lead:
            lead["name"] = text
            send_telegram_message(chat_id, "📱 Укажите платформу для звонка: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif "platform" not in lead:
            lead["platform"] = text
            if text.lower() == "whatsapp":
                send_telegram_message(chat_id, "📞 Пожалуйста, напишите номер WhatsApp:")
            else:
                send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"
        elif lead.get("platform", "").lower() == "whatsapp" and "phone" not in lead:
            lead["phone"] = text
            send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"
        elif "datetime" not in lead:
            lead["datetime"] = text
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
            lead_data.pop(user_id, None)
            return "ok"
        else:
            send_telegram_message(chat_id, "📌 Давайте сначала завершим оформление деталей звонка, и я сразу продолжу.")
            return "ok"

    # GPT логика
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}
    ] + history[-6:] + [
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
        reply = re.sub(r"\*\*(.*?)\*\*", r"\1", reply)
    except Exception as e:
        reply = f"Произошла ошибка при обращении к OpenAI:\n\n{e}"
        print("❌ Ошибка GPT:", e)

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot is running with GPT + FSM lead form."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
