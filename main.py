
from flask import Flask, request
import openai
import requests
import os
import gspread
import json
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

def is_meaningful_reply(expected_question, user_reply):
    check_prompt = f"Ты AI-помощник. Ты задал клиенту вопрос: '{expected_question}'\n\nКлиент ответил: '{user_reply}'\n\nЭто ответ на твой вопрос? Ответь 'да' или 'нет'."
    try:
        check_response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": check_prompt}]
        )
        check_answer = check_response.choices[0].message.content.strip().lower()
        return check_answer.startswith("да")
    except Exception as e:
        print("Ошибка при анализе смысла ответа:", e)
        return False

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
        lead = lead_progress[user_id]
        stage = lead["stage"]

        if stage == "platform":
            if is_meaningful_reply("Вы предпочитаете Zoom, Google Meet или WhatsApp?", text):
                lead["platform"] = text
                if "whatsapp" in text.lower():
                    lead["stage"] = "whatsapp_number"
                    send_telegram_message(chat_id, "Укажите, пожалуйста, номер WhatsApp, по которому с вами можно связаться.")
                else:
                    lead["stage"] = "name"
                    send_telegram_message(chat_id, "Как мне вас называть?")
                return "ok"
            else:
                sessions[user_id] = sessions.get(user_id, [])
                return "ok"

        if stage == "whatsapp_number":
            if is_meaningful_reply("Укажите, пожалуйста, номер WhatsApp, по которому с вами можно связаться.", text):
                lead["contact"] = text
                lead["stage"] = "name"
                send_telegram_message(chat_id, "Как мне вас называть?")
                return "ok"
            else:
                sessions[user_id] = sessions.get(user_id, [])
                return "ok"

        if stage == "name":
            if is_meaningful_reply("Как мне вас называть?", text):
                lead["name"] = text
                if lead["platform"].lower() in ["zoom", "google meet", "meet"]:
                    lead["stage"] = "link_contact"
                    send_telegram_message(chat_id, "Я могу отправить ссылку прямо сюда, в этот чат — будет удобно?")
                else:
                    lead["stage"] = "datetime"
                    send_telegram_message(chat_id, "Когда вам удобно созвониться? Например, сегодня вечером или завтра утром — как вам комфортнее?")
                return "ok"
            else:
                sessions[user_id] = sessions.get(user_id, [])
                return "ok"

        if stage == "link_contact":
            if is_meaningful_reply("Я могу отправить ссылку прямо сюда, в этот чат — будет удобно?", text):
                if any(x in text.lower() for x in ["telegram", "тг", "сюда", "здесь", "в этом чате"]):
                    lead["contact"] = f"Telegram @{username or first_name}"
                else:
                    lead["contact"] = text
                lead["stage"] = "datetime"
                send_telegram_message(chat_id, "Когда вам удобно созвониться? Например, сегодня вечером или завтра утром — как вам комфортнее?")
                return "ok"
            else:
                sessions[user_id] = sessions.get(user_id, [])
                return "ok"

        if stage == "datetime":
            if is_meaningful_reply("Когда вам удобно созвониться? Например, сегодня вечером или завтра утром — как вам комфортнее?", text):
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
            else:
                sessions[user_id] = sessions.get(user_id, [])
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

{documents_context}"}
    ] + history[-2:] + [{"role": "user", "content": text}]

    try:
        response = openai.chat.completions.create(model="gpt-4o", messages=messages)
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
