import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
from config import BOT_TOKEN, ADMIN_ID
from database import db

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальный словарь для связи пересланных сообщений с диалогами
message_to_dialog = {}

# ============ КОМАНДЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение для пользователя."""
    user = update.effective_user
    welcome_text = f"""Привет! 👋

*Привет, это анонимный бот Секретов Деревни Универсиады.*

Просто напиши сюда своё сообщение — и оно *анонимно* перейдёт администратору.

📌 *Как это работает:*
1. Ты пишешь сюда *что угодно* (вопрос, новость, предложение, мемы или что твоего соседа бросила девушка и он плачет по ночам)
2. Администратор получает твоё сообщение *без твоего имени*
3. Он может ответить тебе — и ответ тоже придёт *анонимно*

💡 *Если хочешь, чтобы пост был неанонимным:* укажи в тексте свой @username, иначе пост выложится анонимно.

А если бот сломался, пиши в сообщения каналу или админу @Dushniykotik."""
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
    logger.info(f"Новый пользователь: {user.id}")

# ============ ПЕРЕСЫЛКА СООБЩЕНИЙ ОТ ПОЛЬЗОВАТЕЛЕЙ АДМИНУ ============
async def forward_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересылает любое сообщение от пользователя админу."""
    try:
        # НЕ пересылаем сообщения от самого админа
        if update.effective_user.id == ADMIN_ID:
            logger.info("Получено сообщение от админа, но не reply - игнорируем")
            return
            
        user = update.effective_user
        message = update.message
        
        # Определяем тип контента и готовим текст
        text_content = ""
        if message.text:
            text_content = message.text
        elif message.caption:
            text_content = message.caption
        
        # Извлекаем юзернейм из текста, если пользователь сам его указал
        user_tag_in_message = None
        if text_content and "@" in text_content:
            import re
            match = re.search(r'@(\w+)', text_content)
            if match:
                user_tag_in_message = f"@{match.group(1)}"
        
        # Создаем или находим диалог для этого пользователя
        dialog_id = db.get_or_create_dialog(user.id, user_tag_in_message)
        
        # Сохраняем сообщение в базу (от пользователя)
        db.save_message(dialog_id, from_admin=False, text=text_content)
        
        # Формируем информационное сообщение для админа
        dialog_info = f"🆔 Диалог: {dialog_id}"
        if user_tag_in_message:
            dialog_info += f"\n👤 Пользователь указал: {user_tag_in_message}"
        
        # Отправляем сообщение админу
        sent_to_admin = None
        if message.photo:
            sent_to_admin = await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=f"{dialog_info}\n\n{text_content}" if text_content else dialog_info
            )
        elif message.video:
            sent_to_admin = await context.bot.send_video(
                chat_id=ADMIN_ID,
                video=message.video.file_id,
                caption=f"{dialog_info}\n\n{text_content}" if text_content else dialog_info
            )
        else:
            sent_to_admin = await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"{dialog_info}\n\n{text_content}"
            )
        
        # Запоминаем связь между сообщением у админа и диалогом+пользователем
        if sent_to_admin:
            message_to_dialog[sent_to_admin.message_id] = (dialog_id, user.id)
            logger.info(f"Сообщение переслано админу. Диалог {dialog_id}, Пользователь {user.id}")
        
        # Подтверждение пользователю
        await message.reply_text("✅ Ваше сообщение анонимно отправлено администратору. Ожидайте ответа.")
        
    except Exception as e:
        logger.error(f"Ошибка пересылки админу: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при отправке. Попробуйте позже.")

# ============ ОБРАБОТКА ОТВЕТОВ АДМИНА (REPLY) ============
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ админа на пересланное сообщение."""
    try:
        logger.info("=== НАЧАЛО ОБРАБОТКИ ОТВЕТА АДМИНА ===")
        logger.info(f"ID пользователя (админа): {update.effective_user.id}")
        
        # Проверяем, что сообщение от админа и это ответ (reply)
        if update.effective_user.id != ADMIN_ID:
            logger.warning("Сообщение не от админа, игнорируем")
            return
        
        reply_to_message = update.message.reply_to_message
        if not reply_to_message:
            logger.warning("Сообщение не является ответом (reply), игнорируем")
            return
        
        logger.info(f"Ответ на сообщение с ID: {reply_to_message.message_id}")
        logger.info(f"Текст ответа: {update.message.text}")
        
        # Ищем, к какому диалогу принадлежит сообщение, на которое ответили
        original_message_id = reply_to_message.message_id
        
        if original_message_id not in message_to_dialog:
            error_msg = "❌ Не могу найти диалог для этого сообщения. Возможно, бот был перезапущен."
            logger.error(f"original_message_id {original_message_id} не найден в message_to_dialog")
            await update.message.reply_text(error_msg)
            return
        
        dialog_id, user_id = message_to_dialog[original_message_id]
        logger.info(f"Найден диалог: {dialog_id}, пользователь: {user_id}")
        
        # Получаем текст ответа
        admin_reply_text = update.message.text or update.message.caption
        
        if not admin_reply_text:
            await update.message.reply_text("❌ Ответ должен содержать текст.")
            logger.warning("Ответ админа без текста")
            return
        
        # Сохраняем ответ админа в базу
        db.save_message(dialog_id, from_admin=True, text=admin_reply_text)
        logger.info(f"Ответ сохранён в БД для диалога {dialog_id}")
        
        # Отправляем ответ пользователю
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"💬 *Ответ администратора:*\n\n{admin_reply_text}\n\n_(Вы можете продолжить диалог, просто напишите снова)_",
                parse_mode='Markdown'
            )
            logger.info(f"Ответ успешно отправлен пользователю {user_id}")
            await update.message.reply_text(f"✅ Ответ отправлен в диалог {dialog_id}.")
        except Exception as e:
            error_msg = f"❌ Не удалось отправить ответ. Пользователь, возможно, заблокировал бота. Ошибка: {e}"
            logger.error(error_msg)
            await update.message.reply_text(error_msg)
        
    except Exception as e:
        logger.error(f"Критическая ошибка в handle_admin_reply: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при отправке ответа.")

# ============ КОМАНДЫ ДЛЯ АДМИНА ============
async def admin_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех активных диалогов."""
    if update.effective_user.id != ADMIN_ID:
        return
    
    dialogs = db.get_all_active_dialogs()
    
    if not dialogs:
        await update.message.reply_text("📭 Нет активных диалогов.")
        return
    
    response = "📋 *Активные диалоги:*\n\n"
    for dialog in dialogs:
        dialog_id, user_id, user_tag, last_activity = dialog
        time_str = last_activity.split(".")[0] if isinstance(last_activity, str) else str(last_activity)[:16]
        
        dialog_line = f"*🆔 Диалог {dialog_id}*"
        if user_tag:
            dialog_line += f"\n👤 Указал тег: {user_tag}"
        else:
            dialog_line += f"\n👤 Аноним"
        dialog_line += f"\n⏰ Последняя активность: {time_str}\n"
        
        messages = db.get_dialog_messages(dialog_id, limit=2)
        if messages:
            preview = ""
            for msg in messages[-2:]:
                from_admin, text, _, _ = msg
                prefix = "👨‍💼 Вы: " if from_admin else "👤 Аноним: "
                if text:
                    preview += prefix + (text[:50] + "..." if len(text) > 50 else text) + "\n"
            if preview:
                dialog_line += f"📝 {preview}"
        
        response += dialog_line + "─" * 20 + "\n"
    
    keyboard = []
    for dialog in dialogs[:10]:
        dialog_id = dialog[0]
        keyboard.append([InlineKeyboardButton(f"📨 История диалога {dialog_id}", callback_data=f"history_{dialog_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(response, parse_mode='Markdown', reply_markup=reply_markup)

async def show_dialog_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю конкретного диалога."""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    dialog_id = int(query.data.split('_')[1])
    messages = db.get_dialog_messages(dialog_id, limit=100)
    
    if not messages:
        await query.edit_message_text(f"Диалог {dialog_id} не содержит сообщений.")
        return
    
    history_text = f"📜 *История диалога {dialog_id}:*\n\n"
    
    for msg in messages:
        from_admin, text, media_type, sent_at = msg
        time_str = str(sent_at)[:16] if sent_at else ""
        
        if from_admin:
            history_text += f"👨‍💼 *Вы* ({time_str}):\n{text}\n\n"
        else:
            history_text += f"👤 *Аноним* ({time_str}):\n{text}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 К списку диалогов", callback_data="back_to_dialogs")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if len(history_text) > 4000:
        parts = [history_text[i:i+4000] for i in range(0, len(history_text), 4000)]
        await query.edit_message_text(text=parts[0], parse_mode='Markdown', reply_markup=reply_markup)
        for part in parts[1:]:
            await context.bot.send_message(chat_id=ADMIN_ID, text=part, parse_mode='Markdown')
    else:
        await query.edit_message_text(text=history_text, parse_mode='Markdown', reply_markup=reply_markup)

async def handle_back_to_dialogs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к списку диалогов."""
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        return
    
    await admin_chats(update, context)

# ============ ЗАПУСК БОТА ============
def main():
    """Запуск бота."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # 1. Сначала обработчики КОМАНД
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chats", admin_chats))
    
    # 2. Затем обработчики КНОПОК
    application.add_handler(CallbackQueryHandler(show_dialog_history, pattern="^history_"))
    application.add_handler(CallbackQueryHandler(handle_back_to_dialogs, pattern="^back_to_dialogs$"))
    
    # 3. Самый важный блок: обработчики ОТВЕТОВ АДМИНА (REPLY)
    #    Должны стоять ДО обработчиков обычных сообщений!
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(ADMIN_ID) & filters.REPLY,
        handle_admin_reply
    ))
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO) & filters.Chat(ADMIN_ID) & filters.REPLY,
        handle_admin_reply
    ))
    
    # 4. Обработчики обычных сообщений от пользователей
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.User(ADMIN_ID),
        forward_to_admin
    ))
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO) & ~filters.User(ADMIN_ID),
        forward_to_admin
    ))
    
    logger.info("Анонимный бот-переписка запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()