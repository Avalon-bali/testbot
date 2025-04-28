
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

def deep_escape_markdown(text):
    # Экранировать символы для MarkdownV2
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    text = re.sub(r"([{0}])".format(re.escape(escape_chars)), r"\\\1", text)
    return text

def format_markdown(text):
    # Вставить жирные участки перед экранированием
    important_words = [
        "Высокая доходность", 
        "Три уникальных проекта", 
        "Партнёрство с Ribas Hotels Group", 
        "Современные стандарты", 
        "Прозрачность и ответственность"
    ]
    for word in important_words:
        text = text.replace(word, f"**{word}**")
    # Потом экранировать весь текст
    text = deep_escape_markdown(text)
    # И ещё раз экранировать двойные звездочки правильно
    text = text.replace("**", "\\*\\*")
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
            data["caption"] = deep_escape_markdown(caption)
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

    sessions.setdefault(user_id, [])
    history = sessions[user_id][-2:] + [{"role": "user", "content": text}]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Ты AI-ассистент компании Avalon. Отвечай дружелюбно, подробно, структурировано."}] + history
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка OpenAI: {e}")
        reply = "Произошла техническая ошибка\. Попробуйте позже\."

    sessions[user_id] = (sessions[user_id] + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]
    formatted = format_markdown(reply)
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
