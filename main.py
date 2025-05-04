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

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read())
    return "\n\n".join(context_parts)

def load_system_prompt():
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    lang_code = message.get("from", {}).get("language_code", "ru")

    if not chat_id:
        return "no chat_id", 400

    if text.lower() == "/start":
        sessions[user_id] = []
        lead_data.pop(user_id, None)
        send_telegram_message(chat_id, "👋 Привет! Я — AI ассистент Avalon.\nСпросите про OM, BUDDHA, TAO или инвестиции на Бали.")
        return "ok"

    # FSM в процессе
    if user_id in lead_data:
        lead = lead_data[user_id]
        lower_text = text.lower()

        # Если это вопрос — просим завершить сначала форму
        if "?" in text or lower_text.startswith(("где", "что", "как", "почем", "есть ли", "можно ли")):
            send_telegram_message(chat_id, "📌 Давайте сначала завершим детали звонка, а потом я с радостью помогу вам с остальными вопросами.")
            return "ok"

        if "name" not in lead:
            lead["name"] = text
            send_telegram_message(chat_id, "📱 Укажите платформу для звонка: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"

        elif "platform" not in lead:
            if lower_text not in ["whatsapp", "telegram", "zoom", "google meet"]:
                send_telegram_message(chat_id, "❗ Пожалуйста, выберите одну из предложенных платформ: WhatsApp / Telegram / Zoom / Google Meet.")
                return "ok"
            lead["platform"] = lower_text
            if lower_text == "whatsapp":
                send_telegram_message(chat_id, "📞 Пожалуйста, напишите номер WhatsApp:")
            else:
                send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"

        elif lead.get("platform") == "whatsapp" and "phone" not in lead:
            digits = re.sub(r"\D", "", text)
            if len(digits) < 6:
                send_telegram_message(chat_id, "❗ Пожалуйста, укажите корректный номер телефона.")
                return "ok"
            lead["phone"] = digits
            send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"

        elif "datetime" not in lead:
            if len(text) < 3 or "?" in text:
                send_telegram_message(chat_id, "❗ Пожалуйста, уточните, в какое время вам будет удобно созвониться.")
                return "ok"
            lead["datetime"] = text
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            wa_url = f"https://wa.me/{lead.get('phone')}" if lead.get("platform") == "whatsapp" else ""
            sheet.append_row([
                now,
                lead.get("name"),
                f"@{username}",
                lead.get("platform"),
                wa_url,
                lead.get("datetime"),
                "",  # проект
                lang_code
            ])
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
            lead_data.pop(user_id, None)
            return "ok"

        # на всякий случай
        send_telegram_message(chat_id, "📌 Давайте сначала завершим детали звонка.")
        return "ok"

    # Умный запуск FSM
    invite_keywords = ["созвон", "звонок", "организовать звонок", "позвонить", "связаться"]
    confirm_phrases = ["да", "давайте", "ок", "хорошо", "можно", "вечером", "утром", "после обеда", "давай", "погнали"]
    last_gpt_msgs = [m["content"].lower() for m in sessions.get(user_id, []) if m["role"] == "assistant"][-3:]

    if user_id not in lead_data and any(k in m for m in last_gpt_msgs for k in invite_keywords) and any(p in text.lower() for p in confirm_phrases):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей.\nКак к вам можно обращаться?")
        return "ok"

    # Фото Avalon (если встречается в тексте)
    if "avalon" in text.lower():
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        send_telegram_message(chat_id, "Avalon — современная недвижимость на Бали.", photo_path=photo_path)
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

def send_telegram_message(chat_id, text, photo_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

    if photo_path and os.path.exists(photo_path):
        url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, 'rb') as photo:
            requests.post(url_photo, files={'photo': photo}, data={'chat_id': chat_id})

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot with full FSM validation is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
