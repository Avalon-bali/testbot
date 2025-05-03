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

lang_overrides = {}

def detect_lang(text):
    lower = text.lower()
    if any(word in lower for word in ["hello", "can you", "speak english", "english?", "what is", "tell about", "project"]):
        return "en"
    elif any(word in lower for word in ["привет", "здравствуйте", "что", "расскажи", "объясни", "расскажите"]):
        return "ru"
    elif any(word in lower for word in ["привіт", "доброго", "розкажи", "поясни", "українською"]):
        return "uk"
    return None

def get_lang(code, user_id, text):
    override = detect_lang(text)
    if override:
        lang_overrides[user_id] = override
        return override
    if user_id in lang_overrides:
        return lang_overrides[user_id]
    if code == "ru":
        return "ru"
    elif code == "uk":
        return "uk"
    else:
        return "en"

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    lang_code = message.get("from", {}).get("language_code", "en")
    lang = get_lang(lang_code, user_id, text)

    if not chat_id:
        return "no chat_id", 400

    if text == "/start":
        sessions[user_id] = []
        if lang == "ru":
            welcome = "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?"
        elif lang == "uk":
            welcome = "👋 Вітаю! Я — AI асистент відділу продажів Avalon.\nЗ радістю допоможу з питаннями про наші проєкти, інвестиції та життя на Балі. Чим можу бути корисним?"
        else:
            welcome = "👋 Hello! I'm the AI assistant of Avalon.\nI can help you with our projects, investment options, and life in Bali. How can I assist you?"

        send_telegram_message(chat_id, welcome)
        return "ok"

    # здесь идёт остальная логика обработки заявки, GPT, lead_data и т.д.

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
