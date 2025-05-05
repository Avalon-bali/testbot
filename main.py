# все импорты и config — без изменений
sessions = {}
lead_data = {}
session_flags = {}

# ... send_telegram_message(), load_documents(), load_system_prompt(), detect_project() ...

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

    print(f"📥 Сообщение от {user_id}: {text}")

    if not chat_id:
        return "no chat_id", 400

    if text.lower() == "/start":
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

    # Avalon: показать картинку один раз
    if ("avalon" in lower_text or "авалон" in lower_text) and not session_flags.get(user_id, {}).get("avalon_photo_sent"):
        photo_path = "AVALON/avalon-photos/Avalon-reviews-and-ratings-1.jpg"
        send_telegram_message(chat_id, "Avalon | Development & Investment", photo_path=photo_path)
        session_flags.setdefault(user_id, {})["avalon_photo_sent"] = True

    # FSM: сбор данных
    if user_id in lead_data:
        lead = lead_data[user_id]
        if "name" not in lead:
            lead["name"] = text
            send_telegram_message(chat_id, "📱 Укажите платформу для звонка: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif "platform" not in lead:
            lead["platform"] = text
            send_telegram_message(chat_id, "🗓 Когда вам удобно созвониться?")
            return "ok"
        elif "datetime" not in lead:
            lead["datetime"] = text
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            wa_url = f"https://wa.me/{lead.get('phone')}" if "whatsapp" in lead.get("platform", "").lower() else ""
            try:
                sheet.append_row([
                    now,
                    lead.get("name"),
                    f"@{username}",
                    lead.get("platform"),
                    wa_url,
                    lead.get("datetime"),
                    "",  # проект
                    lang_code
                ])
                print("✅ Лид добавлен в таблицу:", lead.get("name"))
            except Exception as e:
                print("⚠️ Ошибка при добавлении в таблицу:", e)
            send_telegram_message(chat_id, "✅ Все данные записаны. Менеджер скоро свяжется с вами. Если есть вопросы — я на связи.")
            lead_data.pop(user_id, None)
            return "ok"

    # FSM запуск
    last_gpt_msg = next((m["content"] for m in reversed(sessions.get(user_id, [])) if m["role"] == "assistant"), "")
    if (
        user_id not in lead_data and
        "звонок" in last_gpt_msg.lower() and
        lower_text in ["да", "давайте", "ок", "можно", "вечером", "утром"]
    ):
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "✅ Отлично! Давайте уточним пару деталей. Как к вам можно обращаться?")
        return "ok"

    # GPT ответ
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

@app.route("/", methods=["GET"])
def home():
    return "Avalon bot with FSM and Avalon image — OK"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
