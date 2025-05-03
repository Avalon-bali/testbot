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
lang_overrides = {}

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

def detect_lang(text):
    lower = text.lower()
    if any(word in lower for word in ["hello", "can you", "speak english", "english?", "what is", "tell about", "project"]):
        return "en"
    elif any(word in lower for word in ["привет", "здравствуйте", "что", "расскажи", "объясни", "расскажите"]):
        return "ru"
    elif any(word in lower for word in ["привіт", "доброго", "розкажи", "поясни", "українською"]):
        return "uk"
    return None

def resolve_lang(lang_code, user_id, text):
    override = detect_lang(text)
    if override:
        lang_overrides[user_id] = override
        return override
    if user_id in lang_overrides:
        return lang_overrides[user_id]
    return lang_code if lang_code in ["ru", "uk"] else "en"

def get_welcome_message(lang):
    if lang == "ru":
        return "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?"
    elif lang == "uk":
        return "👋 Вітаю! Я — AI асистент відділу продажів Avalon.\nЗ радістю допоможу з питаннями про наші проєкти, інвестиції та життя на Балі. Чим можу бути корисним?"
    else:
        return "👋 Hello! I'm the AI assistant of Avalon.\nI can help you with our projects, investment options, and life in Bali. How can I assist you?"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    lang_code = message.get("from", {}).get("language_code", "en")
    lang = resolve_lang(lang_code, user_id, text)

    if not chat_id:
        return "no chat_id", 400

    if text == "/start":
        sessions[user_id] = []
        welcome = get_welcome_message(lang)
        print(f"[LOG] Приветствие для {user_id} на языке {lang}")
        send_telegram_message(chat_id, welcome)
        return "ok"

    if user_id not in lead_data and any(w in text.lower() for w in call_request_triggers):
        lead_data[user_id] = {}
        msg = {
            "ru": "👋 Как к вам можно обращаться?",
            "uk": "👋 Як до вас можна звертатися?",
            "en": "👋 May I have your name?"
        }
        send_telegram_message(chat_id, msg.get(lang, msg["en"]))
        return "ok"

    if user_id in lead_data:
        lead = lead_data.get(user_id, {})
        if "name" not in lead:
            lead["name"] = text
            msg = {
                "ru": "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet",
                "uk": "📱 Вкажіть платформу: WhatsApp / Telegram / Zoom / Google Meet",
                "en": "📱 Choose platform: WhatsApp / Telegram / Zoom / Google Meet"
            }
            send_telegram_message(chat_id, msg.get(lang, msg["en"]))
        elif "platform" not in lead:
            lead["platform"] = text
            if text.lower() == "whatsapp":
                msg = {
                    "ru": "📞 Напишите номер WhatsApp:",
                    "uk": "📞 Напишіть номер WhatsApp:",
                    "en": "📞 Please enter your WhatsApp number:"
                }
                send_telegram_message(chat_id, msg.get(lang, msg["en"]))
            else:
                msg = {
                    "ru": "🗓 Когда удобно созвониться?",
                    "uk": "🗓 Коли зручно зв'язатися?",
                    "en": "🗓 When would you like to have a call?"
                }
                send_telegram_message(chat_id, msg.get(lang, msg["en"]))
        elif lead.get("platform", "").lower() == "whatsapp" and "phone" not in lead:
            lead["phone"] = text
            msg = {
                "ru": "🗓 Когда удобно созвониться?",
                "uk": "🗓 Коли зручно зв'язатися?",
                "en": "🗓 When would you like to have a call?"
            }
            send_telegram_message(chat_id, msg.get(lang, msg["en"]))
        else:
            lead["datetime"] = text
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            sheet.append_row([
                now_str,
                lead.get("name", ""),
                f"@{username}",
                lead.get("phone", ""),
                text.split()[0] if len(text.split()) > 0 else "",
                text.split()[1] if len(text.split()) > 1 else "",
                lead.get("platform", ""),
                "",
                lang_code
            ])
            msg = {
                "ru": "✅ Все данные записаны. Менеджер свяжется с вами.",
                "uk": "✅ Дані збережено. Менеджер зв'яжеться з вами.",
                "en": "✅ Details saved. Manager will contact you soon."
            }
            send_telegram_message(chat_id, msg.get(lang, msg["en"]))
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
