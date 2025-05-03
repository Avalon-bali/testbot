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

# загрузка контекста из docs
def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read())
    return "\n\n".join(context_parts)

documents_context = load_documents()

system_prompt = (
    "Ты — AI Assistant отдела продаж компании Avalon. "
    "Ты можешь отвечать только на темы: проекты Avalon, OM, BUDDHA, TAO, инвестиции, недвижимость на Бали. "
    "Если вопрос не по теме — мягко откажись. Отвечай как опытный менеджер. "
    "📥 Ты всегда используешь информацию из текстов в `docs/*.txt`. "
    "Обращай внимание на ссылки в этих текстах. Если пользователь спрашивает про PDF, презентацию или ссылку — вставь её, если она есть."
)

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
    t = text.lower().strip()

    # Имя (одно слово)
    if len(text.split()) == 1 and text.isalpha():
        data["name"] = text.capitalize()

    # Платформы
    if any(w in t for w in ["whatsapp", "ватсап", "вотсап", "ват сап", "вацап", "вотцап"]):
        data["platform"] = "WhatsApp"
    elif any(w in t for w in ["telegram", "телеграм", "телега", "тг", "tg"]):
        data["platform"] = "Telegram"
    elif any(w in t for w in ["zoom", "зум", "зуум", "зумм"]):
        data["platform"] = "Zoom"
    elif any(w in t for w in ["google meet", "гугл мит", "гуглміт", "мит", "meet"]):
        data["platform"] = "Google Meet"

    if re.search(r"\+?\d{7,}", t):
        data["phone"] = text

    if any(w in t for w in ["сегодня", "завтра", "вечером", "утром", "понедельник", "вторник", ":"]):
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
        sessions[user_id] = []
        send_telegram_message(chat_id, "👋 Здравствуйте! Я — AI ассистент компании Avalon. Чем могу быть полезен?")
        return "ok"

    if user_id not in lead_data and any(w in text.lower() for w in ["созвон", "менеджер", "звонок", "встретиться"]):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\n👋 Как к вам можно обращаться?")
        return "ok"

    if user_id in lead_data:
        lead = lead_data.get(user_id, {})
        step, prompt = get_step(lead)
        if step:
            label = classify_user_input(prompt, text)
            if label == "QUESTION":
                send_telegram_message(chat_id, "❓ Сейчас уточним детали звонка. После этого с радостью отвечу!")
                return "ok"
            lead.update(extract_lead_data(text))
            lead_data[user_id] = lead
            step, prompt = get_step(lead)
            if not step:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                dt = lead.get("datetime", "").split()
                date_part = dt[0] if len(dt) > 0 else ""
                time_part = dt[1] if len(dt) > 1 else ""
                try:
                    sheet.append_row([
                        now,
                        lead.get("name", ""),
                        f"@{username}",
                        lead.get("phone", ""),
                        date_part,
                        time_part,
                        lead.get("platform", ""),
                        "",
                        "ru"
                    ])
                except Exception as e:
                    print("❌ Ошибка Google Sheet:", e)
                send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
                lead_data.pop(user_id, None)
                return "ok"
            send_telegram_message(chat_id, prompt)
            return "ok"

    # GPT fallback
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
    except Exception as e:
        print("GPT error:", e)
        reply = "⚠️ Ошибка. Попробуйте позже."

    sessions[user_id] = history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/")
def home():
    return "Avalon AI работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
