import random
import os
import re
import time
import csv
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
session_flags = {}

def normalize_platform(text):
    t = text.lower().strip()
    if t in ["whatsapp", "вотсап", "ватсап"]:
        return "whatsapp"
    if t in ["telegram", "телеграм", "тг"]:
        return "telegram"
    if t in ["zoom", "зум"]:
        return "zoom"
    if t in ["google meet", "гугл мит", "мит", "митап", "googlemeet"]:
        return "google meet"
    return t

def send_typing_action(chat_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendChatAction"
    requests.post(url, json={"chat_id": chat_id, "action": "typing"})

def send_telegram_message(chat_id, text, photo_path=None):
    send_typing_action(chat_id)
    time.sleep(1)

    if photo_path:
        if os.path.exists(photo_path):
            url_photo = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            with open(photo_path, 'rb') as photo:
                files = {'photo': photo}
                data = {
                    'chat_id': chat_id,
                    'caption': text if text else None,
                    'parse_mode': 'Markdown'
                }
                if not text:
                    del data["caption"]
                requests.post(url_photo, files=files, data=data)
        else:
            send_telegram_message(chat_id, text + "\n\n⚠️ Картинка не найдена.")
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        requests.post(url, json=payload)

def send_image_once(user_id, chat_id, key, filename, caption):
    if not session_flags.get(user_id, {}).get(f"{key}_photo_sent"):
        send_telegram_message(chat_id, caption, photo_path=f"AVALON/avalon-photos/{filename}")
        session_flags.setdefault(user_id, {})[f"{key}_photo_sent"] = True

def log_dialog(user_id):
    now = datetime.now()
    with open("dialogs.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([user_id, now.strftime("%Y-%m-%d %H:%M:%S")])

def log_lead(user_id):
    now = datetime.now()
    with open("leads.csv", "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([user_id, now.strftime("%Y-%m-%d %H:%M:%S")])

def count_by_period(file_path):
    today = datetime.now().date()
    this_month = today.replace(day=1)
    total, today_count, month_count = 0, 0, 0
    if not os.path.exists(file_path):
        return (0, 0, 0)
    with open(file_path, "r") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            try:
                ts = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            total += 1
            if ts.date() == today:
                today_count += 1
            if ts.date() >= this_month:
                month_count += 1
    return today_count, month_count, total

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
    username = message.get("from", {}).get("username", "")
    raw_lang = message.get("from", {}).get("language_code", "en")[:2]
    lang_code = "ru" if raw_lang == "ru" else "ua" if raw_lang == "uk" else "en"
    lower_text = text.lower()
    system_prompt = load_system_prompt(lang_code)

    if not chat_id:
        return "no chat_id", 400

    if lower_text == "/start":
        log_dialog(user_id)
        greetings = {
            "ru": "👋 Здравствуйте! Я — AI ассистент компании Avalon. С радостью помогу по вопросам наших проектов, инвестиций и жизни на Бали. Чем могу быть полезен?",
            "ua": "👋 Вітаю! Я — AI-асистент компанії Avalon. Із задоволенням допоможу з проєктами, інвестиціями та життям на Балі. Чим можу бути корисним?",
            "en": "👋 Hello! I'm the AI assistant of Avalon. Happy to help with our projects, investments, or relocating to Bali. How can I assist you today?"
        }
        greeting = greetings.get(lang_code, greetings["en"])
        sessions[user_id] = []
        lead_data.pop(user_id, None)
        session_flags.pop(user_id, None)
        send_telegram_message(chat_id, greeting)
        return "ok"

    if lower_text == "/admin stats":
        d_today, d_month, d_total = count_by_period("dialogs.csv")
        l_today, l_month, l_total = count_by_period("leads.csv")
        stats = (
            f"📊 Статистика:\n\n"
            f"*Диалогов:*\n- сегодня: {d_today}\n- за месяц: {d_month}\n- всего: {d_total}\n\n"
            f"*Лидов:*\n- сегодня: {l_today}\n- за месяц: {l_month}\n- всего: {l_total}"
        )
        send_telegram_message(chat_id, stats)
        return "ok"

    # Картинки
    if any(w in lower_text for w in ["avalon", "авалон"]):
        send_image_once(user_id, chat_id, "avalon", "Avalon-reviews-and-ratings-1.jpg", "Avalon | Development & Investment. Подробнее ниже 👇")
    if any(w in lower_text for w in ["om", "ом"]):
        send_image_once(user_id, chat_id, "om", "om.jpg", "OM Club House. Подробнее ниже 👇")
    if any(w in lower_text for w in ["buddha", "будда", "буда"]):
        send_image_once(user_id, chat_id, "buddha", "buddha.jpg", "BUDDHA Club House. Сейчас расскажу 👇")
    if any(w in lower_text for w in ["tao", "тао"]):
        send_image_once(user_id, chat_id, "tao", "tao.jpg", "TAO Club House. Ниже вся информация 👇")

    # FSM
    if user_id in lead_data:
        if "?" in text or lower_text.startswith(("где", "что", "как", "почему", "почем", "есть ли", "адрес", "можно ли", "зачем", "когда")):
            send_telegram_message(chat_id, "📌 Давайте сначала завершим детали звонка. После этого с радостью вернусь к вашему вопросу.")
            return "ok"
        lead = lead_data[user_id]
        if "name" not in lead:
            lead["name"] = text
            send_telegram_message(chat_id, "📱 Укажите платформу для звонка: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif "platform" not in lead:
            lead["platform"] = normalize_platform(text)
            if lead["platform"] == "whatsapp":
                send_telegram_message(chat_id, "📞 Пожалуйста, напишите ваш номер WhatsApp")
            else:
                send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"
        elif lead.get("platform") == "whatsapp" and "phone" not in lead:
            lead["phone"] = text
            send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"
        elif "datetime" not in lead:
            lead["datetime"] = text
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
                    "",
                    lang_code
                ])
                log_lead(user_id)
            except Exception as e:
                print("⚠️ Ошибка при записи в таблицу:", e)
            send_telegram_message(chat_id, "✅ Спасибо за информацию! Наш менеджер свяжется с вами по WhatsApp вечером. Если у вас появятся дополнительные вопросы, не стесняйтесь обращаться. Прекрасного вам дня!")
            lead_data.pop(user_id, None)
            return "ok"

    trigger_words = ["звонок", "созвон", "консультац", "менеджер", "встрече", "перезвонить"]
    confirm_phrases = [
        "да", "давай", "давайте", "ок", "оке", "окей", "можно",
        "вечером", "утром", "конечно", "записывай", "вперед",
        "согласен", "поехали", "погнали", "хорошо", "приступим"
    ]
    last_gpt_msg = next((m["content"] for m in reversed(sessions.get(user_id, [])) if m["role"] == "assistant"), "")
    if (
        user_id not in lead_data and
        any(w in last_gpt_msg.lower() for w in trigger_words) and
        any(p in lower_text for p in confirm_phrases)
    ):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей. Как к вам можно обращаться?")
        return "ok"

    # GPT
    send_typing_action(chat_id)
    time.sleep(1.2)
    history = sessions.get(user_id, [])
    messages = [
        {"role": "system", "content": f"{load_system_prompt(lang_code)}\n\n{documents_context}"},
        *history[-6:],
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(model="gpt-4o", messages=messages)
        reply = response.choices[0].message.content.strip()
        reply = re.sub(r"\*\*(.*?)\*\*", r"\1", reply)
    except Exception as e:
        reply = f"Произошла ошибка при обращении к OpenAI:\n\n{e}"

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot ✅ full features"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
