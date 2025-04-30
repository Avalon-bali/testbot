from flask import Flask, request
import openai
import requests
import os
import time
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

# Состояния пользователей
sessions = {}
fsm_state = {}
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

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    language_code = message.get("from", {}).get("language_code", "en")

    if not chat_id:
        return "no chat_id", 400

    # FSM логика
    if user_id in fsm_state:
        step = fsm_state[user_id]
        answer = text

        if step == "ask_name":
            lead_data[user_id]["name"] = answer
            fsm_state[user_id] = "ask_platform"
            send_telegram_message(chat_id, "📱 Укажите платформу для связи: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif step == "ask_platform":
            lead_data[user_id]["platform"] = answer
            if "whatsapp" in answer.lower():
                fsm_state[user_id] = "ask_phone"
                send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:")
            else:
                fsm_state[user_id] = "ask_datetime"
                send_telegram_message(chat_id, "🗓 Когда удобно созвониться?")
            return "ok"
        elif step == "ask_phone":
            lead_data[user_id]["phone"] = answer
            fsm_state[user_id] = "ask_datetime"
            send_telegram_message(chat_id, "🗓 Когда удобно созвониться?")
            return "ok"
        elif step == "ask_datetime":
            lead_data[user_id]["datetime"] = answer
            try:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                sheet.append_row([
                    now_str,
                    lead_data[user_id].get("name", ""),
                    f"@{username}",
                    lead_data[user_id].get("phone", ""),
                    answer.split()[0] if len(answer.split()) > 0 else "",
                    answer.split()[1] if len(answer.split()) > 1 else "",
                    lead_data[user_id].get("platform", ""),
                    "",
                    language_code
                ])
                send_telegram_message(chat_id, "✅ Отлично! Все данные переданы менеджеру. Мы свяжемся с вами в указанное время.")
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Ошибка записи: {e}")
            fsm_state.pop(user_id)
            lead_data.pop(user_id)
            return "ok"

    # Старт команды
    if text == "/start":
        sessions[user_id] = []
        send_telegram_message(chat_id, "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?")
        return "ok"

    # История для GPT
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}\n\nЕсли пользователь хочет консультацию или звонок, верни только: [CALL_REQUEST]."},
    ] + history[-6:] + [{"role": "user", "content": text}]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        reply = f"⚠️ Ошибка OpenAI: {e}"

    # Обработка желания записаться на звонок
    if reply == "[CALL_REQUEST]":
        fsm_state[user_id] = "ask_name"
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "👋 Как к вам можно обращаться?")
        return "ok"

    # Сохраняем историю
    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
