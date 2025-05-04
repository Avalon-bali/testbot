import random
from flask import Flask, request
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

cancel_phrases = ["отмена", "не хочу", "передумал", "не надо", "не интересно", "потом", "сейчас не нужно"]
platforms = ["whatsapp", "telegram", "zoom", "google meet"]

final_reply_options = [
    "✅ Все данные записаны. Менеджер скоро свяжется с вами. Если есть вопросы — я на связи.",
    "✅ Все данные сохранены. Наш менеджер скоро свяжется с вами. А пока я могу ответить на любые ваши вопросы.",
    "✅ Заявка передана менеджеру. Он скоро с вами свяжется. Если хотите — можем обсудить ещё что-то прямо здесь."
]

def normalize_platform(text):
    t = text.lower().strip()
    if t in ["whatsapp", "вотсап", "ватсап"]:
        return "whatsapp"
    if t in ["telegram", "телеграм", "телега", "тг"]:
        return "telegram"
    if t in ["zoom", "зум"]:
        return "zoom"
    if t in ["google meet", "мит", "митап", "гугл мит", "googlemeet"]:
        return "google meet"
    return ""

def is_confirmative_reply(text):
    confirm = ["да", "давайте", "ок", "хорошо", "можно", "вечером", "утром", "сегодня", "завтра", "в любой день", "в любое время", "давай", "погнали"]
    if any(p in text.lower() for p in confirm):
        return True
    if normalize_platform(text) in platforms:
        return True
    return False

def extract_datetime_candidate(text):
    candidates = ["вечером", "утром", "сегодня", "завтра", "в любой день", "в любое время", "после обеда", "до обеда"]
    return text if any(p in text.lower() for p in candidates) else None

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

def detect_project(messages):
    all_text = " ".join([m["content"].lower() for m in messages[-6:]])
    if "om" in all_text:
        return "OM"
    if "buddha" in all_text:
        return "BUDDHA"
    if "tao" in all_text:
        return "TAO"
    return ""

documents_context = load_documents()

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    raw_lang = message.get("from", {}).get("language_code", "en")[:2]
    lang_code = "ru" if raw_lang == "ru" else "ua" if raw_lang == "uk" else "en"
    lower_text = text.lower()
    system_prompt = load_system_prompt(lang_code)

    if not chat_id:
        return "no chat_id", 400

    if lower_text == "/start":
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

    if user_id in lead_data and lower_text in cancel_phrases:
        lead_data.pop(user_id, None)
        send_telegram_message(chat_id, "👌 Хорошо, если передумаете — просто напишите.")
        return "ok"

    # FSM логика (сбор данных) — остаётся как в предыдущей версии...

    # GPT обработка
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

def send_telegram_message(chat_id, text, photo_path=None):
    if photo_path and os.path.exists(photo_path):
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            files = {'photo': photo}
            data = {
                'chat_id': chat_id,
                'caption': text,
                'parse_mode': 'Markdown'
            }
            requests.post(url_photo, files=files, data=data)
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload)

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot with full image support and dynamic ending."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
