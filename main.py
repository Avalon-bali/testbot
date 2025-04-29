from flask import Flask, request
import openai
import requests
import os
import time
import re

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

sessions = {}
last_message_time = {}

# Экранирование для MarkdownV2
def escape_markdown_v2(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!<>"
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", text)

# Жирное выделение важных частей
def bold_important_parts(text):
    important_phrases = [
        "организовать консультацию",
        "согласовать личный звонок",
        "индивидуальная консультация",
        "созвониться для обсуждения деталей",
        "обсудить ваши вопросы на звонке",
        "помочь выбрать проект на созвоне"
    ]
    for phrase in important_phrases:
        text = text.replace(phrase, f"**{phrase}**")
    text = escape_markdown_v2(text)
    text = text.replace("**", "\\*\\*")
    return text

# Загрузка базы знаний
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

# Отправка сообщения в Telegram
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    formatted_text = bold_important_parts(text)
    payload = {
        "chat_id": chat_id,
        "text": formatted_text,
        "parse_mode": "MarkdownV2"
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("Ошибка отправки текста:", response.text)

# Отправка фото в Telegram
def send_telegram_photo(chat_id, photo_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo_file:
        files = {"photo": photo_file}
        data = {"chat_id": chat_id}
        if caption:
            caption = escape_markdown_v2(caption)
            data["caption"] = caption
            data["parse_mode"] = "MarkdownV2"
        response = requests.post(url, data=data, files=files)
    if response.status_code != 200:
        print("Ошибка отправки фото:", response.text)

# Поиск логотипа
def find_logo():
    folder = "docs/AVALON"
    if os.path.exists(folder):
        files = [f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        if files:
            return os.path.join(folder, files[0])
    return None

# Webhook для Telegram
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    now = time.time()
    last_time = last_message_time.get(user_id, 0)
    if now - last_time < 1:
        return "rate limit", 429
    last_message_time[user_id] = now

    sessions.setdefault(user_id, [])
    history = sessions[user_id][-6:]

    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}
    ] + history + [
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка OpenAI: {e}")
        reply = "Произошла техническая ошибка. Попробуйте позже."

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)

    keywords = ["авалон", "avalon", "ом", "buddha", "budda", "tao"]
    if any(k in text.lower() for k in keywords):
        logo = find_logo()
        if logo:
            send_telegram_photo(chat_id, logo, caption="Avalon — инвестиции на Бали 🌴")

    return "ok"

# Проверка работоспособности
@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает стабильно."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
