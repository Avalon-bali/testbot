from flask import Flask, request, send_from_directory
import openai
import requests
import os
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

system_prompt = """
Ты — AI Assistant отдела продаж компании Avalon, специализирующейся на инвестиционной недвижимости на Бали.
Ты можешь отвечать только на темы: Avalon, проекты OM, BUDDHA, TAO, инвестиции на Бали, переезд, доходность, этапы строительства.
Если вопрос не по теме — мягко откажись и скажи, что можешь отвечать только по проектам Avalon.
Всегда отвечай как опытный менеджер, но честно указывай, что ты — AI Assistant.
"""

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def detect_lang(text):
    lower = text.lower()
    if any(word in lower for word in ["hello", "can you", "speak english"]):
        return "en"
    elif any(word in lower for word in ["привет", "здравствуйте", "расскажи"]):
        return "ru"
    elif any(word in lower for word in ["привіт", "українською"]):
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
    return {
        "ru": "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?",
        "uk": "👋 Вітаю! Я — AI асистент компанії Avalon.\nЗ радістю допоможу з питаннями про проєкти Avalon та інвестиції на Балі!",
        "en": "👋 Hello! I'm the AI assistant of Avalon.\nI can help you with our projects, investments, and life in Bali. How can I assist you?"
    }.get(lang, "en")

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
        send_telegram_message(chat_id, get_welcome_message(lang))
        return "ok"

    # GPT reply only
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": system_prompt},
        *history[-6:],
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ GPT error:", e)
        reply = "⚠️ Произошла ошибка. Попробуйте позже."

    if any(kw in text.lower() for kw in ["ом", "om", "buddha", "тау", "авалон", "проект", "бали"]):
        sessions[user_id] = history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        send_telegram_message(chat_id, reply)
    else:
        warning = {
            "ru": "Извините, я могу отвечать только на вопросы, связанные с проектами Avalon и инвестициями на Бали.",
            "uk": "Вибачте, я можу відповідати лише на запитання щодо Avalon та інвестицій на Балі.",
            "en": "Sorry, I can only answer questions related to Avalon and Bali real estate investments."
        }
        send_telegram_message(chat_id, warning.get(lang, warning["en"]))

    return "ok"

@app.route("/")
def home():
    return "Avalon AI bot running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
