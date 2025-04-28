
from flask import Flask, request, abort
import openai
import requests
import os
import random
import gspread
import json
import time
from datetime import datetime
from google.oauth2.service_account import Credentials

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

sessions = {}
last_message_time = {}
user_last_seen = {}
lead_progress = {}

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file("/etc/secrets/google-credentials.json", scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key("1rJSFvD9r3yTxnl2Y9LFhRosAbr7mYF7dYtgmg9VJip4").sheet1

# IP-адреса Telegram (глобальный список может меняться, тут базовый пример)
TELEGRAM_IPS = ["149.154.160.0/20", "91.108.4.0/22"]

def load_documents():
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read()[:3000])
    return "\n\n".join(context_parts)

def load_system_prompt():
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

def escape_markdown(text):
    escape_chars = "_*[]()~`>#+-=|{}.!"  # символы которые нужно экранировать
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": escape_markdown(text), "parse_mode": "MarkdownV2"}
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("Ошибка отправки в Telegram:", response.text)

def ip_in_telegram_ranges(ip):
    import ipaddress
    for cidr in TELEGRAM_IPS:
        if ipaddress.ip_address(ip) in ipaddress.ip_network(cidr):
            return True
    return False

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    ip = request.remote_addr
    if not ip_in_telegram_ranges(ip):
        print(f"Отклонено соединение с IP: {ip}")
        abort(403)

    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    username = message.get("from", {}).get("username", "")
    language = message.get("from", {}).get("language_code", "en")
    first_name = message.get("from", {}).get("first_name", "")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    if text and len(text) > 1000:
        text = text[:1000]

    now = time.time()
    last_time = last_message_time.get(user_id, 0)
    if now - last_time < 2:
        return "rate limit", 429
    last_message_time[user_id] = now
    user_last_seen[user_id] = now

    history = sessions.get(user_id, [])
    messages = [{"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}] + history[-2:] + [{"role": "user", "content": text}]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ошибка OpenAI: {e}")
        reply = "Произошла техническая ошибка\. Пожалуйста, попробуйте позже\."

    sessions[user_id] = (history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}])[-6:]

    send_telegram_message(chat_id, reply)
    cleanup_inactive_users()
    return "ok"

def cleanup_inactive_users():
    now = time.time()
    twenty_days = 20 * 24 * 60 * 60
    to_delete = [user_id for user_id, last_seen in user_last_seen.items() if now - last_seen > twenty_days]
    for user_id in to_delete:
        sessions.pop(user_id, None)
        last_message_time.pop(user_id, None)
        user_last_seen.pop(user_id, None)
        lead_progress.pop(user_id, None)
    if to_delete:
        print(f"Очищено неактивных пользователей: {len(to_delete)}")

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
