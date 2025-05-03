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

system_prompt_template = {
    "ru": (
        "Ты — AI Assistant отдела продаж компании Avalon. "
        "Ты можешь отвечать только на темы: проекты Avalon, OM, BUDDHA, TAO, инвестиции, недвижимость на Бали. "
        "Если вопрос не по теме — мягко откажись. Отвечай как опытный менеджер. "
        "📥 Ты всегда используешь информацию из текстов в `docs/*.txt`. "
        "Обращай внимание на ссылки в этих текстах. Если пользователь спрашивает про PDF, презентацию или ссылку — вставь её, если она есть."
    ),
    "uk": (
        "Ти — AI асистент відділу продажів компанії Avalon. "
        "Ти можеш відповідати лише на теми: проєкти Avalon, OM, BUDDHA, TAO, інвестиції, нерухомість на Балі. "
        "Якщо питання не по темі — ввічливо відмов. Відповідай як досвідчений менеджер. "
        "📥 Завжди використовуй інформацію з текстів у `docs/*.txt`. "
        "Звертай увагу на посилання в цих текстах. Якщо користувач питає про PDF, презентацію чи посилання — встав його, якщо воно є."
    ),
    "en": (
        "You are the AI Assistant of the Avalon sales team. "
        "You may only answer questions related to: Avalon projects, OM, BUDDHA, TAO, investments, real estate in Bali. "
        "If the question is off-topic — politely decline. Answer like a professional sales manager. "
        "📥 Always use content from the `docs/*.txt` files. "
        "Pay attention to links in those texts. If the user asks for a PDF, brochure or link — include it if available."
    )
}

lang = lang_code if lang_code in ["ru", "uk"] else "en"
system_prompt = system_prompt_template.get(lang, system_prompt_template["en"])
Ты — AI Assistant отдела продаж компании Avalon. Ты можешь отвечать только на темы: проекты Avalon, OM, BUDDHA, TAO, инвестиции, недвижимость на Бали. Если вопрос не по теме — мягко откажись. Отвечай как опытный менеджер.
"""

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def classify_user_input(prompt_text, user_text):
    try:
        result = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты помощник. Ответь только 'ANSWER' если пользователь отвечает на вопрос, или 'QUESTION' если задаёт встречный вопрос."},
                {"role": "user", "content": f"Вопрос от бота: {prompt_text}\nОтвет пользователя: {user_text}"}
            ]
        )
        return result.choices[0].message.content.strip().upper()
    except:
        return "ANSWER"

def extract_lead_data(text):
    data = {}
    text = text.strip()
    if len(text.split()) == 1 and text.isalpha():
        data["name"] = text.capitalize()
    if any(w in text.lower() for w in ["whatsapp", "ватсап", "вотсап"]):
        data["platform"] = "WhatsApp"
    elif "telegram" in text.lower():
        data["platform"] = "Telegram"
    elif "zoom" in text.lower():
        data["platform"] = "Zoom"
    if re.search(r"\+?\d{7,}", text):
        data["phone"] = text
    if any(w in text.lower() for w in ["сегодня", "завтра", "вечером", "утром"]):
        data["datetime"] = text
    return data

def get_step(lead):
    if "name" not in lead:
        return "name", "👋 Как к вам можно обращаться?"
    if "platform" not in lead:
        return "platform", "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet"
    if lead.get("platform", "").lower() == "whatsapp" and "phone" not in lead:
        return "phone", "📞 Напишите номер WhatsApp:"
    if "datetime" not in lead:
        return "datetime", "🗓 Когда удобно созвониться?"
    return None, None

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")

    if text == "/start":
        send_telegram_message(chat_id, "👋 Здравствуйте! Я — AI ассистент компании Avalon. Чем могу быть полезен?")
        return "ok"

    if user_id not in lead_data and any(w in text.lower() for w in call_request_triggers):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\n👋 Как к вам можно обращаться?")
        return "ok"

    if user_id in lead_data:
        lead = lead_data.get(user_id, {})
        step, prompt = get_step(lead)
        if step:
            label = classify_user_input(prompt, text)
            if label == "QUESTION":
                send_telegram_message(chat_id, "❓ Сейчас уточним детали звонка. После этого я с радостью отвечу на другие вопросы!")
                return "ok"
            lead.update(extract_lead_data(text))
            lead_data[user_id] = lead
            step, prompt = get_step(lead)
            if not step:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                dt = lead.get("datetime", "").split()
                date_part = dt[0] if len(dt) > 0 else ""
                time_part = dt[1] if len(dt) > 1 else ""
                datetime_raw = lead.get("datetime", "").strip().lower()
date_part = ""
time_part = ""

for word in datetime_raw.split():
    if word in ["сегодня", "завтра", "понедельник", "вторник", "среда", "четверг", "пятница"]:
        date_part = word
    elif word in ["утром", "вечером", "днем", "вечер", "утро", "после обеда"]:
        time_part = word

wa_url = f"https://wa.me/{lead.get('phone')}" if lead.get("platform") == "WhatsApp" and lead.get("phone") else ""
project = ""
text_lower = text.lower()
if any(w in text_lower for w in ["ом", "om"]):
    project = "OM"
elif any(w in text_lower for w in ["buddha", "будда"]):
    project = "BUDDHA"
elif any(w in text_lower for w in ["tao", "тао", "тау"]):
    project = "TAO"  # Пока не заполняется

now = datetime.now().strftime("%Y-%m-%d %H:%M")
t = text.lower()

platform = lead.get("platform", "")
wa_url = f"https://wa.me/{lead.get('phone')}" if platform == "WhatsApp" and lead.get("phone") else ""
datetime_value = lead.get("datetime", "")

project = ""
if "ом" in t or "om" in t:
    project = "OM"
elif "будда" in t or "buddha" in t:
    project = "BUDDHA"
elif "тао" in t or "tao" in t or "тау" in t:
    project = "TAO"

sheet.append_row([
    now,
    lead.get("name", ""),
    f"@{username}",
    platform,
    wa_url,
    datetime_value,
    project,
    "ru"
])
                send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
                lead_data.pop(user_id, None)
                return "ok"
            send_telegram_message(chat_id, prompt)
            return "ok"

    # GPT fallback if no form is active
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}

{documents_context}"},
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
        reply = "⚠️ Ошибка. Попробуйте позже."

    sessions[user_id] = history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/")
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
