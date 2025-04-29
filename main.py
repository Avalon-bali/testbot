@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def telegram_webhook():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")
    language_code = message.get("from", {}).get("language_code", "en")
    username = message.get("from", {}).get("username", "")

    if not chat_id:
        return "no chat_id", 400

    now = time.time()
    last_time = last_message_time.get(user_id, 0)
    if now - last_time < 1:
        return "rate limit", 429
    last_message_time[user_id] = now

    # Обработка команд для админа
    if text.strip() == "/leads":
        if user_id != ADMIN_ID:
            send_telegram_message(chat_id, "⛔ Эта команда доступна только администратору.")
            return "ok"
        try:
            rows = sheet.get_all_values()
            last = rows[-3:] if len(rows) >= 3 else rows[-len(rows):]
            messages = []
            for r in last:
                messages.append(
                    f"*Имя:* {r[1]}\n"
                    f"*Telegram:* {r[2]}\n"
                    f"*WhatsApp:* {r[3]}\n"
                    f"*Дата звонка:* {r[4]} {r[5]}\n"
                    f"*Платформа:* {r[6]}\n"
                    f"*Проект:* {r[7]}\n"
                    f"*Язык:* {r[8]}"
                )
            for m in messages:
                send_telegram_message(chat_id, m)
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка при получении лидов: {e}")
        return "ok"

    if text.startswith("/addprompt "):
        if user_id != ADMIN_ID:
            send_telegram_message(chat_id, "⛔ Эта команда доступна только администратору.")
            return "ok"
        addition = text[len("/addprompt "):].strip()
        try:
            with open("docs/system_prompt.txt", "a", encoding="utf-8") as f:
                f.write("\n" + addition)
            global system_prompt
            system_prompt = load_system_prompt()
            send_telegram_message(chat_id, "✅ Новый текст добавлен в system prompt.")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка при добавлении prompt: {e}")
        return "ok"

    if text.strip() == "/prompt":
        if user_id != ADMIN_ID:
            send_telegram_message(chat_id, "⛔ Эта команда доступна только администратору.")
            return "ok"
        try:
            with open("docs/system_prompt.txt", "r", encoding="utf-8") as f:
                current_prompt = f.read()
            if len(current_prompt) > 4000:
                send_telegram_message(chat_id, "⚠️ Промпт слишком длинный.")
            else:
                send_telegram_message(chat_id, f"📝 Текущий prompt:\n\n{current_prompt}")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Ошибка при чтении prompt: {e}")
        return "ok"

    # FSM — пошаговый опрос
    if user_id in fsm_state:
        step = fsm_state[user_id]
        answer = text.strip()
        if step == "ask_name":
            lead_data[user_id]["name"] = answer
            fsm_state[user_id] = "ask_platform"
            send_telegram_message(chat_id, "📱 Укажите платформу для связи: WhatsApp / Telegram / Zoom / Google Meet")
            return "ok"
        elif step == "ask_platform":
            lead_data[user_id]["platform"] = answer
            if any(w in answer.lower() for w in ["whatsapp", "ватсап", "вотсап"]):
                fsm_state[user_id] = "ask_phone"
                send_telegram_message(chat_id, "📞 Напишите номер WhatsApp:")
            else:
                fsm_state[user_id] = "ask_datetime"
                send_telegram_message(chat_id, "🗓 Когда удобно созвониться? (например: завтра утром или завтра в 16:00)")
            return "ok"
        elif step == "ask_phone":
            lead_data[user_id]["phone"] = answer
            fsm_state[user_id] = "ask_datetime"
            send_telegram_message(chat_id, "🗓 Когда удобно созвониться? (например: завтра утром или завтра в 16:00)")
            return "ok"
        elif step == "ask_datetime":
            lead_data[user_id]["datetime"] = answer
            # Сохраняем лид
            try:
                now = datetime.now().strftime("%Y-%m-%d %H:%M")
                date_part = answer.split()[0] if len(answer.split()) > 0 else ""
                time_part = answer.split()[1] if len(answer.split()) > 1 else ""
                sheet.append_row([
                    now,
                    lead_data[user_id].get("name", ""),
                    f"@{username}",
                    lead_data[user_id].get("phone", ""),
                    date_part,
                    time_part,
                    lead_data[user_id].get("platform", ""),
                    "",  # проект
                    language_code
                ])
                # Отправляем красивое финальное сообщение
                time_text = detect_time_of_day(answer)
                send_telegram_message(chat_id, f"✅ Отлично! Все данные переданы менеджеру. Мы свяжемся с вами {time_text}.")
            except Exception as e:
                send_telegram_message(chat_id, f"❌ Ошибка при записи в таблицу: {e}")
            fsm_state.pop(user_id)
            lead_data.pop(user_id)
            return "ok"

    # Если человек пишет про звонок — запускаем FSM
    if "звонок" in text.lower() or "созвон" in text.lower() or "консультац" in text.lower():
        fsm_state[user_id] = "ask_name"
        lead_data[user_id] = {}
        send_telegram_message(chat_id, "👋 Напишите, пожалуйста, ваше имя:")
        return "ok"

    # Обычная обработка сообщений
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
        reply = "Произошла техническая ошибка. Попробуйте позже."

    sessions[user_id] = (history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply}
    ])[-10:]

    send_telegram_message(chat_id, reply)

    # Отправка логотипа при упоминании ключевых слов
    keywords = ["авалон", "avalon", "ом", "buddha", "budda", "tao"]
    if any(k in text.lower() for k in keywords):
        logo = find_logo()
        if logo:
            send_telegram_photo(chat_id, logo, caption="Avalon — инвестиции на Бали 🌴")

    return "ok"

# Определение части дня
def detect_time_of_day(text):
    text = text.lower()
    if "утро" in text:
        return "утром"
    if "вечер" in text:
        return "вечером"
    if "день" in text:
        return "днём"
    return "в удобное для вас время"

@app.route("/", methods=["GET"])
def home():
    return "Avalon GPT работает стабильно."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
