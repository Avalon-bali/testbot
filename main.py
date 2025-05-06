# продолжение функции telegram_webhook()
    def send_image_once(key, filename, caption):
        if not session_flags.get(user_id, {}).get(f"{key}_photo_sent"):
            send_telegram_message(chat_id, caption, photo_path=f"AVALON/avalon-photos/{filename}")
            session_flags.setdefault(user_id, {})[f"{key}_photo_sent"] = True

    if any(w in lower_text for w in ["avalon", "авалон"]):
        send_image_once("avalon", "Avalon-reviews-and-ratings-1.jpg", "Avalon | Development & Investment. Подробнее ниже 👇")
    if any(w in lower_text for w in ["om", "ом"]):
        send_image_once("om", "om.jpg", "OM Club House. Подробнее ниже 👇")
    if any(w in lower_text for w in ["buddha", "будда", "буда"]):
        send_image_once("buddha", "buddha.jpg", "BUDDHA Club House. Сейчас расскажу 👇")
    if any(w in lower_text for w in ["tao", "тао"]):
        send_image_once("tao", "tao.jpg", "TAO Club House. Ниже вся информация 👇")

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

    # FSM запуск
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
    return "Avalon bot ✅ FSM, GPT, статистика, изображения"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🟢 Starting Avalon bot on port {port}")
    app.run(host="0.0.0.0", port=port)
