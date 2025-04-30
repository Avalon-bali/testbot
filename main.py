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

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("/etc/secrets/google-credentials.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

sessions = {}
fsm_state = {}
lead_data = {}
fsm_timestamps = {}

FSM_TIMEOUT = 600

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

def send_telegram_photo(chat_id, photo_url, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_url}
    if caption:
        payload["caption"] = caption
        payload["parse_mode"] = "Markdown"
    requests.post(url, json=payload)

def get_lang(code):
    return "ru" if code in ["ru", "uk"] else "en"

def fsm_timeout_check(user_id):
    if user_id in fsm_timestamps:
        if time.time() - fsm_timestamps[user_id] > FSM_TIMEOUT:
            fsm_state.pop(user_id, None)
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
    lang_code = message.get("from", {}).get("language_code", "en")
    lang = get_lang(lang_code)

    if not chat_id:
        return "no chat_id", 400

    if fsm_timeout_check(user_id):
        send_telegram_message(chat_id, "⏳ Время ожидания истекло. Начнём сначала." if lang == "ru" else "⏳ Timeout. Let's start again.")
        return "ok"

    if user_id in fsm_state:
        fsm_timestamps[user_id] = time.time()
        step = fsm_state[user_id]
        answer = text

        if any(answer.lower().startswith(q) for q in ["где", "что", "почему", "как", "когда", "do", "what", "where", "who", "how", "why"]):
            print(f"🧩 FSM interrupted by question from {user_id}: {answer}")
            fsm_state.pop(user_id, None)
            fsm_timestamps.pop(user_id, None)
        else:
            try:
                if step == "ask_name":
                    lead_data[user_id] = lead_data.get(user_id, {})
                    lead_data[user_id]["name"] = answer
                    fsm_state[user_id] = "ask_platform"
                    send_telegram_message(chat_id, "📱 Укажите платформу: WhatsApp / Telegram / Zoom / Google Meet" if lang == "ru" else "📱 Choose platform: WhatsApp / Telegram / Zoom / Google Meet")
                    return "ok"

                elif step == "ask_platform":
                    lead_data[user_id]["platform"] = answer
                    if "whatsapp" in answer.lower():
                        fsm_state[user_id] = "ask_phone"
                        send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:" if lang == "ru" else "📞 Please enter your WhatsApp number:")
                    else:
                        fsm_state[user_id] = "ask_datetime"
                        send_telegram_message(chat_id, "🗓 Когда удобно созвониться?" if lang == "ru" else "🗓 When would you like to have a call?")
                    return "ok"

                elif step == "ask_phone":
                    if not any(c.isdigit() for c in answer):
                        send_telegram_message(chat_id, "❌ Неверный номер. Попробуйте ещё раз." if lang == "ru" else "❌ Invalid number. Please try again.")
                        return "ok"
                    lead_data[user_id]["phone"] = answer
                    fsm_state[user_id] = "ask_datetime"
                    send_telegram_message(chat_id, "🗓 Когда удобно созвониться?" if lang == "ru" else "🗓 When would you like to have a call?")
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
                        lang_code
                    ])
                    send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер свяжется с вами." if lang == "ru" else "✅ Details saved. Manager will contact you soon.")
                    fsm_state.pop(user_id, None)
                    lead_data.pop(user_id, None)
                    fsm_timestamps.pop(user_id, None)
                    return "ok"
            except Exception as e:
                print(f"❌ FSM error: {e}")
                send_telegram_message(chat_id, "⚠️ Ошибка. Попробуйте позже." if lang == "ru" else "⚠️ Error. Please try again later.")
                return "ok"

    if text == "/start":
        sessions[user_id] = []
        welcome = "👋 Здравствуйте! Я — AI ассистент компании Avalon.\nРад помочь вам по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?" \
            if lang == "ru" else \
            "👋 Hello! I’m the AI assistant of Avalon.\nI can help you with our projects, investment options, and life in Bali. How can I assist you?"
        send_telegram_message(chat_id, welcome)
        return "ok"

    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}\n\nIf the user requests a call or consultation, return only: [CALL_REQUEST]."},
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
        print("❌ OpenAI error:", e)
        reply = "⚠️ Ошибка OpenAI." if lang == "ru" else "⚠️ OpenAI error."

    if reply == "[CALL_REQUEST]":
        fsm_state[user_id] = "ask_name"
        lead_data[user_id] = {}
        fsm_timestamps[user_id] = time.time()
        send_telegram_message(chat_id, "👋 Как к вам можно обращаться?" if lang == "ru" else "👋 May I have your name?")
        return "ok"

    trigger = text.lower()
    if "ом" in trigger or "om" in trigger:
        send_telegram_photo(chat_id, "https://github.com/Avalon-bali/testbot/blob/main/AVALON/avalon-photos/OM.jpg?raw=true", "🏡 *OM Club House* — премиум-апартаменты в Чангу.")
    elif "тао" in trigger or "tao" in trigger:
        send_telegram_photo(chat_id, "https://github.com/Avalon-bali/testbot/blob/main/AVALON/avalon-photos/TAO.jpg?raw=true", "🌿 *TAO* — бутик-апартаменты в Бераве.")
    elif "будда" in trigger or "buddha" in trigger:
        send_telegram_photo(chat_id, "https://github.com/Avalon-bali/testbot/blob/main/AVALON/avalon-photos/BUDDHA.jpg?raw=true", "🧘 *BUDDHA Club House* — инвестиционный апарт-отель в Чангу.")
    elif "авалон" in trigger or "avalon" in trigger:
        send_telegram_photo(chat_id, "https://github.com/Avalon-bali/testbot/blob/main/AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg?raw=true", "🏢 *AVALON* — девелоперская компания с украинскими корнями на Бали.")

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
