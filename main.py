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

    if user_id in lead_data:
        lead = lead_data[user_id]

        if "?" in text or lower_text.startswith(("где", "что", "как", "почему", "почем", "можно", "есть ли")):
            send_telegram_message(chat_id, "📌 Давайте сначала завершим детали звонка, и потом я с радостью помогу вам с остальными вопросами.")
            return "ok"

        if "name" not in lead:
            lead["name"] = text
            if not lead.get("platform"):
                send_telegram_message(chat_id, "📱 Укажите платформу для звонка: WhatsApp / Telegram / Zoom / Google Meet")
            elif not lead.get("datetime"):
                send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            else:
                send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
                lead_data.pop(user_id, None)
            return "ok"

        if not lead.get("platform"):
            norm = normalize_platform(lower_text)
            if norm not in platforms:
                send_telegram_message(chat_id, "❗ Пожалуйста, выберите одну из предложенных платформ: WhatsApp / Telegram / Zoom / Google Meet.")
                return "ok"
            lead["platform"] = norm
            if not lead.get("datetime"):
                send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            else:
                send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
                lead_data.pop(user_id, None)
            return "ok"

        if lead.get("platform") == "whatsapp" and not lead.get("phone"):
            digits = re.sub(r"\D", "", text)
            if len(digits) < 6:
                send_telegram_message(chat_id, "❗ Пожалуйста, укажите корректный номер телефона.")
                return "ok"
            lead["phone"] = digits
            send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"

        if not lead.get("datetime"):
            if len(text) < 3 or "?" in text:
                send_telegram_message(chat_id, "❗ Пожалуйста, укажите удобное время для звонка.")
                return "ok"
            lead["datetime"] = text
            history = sessions.get(user_id, [])
            project = detect_project(history)
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            wa_url = f"https://wa.me/{lead.get('phone')}" if lead.get("platform") == "whatsapp" else ""
            try:
                sheet.append_row([
                    now,
                    lead.get("name"),
                    f"@{username}",
                    lead.get("platform"),
                    wa_url,
                    lead.get("datetime"),
                    project,
                    lang_code
                ])
                print("✅ Лид успешно добавлен в таблицу:", lead.get("name"))
            except Exception as e:
                print("⚠️ Ошибка при добавлении в таблицу:", e)
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами.")
            lead_data.pop(user_id, None)
            return "ok"

        send_telegram_message(chat_id, "📌 Давайте сначала завершим детали звонка.")
        return "ok"

    # FSM запуск
    invite_keywords = ["созвон", "звонок", "организовать звонок", "позвонить", "связаться"]
    last_gpt_msg = next((m["content"] for m in reversed(sessions.get(user_id, [])) if m["role"] == "assistant"), "")
    last_gpt_msg_lower = last_gpt_msg.lower()

    if (
        user_id not in lead_data and
        last_gpt_msg.strip().endswith("?") and
        any(k in last_gpt_msg_lower for k in invite_keywords) and
        is_confirmative_reply(lower_text)
    ):
        platform = normalize_platform(lower_text)
        datetime_value = extract_datetime_candidate(lower_text)
        lead_data[user_id] = {}
        if platform in platforms:
            lead_data[user_id]["platform"] = platform
        if datetime_value:
            lead_data[user_id]["datetime"] = datetime_value
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей. Как к вам можно обращаться?")
        return "ok"

    if "avalon" in lower_text:
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        send_telegram_message(chat_id, "Avalon — современная недвижимость на Бали.", photo_path=photo_path)
        return "ok"

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
    return "Avalon bot ready."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
