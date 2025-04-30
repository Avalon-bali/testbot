from flask import Flask, request
import openai
import requests
import os
import time
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

# Состояния
sessions = {}
fsm_state = {}
lead_data = {}
fsm_timestamps = {}

FSM_TIMEOUT = 600  # 10 минут

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

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_lang(language_code):
    return "ru" if language_code in ["ru", "uk"] else "en"

def fsm_timeout_check(user_id):
    if user_id in fsm_timestamps:
        if time.time() - fsm_timestamps[user_id] > FSM_TIMEOUT:
            fsm_state.pop(user_id, None)
            lead_data.pop(user_id, None)
            fsm_timestamps.pop(user_id, None)
            print(f"⏳ FSM session for {user_id} timed out.")
            return True
    return False

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "").strip()
    username = message.get("from", {}).get("username", "")
    language_code = message.get("from", {}).get("language_code", "en")
    lang = get_lang(language_code)

    if not chat_id:
        return "no chat_id", 400

    if fsm_timeout_check(user_id):
        send_telegram_message(chat_id, "⏳ Время ожидания истекло. Начнём сначала." if lang == "ru" else "⏳ Timeout. Let's start again.")
        return "ok"

    if user_id in fsm_state:
        fsm_timestamps[user_id] = time.time()
        step = fsm_state[user_id]
        answer = text.strip()

        # Проверка: пользователь задал новый вопрос
        if any(answer.lower().startswith(q) for q in ["где", "что", "почему", "как", "когда", "do", "what", "where", "who", "how", "why"]):
            print(f"🧩 {user_id} задал вопрос вне FSM: «{answer}». Прерываем FSM.")
            fsm_state.pop(user_id, None)
            lead_data.pop(user_id, None)
            fsm_timestamps.pop(user_id, None)
        else:
            try:
                if step == "ask_name":
                    lead_data[user_id]["name"] = answer
                    fsm_state[user_id] = "ask_platform"
                    msg = "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet" if lang == "ru" else "📱 Choose platform: WhatsApp / Telegram / Zoom / Google Meet"
                    send_telegram_message(chat_id, msg)
                    return "ok"

                elif step == "ask_platform":
                    platform = answer.lower()
                    lead_data[user_id]["platform"] = platform
                    if "whatsapp" in platform or "ватсап" in platform or "вотсап" in platform:
                        fsm_state[user_id] = "ask_phone"
                        msg = "📞 Напишите номер WhatsApp:" if lang == "ru" else "📞 Please enter your WhatsApp number:"
                        send_telegram_message(chat_id, msg)
                    elif any(p in platform for p in ["telegram", "zoom", "google"]):
                        fsm_state[user_id] = "ask_datetime"
                        msg = "🗓 Когда удобно созвониться?" if lang == "ru" else "🗓 When would you like to have a call?"
                        send_telegram_message(chat_id, msg)
                    else:
                        send_telegram_message(chat_id, "❓ Пожалуйста, выберите один из указанных вариантов." if lang == "ru" else "❓ Please choose one of the listed options.")
                    return "ok"

                elif step == "ask_phone":
                    if not any(c.isdigit() for c in answer):
                        send_telegram_message(chat_id, "❌ Неверный номер. Попробуйте ещё раз." if lang == "ru" else "❌ Invalid number. Please try again.")
                        return "ok"
                    lead_data[user_id]["phone"] = answer
                    fsm_state[user_id] = "ask_datetime"
                    msg = "🗓 Когда удобно созвониться?" if lang == "ru" else "🗓 When would you like to have a call?"
                    send_telegram_message(chat_id, msg)
                    return "ok"

                elif step == "ask_datetime":
                    lead_data[user_id]["datetime"] = answer
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    sheet.append_row([
                        now_str,
                        lead_data[user_id].get("name", ""),
                        f"@{username}",
                        lead_data[user_id].get("phone", ""),
                        answer.split()[0] if len(answer.split()) > 0 else "",
                        answer.split()[1] if len(answer.split()) > 1 else "",
                        lead_data[user_id].get("platform", ""),
                        "",
                        language_code
                    ])
                    msg = "✅ Все данные записаны. Менеджер скоро свяжется с вами." if lang == "ru" else "✅ Your details are recorded. Our manager will contact you soon."
                    send_telegram_message(chat_id, msg)
                    fsm_state.pop(user_id, None)
                    lead_data.pop(user_id, None)
                    fsm_timestamps.pop(user_id, None)
                    return "ok"

            except Exception as e:
                print(f"❌ FSM error for {user_id}:", e)
                send_telegram_message(chat_id, "❌ Произошла ошибка. Попробуйте позже." if lang == "ru" else "❌ An error occurred. Please try again later.")
                return "ok"

    if text == "/start":
        sessions[user_id] = []
        msg = "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?" \
            if lang == "ru" else \
            "👋 Hello! I’m the AI assistant of Avalon.\nI can help you with our projects, investment options, and life in Bali. How can I assist you?"
        send_telegram_message(chat_id, msg)
        return "ok"

    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}\n\nIf the user requests a call or consultation, return only: [CALL_REQUEST]."},
        *history[-6:],  # последние 6 сообщений
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ OpenAI error:", e)
        reply = "⚠️ Ошибка OpenAI." if lang == "ru" else "⚠️ OpenAI error."

    if reply == "[CALL_REQUEST]":
        fsm_state[user_id] = "ask_name"
        lead_data[user_id] = {}
        fsm_timestamps[user_id] = time.time()
        msg = "👋 Как к вам можно обращаться?" if lang == "ru" else "👋 May I have your name?"
        send_telegram_message(chat_id, msg)
        return "ok"

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon AI бот работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
