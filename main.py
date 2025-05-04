import random
import os
import re
import requests
import openai
import gspread
from flask import Flask, request
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

def send_telegram_message(chat_id, text, photo_path=None):
    if photo_path:
        if os.path.exists(photo_path):
            print("📸 Отправляю изображение:", photo_path)
            url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': chat_id,
                    'caption': text,
                    'parse_mode': 'Markdown'
                }
                response = requests.post(url_photo, files=files, data=data)
                print("📤 Ответ Telegram (фото):", response.status_code)
        else:
            print("❌ Файл не найден:", photo_path)
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": text + "\n\n⚠️ Картинка не найдена.",
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload)
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload)
        print("📤 Ответ Telegram (текст):", response.status_code)

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read())
    return "\n\n".join(context_parts)

def load_system_prompt(lang_code):
    try:
        with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
            full_text = f.read()
            match = re.search(rf"### {lang_code}\n(.*?)\n###", full_text, re.DOTALL)
            return match.group(1).strip() if match else "Ты — AI ассистент Avalon."
    except:
        return "Ты — AI ассистент Avalon."

documents_context = load_documents()

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    raw_lang = message.get("from", {}).get("language_code", "en")[:2]
    lang_code = "ru" if raw_lang == "ru" else "ua" if raw_lang == "uk" else "en"
    system_prompt = load_system_prompt(lang_code)

    print(f"📥 Сообщение от {user_id}: {text}")

    if not chat_id:
        return "no chat_id", 400

    if text.lower() == "/start":
        greetings = {
            "ru": "👋 Здравствуйте! Я — AI ассистент компании Avalon. С радостью помогу по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?",
            "ua": "👋 Вітаю! Я — AI-асистент компанії Avalon. Із задоволенням допоможу з проєктами, інвестиціями та життям на Балі. Чим можу бути корисним?",
            "en": "👋 Hello! I'm the AI assistant of Avalon. Happy to help with our projects, investments, or relocating to Bali. How can I assist you today?"
        }
        greeting = greetings.get(lang_code, greetings["en"])
        sessions[user_id] = []
        lead_data.pop(user_id, None)
        send_telegram_message(chat_id, greeting)
        return "ok"

    # 📸 Отдельная реакция на "авалон"
    if "avalon" in text.lower():
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        reply_text = (
            "Avalon — современная недвижимость на Бали.\n\n"
            "Один из самых известных девелоперов острова. Мы реализуем проекты OM, BUDDHA и TAO с фокусом на инвестиции, архитектуру и топовые локации.\n\n"
            "Готов рассказать больше!"
        )
        send_telegram_message(chat_id, reply_text, photo_path=photo_path)
        return "ok"

    # GPT логика
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"},
        *history[-6:],
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
        reply = re.sub(r"\*\*(.*?)\*\*", r"\1", reply)
    except Exception as e:
        reply = f"Произошла ошибка при обращении к OpenAI:\n\n{e}"
        print("❌ GPT Error:", e)

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot live — with photo + prompt + return OK."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
