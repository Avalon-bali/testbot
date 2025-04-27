from flask import Flask, request
import openai
import requests
import os
import random
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

def get_welcome_text(language):
    if language and language.startswith("ru"):
        return (
            "👋 _Добро пожаловать!_\n\n"
            "**Я — AI ассистент отдела продаж Avalon.**\n\n"
            "Помогу вам узнать о наших проектах 🏡 **OM / BUDDHA / TAO** и инвестициях на острове мечты 🏝️.\n\n"
            "Спрашивайте!"
        )
    elif language and language.startswith("uk"):
        return (
            "👋 _Ласкаво просимо!_\n\n"
            "**Я — AI асистент відділу продажів Avalon.**\n\n"
            "Допоможу вам дізнатися про наші проекти 🏡 **OM / BUDDHA / TAO** та інвестиції на острові мрії 🏝️.\n\n"
            "Питайте що завгодно!"
        )
    elif language and language.startswith("id"):
        return (
            "👋 _Selamat datang!_\n\n"
            "**Saya adalah asisten AI dari tim penjualan Avalon.**\n\n"
            "Saya akan membantu Anda tentang proyek kami 🏡 **OM / BUDDHA / TAO** dan investasi di Bali 🏝️.\n\n"
            "Silakan tanya apa saja!"
        )
    else:
        return (
            "👋 _Welcome!_\n\n"
            "**I am the AI sales assistant of Avalon.**\n\n"
            "I can help you with our projects 🏡 **OM / BUDDHA / TAO** and investments on the dream island 🏝️.\n\n"
            "Feel free to ask me anything!"
        )

def find_logo_or_random(folder):
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
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def send_telegram_local_photo(chat_id, photo_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo_file:
        files = {"photo": photo_file}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "Markdown"
        requests.post(url, data=data, files=files)

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
    language = message.get("from", {}).get("language_code", "en")
    first_name = message.get("from", {}).get("first_name", "")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    if text.strip().lower() in ["/start"]:
        sessions[user_id] = []
        lead_progress.pop(user_id, None)

        welcome_text = get_welcome_text(language)
        send_telegram_message(chat_id, welcome_text)

        avalon_folder = "docs/AVALON"
        if os.path.exists(avalon_folder):
            logo_or_random = find_logo_or_random(avalon_folder)
            if logo_or_random:
                send_telegram_local_photo(chat_id, logo_or_random, caption="Avalon — инвестиции на Бали 🌴")

        return "ok"

    # (Остальная твоя логика здесь без изменений — обработка лида и ответов через GPT)

    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает. FSM и лиды активны."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
