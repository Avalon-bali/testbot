
from flask import Flask, request
import openai
import requests
import os
import random
import gspread
import json
import time
from datetime import datetime
from google.oauth2.service_account import Credentials
import re

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

sessions = {}
last_message_time = {}
user_last_seen = {}
lead_progress = {}

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("/etc/secrets/google-credentials.json", scopes=scope)
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

def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\", text)

def get_welcome_text(language):
    lang = (language or "").lower()
    if lang.startswith("ru"):
        return ("👋 _Добро пожаловать!_\n\n"
                "**Я — AI ассистент отдела продаж Avalon.**\n\n"
                "Помогу вам узнать о наших проектах 🏡 **OM / BUDDHA / TAO** и инвестициях на острове мечты 🏝️.\n\n"
                "Спрашивайте!")
    if lang.startswith("uk"):
        return ("👋 _Ласкаво просимо!_\n\n"
                "**Я — AI асистент відділу продажів Avalon.**\n\n"
                "Допоможу вам дізнатися про наші проекти 🏡 **OM / BUDDHA / TAO** та інвестиції на острові мрії 🏝️.\n\n"
                "Питайте що завгодно!")
    if lang.startswith("id"):
        return ("👋 _Selamat datang!_\n\n"
                "**Saya adalah asisten AI dari tim penjualan Avalon.**\n\n"
                "Saya akan membantu Anda tentang proyek kami 🏡 **OM / BUDDHA / TAO** dan investasi di Bali 🏝️.\n\n"
                "Silakan tanya apa saja!")
    return ("👋 _Welcome!_\n\n"
            "**I am the AI sales assistant of Avalon.**\n\n"
            "I can help you with our projects 🏡 **OM / BUDDHA / TAO** and investments on the dream island 🏝️.\n\n"
            "Feel free to ask me anything!")

def find_logo_or_random():
    candidates = ["/mnt/disk/docs/AVALON", "docs/AVALON"]
    for folder in candidates:
        if os.path.exists(folder):
            files = []
            logos = []
            for f in os.listdir(folder):
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    files.append(f)
                    if "logo" in f.lower():
                        logos.append(f)
            if logos:
                return os.path.join(folder, random.choice(logos))
            if files:
                return os.path.join(folder, random.choice(files))
    return None

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": escape_markdown(text), "parse_mode": "MarkdownV2"}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("Ошибка отправки в Telegram:", response.text)

def send_telegram_local_photo(chat_id, photo_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo_file:
        files = {"photo": photo_file}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = escape_markdown(caption)
            data["parse_mode"] = "MarkdownV2"
        response = requests.post(url, data=data, files=files)
    if response.status_code != 200:
        print("Ошибка отправки фото:", response.text)

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    username = message.get("from", {}).get("username", "")
    language = message.get("from", {}).get("language_code", "en")
    first_name = message.get("from", {}).get("first_name", "")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    if text and len(text) > 1000:
        text = text[:1000]

    now = time.time()
    last_time = last_message_time.get(user_id, 0)
    if now - last_time < 2:
        return "rate limit", 429
    last_message_time[user_id] = now
    user_last_seen[user_id] = now

    if text.strip() == "/start":
        welcome_text = get_welcome_text(language)
        send_telegram_message(chat_id, welcome_text)

        logo_or_random = find_logo_or_random()
        if logo_or_random:
            send_telegram_local_photo(chat_id, logo_or_random, caption="Avalon — инвестиции на Бали 🌴")

        return "ok"

    history = sessions.get(user_id, [])
    messages = [{"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}] + history[-2:] + [{"role": "user", "content": text}]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка OpenAI: {e}")
        reply = "Произошла техническая ошибка\. Пожалуйста, попробуйте позже\."

    sessions[user_id] = (history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]

    send_telegram_message(chat_id, reply)
    cleanup_inactive_users()
    return "ok"

def cleanup_inactive_users():
    now = time.time()
    twenty_days = 20 * 24 * 60 * 60
    to_delete = [user_id for user_id, last_seen in user_last_seen.items() if now - last_seen > twenty_days]
    for user_id in to_delete:
        sessions.pop(user_id, None)
        last_message_time.pop(user_id, None)
        user_last_seen.pop(user_id, None)
        lead_progress.pop(user_id, None)
    if to_delete:
        print(f"Очищено неактивных пользователей: {len(to_delete)}")

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
