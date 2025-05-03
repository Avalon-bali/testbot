from flask import Flask, request, send_from_directory
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

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def send_telegram_photo(chat_id, photo_url, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "Markdown"
    requests.post(url, json=payload)

def get_lang(code):
    return "ru" if code in ["ru", "uk"] else "en"

def extract_lead_data_from_text(text):
    data = {}
    text_l = text.lower().strip()

    match = re.search(r"(меня зовут|я|это|имя)\s+([а-яa-z\-]+)", text_l)
    if match:
        data["name"] = match.group(2).capitalize()

    if len(text.split()) == 1 and text.isalpha() and len(text) <= 15:
        data["name"] = text.capitalize()

    if any(w in text_l for w in ["whatsapp", "ватсап", "вотсап", "ват сап", "вот сап"]):
        data["platform"] = "WhatsApp"
    elif "telegram" in text_l or "телеграм" in text_l:
        data["platform"] = "Telegram"
    elif "zoom" in text_l or "зум" in text_l:
        data["platform"] = "Zoom"
    elif "google meet" in text_l or "гугл мит" in text_l:
        data["platform"] = "Google Meet"

    phone_match = re.search(r"\+?\d{7,}", text)
    if phone_match:
        data["phone"] = phone_match.group(0)

    if any(w in text_l for w in ["завтра", "сегодня", "утром", "вечером", "понедельник", "вторник", "в", ":"]):
        data["datetime"] = text.strip()

    return data

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    lang_code = message.get("from", {}).get("language_code", "en")
    lang = get_lang(lang_code)

    if not chat_id:
        return "no chat_id", 400

    if text == "/start":
        sessions[user_id] = []
        welcome = "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?"
        send_telegram_message(chat_id, welcome)
        return "ok"

    if user_id not in lead_data and any(w in text.lower() for w in call_request_triggers):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей, чтобы согласовать звонок с менеджером.\n\n👋 Как к вам можно обращаться?")
        return "ok"

    if user_id in lead_data:
        lead = lead_data.get(user_id, {})

        if not lead.get("name") and "platform" in lead:
            send_telegram_message(chat_id, "👋 Как к вам можно обращаться?")
            return "ok"
        elif not lead.get("platform"):
            send_telegram_message(chat_id, "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet")
            lead.update(extract_lead_data_from_text(text))
            lead_data[user_id] = lead
            return "ok"
        elif lead.get("platform", "").lower() == "whatsapp" and not lead.get("phone"):
            send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:")
            lead.update(extract_lead_data_from_text(text))
            lead_data[user_id] = lead
            return "ok"
        elif not lead.get("datetime"):
            send_telegram_message(chat_id, "🗓 Когда удобно созвониться?")
            lead.update(extract_lead_data_from_text(text))
            lead_data[user_id] = lead
            return "ok"

        # финальное поле
        lead.update(extract_lead_data_from_text(text))
        lead_data[user_id] = lead

        required_fields = ["name", "platform", "datetime"]
        if lead.get("platform") == "WhatsApp":
            required_fields.append("phone")

        if all(lead.get(field) for field in required_fields):
            datetime_raw = lead.get("datetime", "").strip()
            parts = datetime_raw.split()
            date_part = parts[0] if len(parts) >= 1 else ""
            time_part = parts[1] if len(parts) >= 2 else ""

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                sheet.append_row([
                    now_str,
                    lead.get("name", ""),
                    f"@{username}",
                    lead.get("phone", ""),
                    date_part,
                    time_part,
                    lead.get("platform", ""),
                    "",
                    lang_code
                ])
                send_telegram_message(chat_id, "✅ Все данные получены и записаны. Менеджер скоро свяжется с вами.")
            except Exception as e:
                print("Ошибка записи:", e)
                send_telegram_message(chat_id, "⚠️ Не удалось сохранить заявку. Попробуйте ещё раз.")
            lead_data.pop(user_id, None)
            return "ok"

    return "ok"

@app.route("/AVALON/<path:filename>")
def serve_avalon_static(filename):
    return send_from_directory("AVALON", filename)

@app.route("/")
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
