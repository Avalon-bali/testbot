import os
import json
import random
from datetime import datetime
from flask import Flask, request
import openai
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# ======================
# КОНФИГУРАЦИЯ (БЕЗОПАСНОЕ ХРАНЕНИЕ)
# ======================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # 1. Добавьте в Environment Variables на Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEETS_KEY = os.getenv("GOOGLE_SHEETS_KEY")  # ID вашей таблицы
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")  # 2. Вставьте сюда весь JSON из google-credentials.json

# Проверка обязательных переменных
if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, GOOGLE_CREDS_JSON]):
    raise ValueError("Не заданы обязательные переменные окружения!")

openai.api_key = OPENAI_API_KEY

# ======================
# ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ
# ======================
sessions = {}
lead_progress = {}

# Настройка Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_CREDS_JSON), scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(GOOGLE_SHEETS_KEY).sheet1

# ======================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ======================
def load_documents():
    """Загружает текстовые документы из папки docs"""
    folder = "docs"
    context_parts = []
    for filename in os.listdir(folder):
        if filename.endswith(".txt") and filename != "system_prompt.txt":
            with open(os.path.join(folder, filename), "r", encoding="utf-8") as f:
                context_parts.append(f.read()[:3000])
    return "\n\n".join(context_parts)

def load_system_prompt():
    """Загружает системный промпт"""
    with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
        return f.read()

documents_context = load_documents()
system_prompt = load_system_prompt()

def get_welcome_text(language):
    """Возвращает приветственное сообщение на нужном языке"""
    welcome_texts = {
        "ru": (
            "👋 _Добро пожаловать!_\n\n"
            "**Я — AI ассистент отдела продаж Avalon.**\n\n"
            "Помогу вам узнать о наших проектах 🏡 **OM / BUDDHA / TAO** и инвестициях на острове мечты 🏝️.\n\n"
            "Спрашивайте!"
        ),
        "uk": (
            "👋 _Ласкаво просимо!_\n\n"
            "**Я — AI асистент відділу продажів Avalon.**\n\n"
            "Допоможу вам дізнатися про наші проекти 🏡 **OM / BUDDHA / TAO** та інвестиції на острові мрії 🏝️.\n\n"
            "Питайте що завгодно!"
        ),
        "id": (
            "👋 _Selamat datang!_\n\n"
            "**Saya adalah asisten AI dari tim penjualan Avalon.**\n\n"
            "Saya akan membantu Anda tentang proyek kami 🏡 **OM / BUDDHA / TAO** dan investasi di Bali 🏝️.\n\n"
            "Silakan tanya apa saja!"
        )
    }
    return welcome_texts.get(language[:2], 
        "👋 _Welcome!_\n\n"
        "**I am the AI sales assistant of Avalon.**\n\n"
        "I can help you with our projects 🏡 **OM / BUDDHA / TAO** and investments on the dream island 🏝️.\n\n"
        "Feel free to ask me anything!"
    )

def send_telegram_message(chat_id, text):
    """Отправляет сообщение в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")

# ... (остальные функции остаются без изменений, как в вашем исходном коде)

# ======================
# ВЕБХУКИ
# ======================
@app.route(f"/webhook", methods=["POST"])
def telegram_webhook():
    """Обработчик входящих сообщений от Telegram"""
    # Добавим проверку секретного токена для безопасности
    if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != os.getenv("WEBHOOK_SECRET"):
        return "Unauthorized", 401

    data = request.get_json()
    if not data:
        return "Bad Request", 400

    # ... (остальная логика обработки сообщений без изменений)

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает. FSM и лиды активны."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
