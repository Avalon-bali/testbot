from flask import Flask, request
import openai
import requests
import os
import re
import gspread
import logging
import time
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from gspread.exceptions import APIError

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)

logging.basicConfig(level=logging.INFO)

def connect_to_sheet(sheet_key, retries=5, delay=10):
    for attempt in range(1, retries + 1):
        try:
            sheet = gsheet.open_by_key(sheet_key).sheet1
            logging.info(f"Connected to sheet on attempt {attempt}")
            return sheet
        except APIError as e:
            logging.error(f"Attempt {attempt}/{retries} - Error connecting to Google Sheets: {e}")
            if attempt < retries:
                time.sleep(delay)
            else:
                logging.critical("Failed to connect to Google Sheets after multiple attempts")
                raise e

sheet = connect_to_sheet("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4")

sessions = {}
lead_data = {}

call_request_triggers = [
    "созвон", "поговорить", "менеджер", "хочу звонок", "можно позвонить",
    "звонок", "давайте созвонимся", "обсудить", "свяжитесь со мной"
]

system_prompt = (
    "You are the AI Assistant of the Avalon sales team. "
    "You may only answer questions related to: Avalon projects, OM, BUDDHA, TAO, investments, real estate in Bali. "
    "If the question is off-topic - politely decline. Answer like a professional sales manager. "
    "Always use content from the docs/*.txt files. "
    "Pay attention to links in those texts. If the user asks for a PDF, brochure or link - include it if available."
)

def escape_markdown(text):
    escape_chars = r'_*[\]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def send_telegram_message(chat_id, text, photo_path=None):
    escaped_text = escape_markdown(text)
    if photo_path:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            payload = {
                'chat_id': chat_id,
                'caption': escaped_text,
                'parse_mode': 'MarkdownV2'
            }
            files = {'photo': photo}
            requests.post(url, data=payload, files=files)
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": escaped_text,
            "parse_mode": "MarkdownV2"
        }
        requests.post(url, json=payload)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip().lower()
    username = message.get("from", {}).get("username", "")

    if text == "/start":
        send_telegram_message(chat_id, "👋 Здравствуйте! Я — AI ассистент компании Avalon. Чем могу быть полезен?")
        return "ok"

    if user_id not in lead_data and any(w in text for w in call_request_triggers):
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
            wa_url = f"https://wa.me/{lead.get('phone')}" if lead.get("platform") == "WhatsApp" else ""
            sheet.append_row([
                now, lead.get("name"), f"@{username}", lead.get("platform"),
                wa_url, lead.get("datetime"), "", "ru"
            ])
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
            lead_data.pop(user_id, None)
            return "ok"

    # Отправка фото Avalon
    if "avalon" in text:
        photo_path = "testbot/AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        caption = "*Avalon* – современная недвижимость на Бали."
        send_telegram_message(chat_id, caption, photo_path=photo_path)
        return "ok"

    # GPT fallback
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]
    response = openai.chat.completions.create(model="gpt-4o", messages=messages)
    reply = response.choices[0].message.content.strip()

    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/")
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
