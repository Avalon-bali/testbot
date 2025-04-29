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

ADMIN_ID = 5275555034
sessions = {}
last_message_time = {}
fsm_state = {}
lead_data = {}

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def detect_time_of_day(text):
    t = text.lower()
    if "утро" in t: return "утром"
    if "вечер" in t: return "вечером"
    if "день" in t: return "днём"
    return "в удобное для вас время"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")
    username = message.get("from", {}).get("username", "")
    language_code = message.get("from", {}).get("language_code", "en")

    if not chat_id:
        return "no chat_id", 400

    now = time.time()
    if now - last_message_time.get(user_id, 0) < 1:
        return "rate limit", 429
    last_message_time[user_id] = now

    if user_id in fsm_state:
        step = fsm_state[user_id]
        answer = text.strip()
        if step == "ask_name":
            lead_data[user_id]["name"] = answer
            fsm_state[user_id] = "ask_platform"
            send_telegram_message(chat_id, "📱 Укажите платформу для связи: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif step == "ask_platform":
            lead_data[user_id]["platform"] = answer
            if "whatsapp" in answer.lower() or "ватсап" in answer.lower() or "вотсап" in answer.lower():
                fsm_state[user_id] = "ask_phone"
                send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:")
            else:
                fsm_state[user_id] = "ask_datetime"
                send_telegram_message(chat_id, "🗓 Когда удобно созвониться? (например: завтра утром)")
            return "ok"
        elif step == "ask_phone":
            lead_data[user_id]["phone"] = answer
            fsm_state[user_id] = "ask_datetime"
            send_telegram_message(chat_id, "🗓 Когда удобно созвониться? (например: завтра утром)")
            return "ok"
        elif step == "ask_datetime":
            lead_data[user_id]["datetime"] = answer
            # Финал: записать в таблицу
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
                part_day = detect_time_of_day(answer)
                platform = lead_data[user_id].get("platform", "выбранная платформа")
                send_telegram_message(chat_id, f"✅ Отлично! Все данные переданы менеджеру. Мы свяжемся с вами через {platform} {part_day}.")
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Ошибка записи в таблицу: {e}")
            fsm_state.pop(user_id)
            lead_data.pop(user_id)
            return "ok"

    if any(x in text.lower() for x in ["звонок", "созвон", "консультац"]):
        fsm_state[user_id] = "ask_name"
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "👋 Напишите, пожалуйста, ваше имя:")
        return "ok"

    send_telegram_message(chat_id, "Здравствуйте! Я AI Assistant компании Avalon, рад помочь с вопросами о проектах. Чем могу быть полезен?")
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает стабильно."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
