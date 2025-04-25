from flask import Flask, request
import openai
import requests
import os

app = Flask(__name__)

# Жёстко заданный Telegram токен
TELEGRAM_TOKEN = "7942085031:AAERWupDOXiDvqA1LE-EWTE8JM9n3Qa0v44"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Память по пользователю
sessions = {}

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

# Точный маршрут для Telegram Webhook
@app.route("/7942085031:AAERWupDOXiDvqA1LE-EWTE8JM9n3Qa0v44", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    print("🔔 Входящее сообщение от Telegram:", data)

    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return "no chat_id", 400

    if text.strip() == "/start":
        welcome = "👋 Привет! Я — AI ассистент Avalon.\nСпросите про OM, BUDDHA, TAO или про инвестиции на Бали."
        sessions[user_id] = []
        send_telegram_message(chat_id, welcome)
        return "ok"

    history = sessions.get(user_id, [])

    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{documents_context}"}
    ] + history[-6:] + [
        {"role": "user", "content": text}
    ]

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        reply = f"Произошла ошибка при обращении к OpenAI:\n\n{e}"
        print("❌ Ошибка GPT:", e)

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)
    return "ok"

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
    "chat_id": chat_id,
    "text": text,
    "parse_mode": "Markdown"
}
    r = requests.post(url, json=payload)
    print("📤 Ответ отправлен:", r.status_code, r.text)

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT bot is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
