from flask import Flask, request
import openai
import requests
import os
import gspread
import json
import random
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

TELEGRAM_TOKEN = "7942085031:AAERWupDOXiDvqA1LE-EWTE8JM9n3Qa0v44"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

sessions = {}
lead_progress = {}
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
with open("/etc/secrets/google-credentials.json", "r") as f:
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json.load(f), scope)

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

    # FSM логика по этапам
    if user_id in lead_progress:
        lead = lead_progress[user_id]
        stage = lead["stage"]

        if stage == "platform":
            lead["platform"] = text
            if "whatsapp" in text.lower():
                lead["stage"] = "whatsapp_number"
                send_telegram_message(chat_id, "Пожалуйста, напишите номер WhatsApp, на который удобно связаться.")
            else:
                lead["stage"] = "name"
                send_telegram_message(chat_id, "Как к вам можно обращаться?")
            return "ok"

        elif stage == "whatsapp_number":
            lead["contact"] = text
            lead["stage"] = "name"
            send_telegram_message(chat_id, "Спасибо! А как к вам можно обращаться?")
            return "ok"

        elif stage == "name":
            lead["name"] = text
            if lead["platform"].lower() in ["zoom", "google meet", "meet"]:
                lead["stage"] = "link_contact"
                send_telegram_message(chat_id, "Куда вам отправить ссылку на звонок? Можно Telegram username или другой удобный способ.")
            else:
                lead["stage"] = "datetime"
                send_telegram_message(chat_id, "Когда вам удобно созвониться — сегодня, завтра или в другой день? И во сколько — в первой половине дня или во второй?")
            return "ok"

        elif stage == "link_contact":
            lead["contact"] = text
            lead["stage"] = "datetime"
            send_telegram_message(chat_id, "Спасибо! И когда вам удобно созвониться — сегодня, завтра или в другой день? И во сколько — в первой половине дня или во второй?")
            return "ok"

        elif stage == "datetime":
            lead["time"] = text
            for project in ["OM", "TAO", "BUDDHA"]:
                if project.lower() in text.lower():
                    lead["project"] = project
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                lead.get("name", first_name),
                str(user_id),
                lead.get("contact", f"Telegram @{username or first_name}"),
                lead.get("platform", ""),
                lead.get("time", ""),
                lead.get("project", "—"),
                language
            ]
            sheet.append_row(row)
            send_telegram_message(chat_id, f"✅ Звонок подтверждён. Менеджер свяжется с вами через {lead.get('platform', 'указанный канал')} в ближайшее удобное время. До встречи!")
            lead_progress.pop(user_id)
            return "ok"

    # Приветствие на старте с учётом языка
    if text.strip().lower() in ["/start"]:
        sessions[user_id] = []
        lead_progress.pop(user_id, None)

        greetings_ru = [
            "👋 Привет! Я — AI ассистент Avalon. Чем могу помочь вам сегодня?",
            "Здравствуйте! Готов ответить на ваши вопросы по OM, BUDDHA, TAO и инвестициям на Бали.",
            "Добро пожаловать! Я — AI консультант Avalon. Спросите про проекты или организуем звонок.",
        ]

        greetings_en = [
            "👋 Hello! I’m the AI assistant of Avalon. How can I help you today?",
            "Welcome! I can assist you with any questions about OM, BUDDHA, TAO or investing in Bali.",
        ]

        greetings_uk = [
            "👋 Вітаю! Я — AI-асистент Avalon. Чим можу допомогти сьогодні?",
            "Доброго дня! Готовий відповісти на ваші запитання про проєкти Avalon та інвестиції на Балі.",
        ]

        if language.startswith("en"):
            greeting = random.choice(greetings_en)
        elif language.startswith("uk"):
            greeting = random.choice(greetings_uk)
        else:
            greeting = random.choice(greetings_ru)

        send_telegram_message(chat_id, greeting)
        return "ok"

    # ChatGPT обработка
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

    if any(word in text.lower() for word in ["звонок", "созвон", "встретиться"]):
        lead_progress[user_id] = {"stage": "platform"}
        send_telegram_message(chat_id, "Хорошо! Уточните, пожалуйста: вы предпочитаете Zoom, Google Meet или WhatsApp?")
        return "ok"

    send_telegram_message(chat_id, reply)
    return "ok"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает. FSM и лиды активны."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
