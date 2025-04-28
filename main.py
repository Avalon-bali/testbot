
from flask import Flask, request
import openai
import requests
import os
import time
import re

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

sessions = {}
last_message_time = {}

def escape_markdown(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    text = re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)
    return text

def format_answer(text):
    keywords = ["Высокая доходность", "Три уникальных проекта", "Партнёрство с Ribas Hotels Group", "Современные стандарты", "Прозрачность и ответственность"]
    for word in keywords:
        text = text.replace(word, f"**{word}**")
    text = escape_markdown(text)
    return text

def find_logo():
    folder = "docs/AVALON"
    if os.path.exists(folder):
        files = [f for f in os.listdir(folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
        if files:
            return os.path.join(folder, files[0])
    return None

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("Ошибка отправки текста:", response.text)

def send_telegram_photo(chat_id, photo_path, caption=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo_file:
        files = {"photo": photo_file}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = escape_markdown(caption)
            data["parse_mode"] = "MarkdownV2"
        response = requests.post(url, data=data, files=files)
    if response.status_code != 200:
        print("Ошибка отправки фото:", response.text)

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

    if text.strip() == "/start":
        send_telegram_message(chat_id, "👋 _Добро пожаловать!_\n\n**Я — AI ассистент компании Avalon.**")
        logo = find_logo()
        if logo:
            send_telegram_photo(chat_id, logo, caption="Avalon — инвестиции на Бали 🌴")
        return "ok"

    sessions.setdefault(user_id, [])
    history = sessions[user_id][-2:] + [{"role": "user", "content": text}]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Ты представляешь компанию Avalon. Пиши строго и по делу."}] + history
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка OpenAI: {e}")
        reply = "Произошла техническая ошибка\. Попробуйте позже\."

    sessions[user_id] = (sessions[user_id] + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]
    formatted = format_answer(reply)
    send_telegram_message(chat_id, formatted)

    keywords = ["авалон", "avalon", "ом", "budda", "buddha", "tao"]
    if any(k in text.lower() for k in keywords):
        logo = find_logo()
        if logo:
            send_telegram_photo(chat_id, logo, caption="Avalon — инвестиции на Бали 🌴")

    return "ok"

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает."

if __name__ == "__main__":
    webhook_url = f"https://testbot-1e8k.onrender.com/{TELEGRAM_TOKEN}"
    set_webhook_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={webhook_url}"

    try:
        response = requests.get(set_webhook_url)
        if response.status_code == 200:
            print("✅ Webhook установлен автоматически.")
        else:
            print(f"❌ Ошибка установки Webhook: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка при установке Webhook: {e}")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
