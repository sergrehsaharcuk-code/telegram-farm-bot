import asyncio
import os
import re
import zipfile
import json
import qrcode
import logging
from io import BytesIO
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

from config import BOT_TOKEN, ADMIN_IDS, API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR
from farm_core import TelegramFarm

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

WAITING_PHONE, WAITING_CODE = range(2)

farm = TelegramFarm(API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR)


def clean_phone_number(raw_phone):
    phone = re.sub(r'[^\d+]', '', raw_phone)
    if phone.startswith('8') and len(phone) == 11:
        phone = '+7' + phone[1:]
    elif phone.startswith('7') and len(phone) == 11 and not phone.startswith('+'):
        phone = '+' + phone
    elif not phone.startswith('+'):
        phone = '+' + phone
    return phone


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет доступа")
        return
    
    proxies_count = len(farm.proxy_manager.proxies)
    accounts_count = len(farm.get_accounts_list())
    
    keyboard = [
        [InlineKeyboardButton("📱 Регистрация", callback_data="register")],
        [InlineKeyboardButton("🤖 АВТОФЕРМА", callback_data="auto_farm")],
        [InlineKeyboardButton("📦 Мои аккаунты", callback_data="my_accounts")],
        [InlineKeyboardButton("📦 Все аккаунты", callback_data="export_all")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🤖 *Telegram Farm Bot*\n\n"
        f"🌐 Прокси: {proxies_count}\n"
        f"📁 Аккаунтов: {accounts_count}\n"
        f"⏳ В процессе: {len(farm.pending_registrations)}",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("❌ У вас нет доступа")
        return
    
    data = query.data
    
    if data == "register":
        await query.edit_message_text(
            "📱 Введи номер телефона в любом формате:\n"
            "Пример: `+79991234567` или `8 999 123-45-67`",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['state'] = WAITING_PHONE
        
    elif data == "auto_farm":
        await show_countries(query, context)
    elif data.startswith("buy_"):
        country = data.replace("buy_", "")
        await buy_number(query, context, country)
    elif data == "my_accounts":
        await show_my_accounts(query, context)
    elif data == "export_all":
        await export_all_accounts(query, context)
    elif data == "stats":
        await show_stats(query, context)
    elif data == "help":
        await show_help(query, context)
    elif data == "back":
        await back_to_menu(query, context)
    elif data.startswith("download_"):
        filename = data.replace("download_", "")
        await download_account(query, context, filename)
    elif data.startswith("qr_"):
        filename = data.replace("qr_", "") + ".zip"
        await generate_qr(query, context, filename)
    elif data.startswith("cancel_reg_"):
        phone = data.replace("cancel_reg_", "")
        await cancel_registration(query, context, phone)


async def show_countries(query, context):
    """Показывает список стран с ценами (без проверки баланса)"""
    await query.edit_message_text("⏳ Загружаю цены...")
    
    prices = farm.tiger_sms.get_prices()
    if not prices:
        await query.edit_message_text("❌ Не удалось загрузить цены")
        return
    
    keyboard = []
    for country, data in prices.items():
        price = data.get('cost', 0) / 100
        keyboard.append([InlineKeyboardButton(
            f"📱 {country.upper()} - {price:.2f} руб", 
            callback_data=f"buy_{country}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    
    await query.edit_message_text(
        "💸 *Выбери страну для номера:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def buy_number(query, context, country):
    """Покупает номер (проверка баланса после выбора страны)"""
    
    # Проверяем баланс ТОЛЬКО после выбора страны
    balance = farm.tiger_sms.get_balance()
    if balance is None:
        await query.edit_message_text("❌ Не удалось подключиться к Tiger SMS")
        return
    
    if balance < 5:
        await query.edit_message_text(
            f"❌ *Недостаточно средств!*\n\n"
            f"💰 Баланс: *{balance:.2f} руб*\n"
            f"📱 Номер в *{country.upper()}* стоит ~5 руб\n\n"
            f"Пополни баланс на Tiger SMS и попробуй снова.\n\n"
            f"🔙 Нажми «Назад» и выбери другую страну.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="auto_farm")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await query.edit_message_text(f"🤖 Покупаю номер в {country.upper()}...\n\n⏳ Жди, это может занять минуту.")
    
    success, message, account_data = await farm.auto_register_country(query.from_user.id, country)
    
    if success:
        await query.message.reply_text(f"✅ {message}\n\n📱 Номер: {account_data['phone']}")
        
        zip_file = os.path.join(ACCOUNTS_DIR, f"{account_data['phone'].replace('+', '')}.zip")
        if os.path.exists(zip_file):
            with open(zip_file, 'rb') as f:
                await query.message.reply_document(
                    document=f,
                    filename=os.path.basename(zip_file),
                    caption=f"✅ Аккаунт {account_data['phone']} готов!"
                )
    else:
        await query.message.reply_text(f"❌ {message}")
    
    await back_to_menu(query, context)


async def show_my_accounts(query, context):
    accounts = farm.get_accounts_list()
    
    if not accounts:
        await query.edit_message_text("📭 Нет аккаунтов")
        return
    
    keyboard = []
    for acc in accounts:
        acc_name = acc.replace('.zip', '')
        keyboard.append([
            InlineKeyboardButton(f"📱 {acc_name}", callback_data=f"download_{acc}"),
            InlineKeyboardButton(f"🔲 QR", callback_data=f"qr_{acc}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("📦 Выбери аккаунт:", reply_markup=reply_markup)


async def generate_qr(query, context, filename):
    file_path = os.path.join(ACCOUNTS_DIR, filename)
    
    if not os.path.exists(file_path):
        await query.edit_message_text("❌ Аккаунт не найден")
        return
    
    await query.edit_message_text("⏳ Генерирую QR-код...")
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            session_string = None
            for file in zf.namelist():
                if file.endswith('info.json'):
                    with zf.open(file) as f:
                        info = json.load(f)
                        session_string = info.get('session_string')
                        break
                elif file.endswith('auth_key.txt'):
                    with zf.open(file) as f:
                        session_string = f.read().decode('utf-8').strip()
                        break
        
        if not session_string:
            await query.edit_message_text("❌ Не удалось найти session_string в архиве")
            return
        
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(session_string)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        
        await query.message.reply_photo(
            photo=buf,
            caption=f"🔑 *QR-код для входа*\n\n"
                    f"📱 *Как войти:*\n"
                    f"• *Android:* Telegram → «Войти по QR-коду» → сканируй\n"
                    f"• *iPhone:* Настройки → Устройства → Сканировать QR\n\n"
                    f"⚠️ QR-код одноразовый!",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await query.edit_message_text("✅ QR-код отправлен!")
        
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    text = update.message.text.strip()
    state = context.user_data.get('state')
    
    if state == WAITING_PHONE:
        phone = clean_phone_number(text)
        if len(phone) < 10 or len(phone) > 16:
            await update.message.reply_text("❌ Неверный формат номера!\nПример: +79991234567")
            return
        
        context.user_data['state'] = None
        await start_registration(update, context, phone)
        
    elif state == WAITING_CODE:
        code = text
        if not code.isdigit():
            await update.message.reply_text("❌ Код должен состоять только из цифр")
            return
        
        context.user_data['state'] = None
        await complete_registration(update, context, code)
        
    else:
        await update.message.reply_text("Нажми /start для начала работы")


async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, phone):
    if phone in farm.pending_registrations:
        await update.message.reply_text(f"⏳ Регистрация для {phone} уже идёт")
        return
    
    success, message = await farm.start_registration(phone, update.effective_user.id)
    
    if not success:
        await update.message.reply_text(f"❌ {message}")
        return
    
    context.user_data['waiting_code_phone'] = phone
    context.user_data['state'] = WAITING_CODE
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_reg_{phone}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📨 *{message}*\n\n✏️ Введи код из SMS:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def complete_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, code):
    phone = context.user_data.get('waiting_code_phone')
    
    if not phone:
        await update.message.reply_text("❌ Нет ожидающей регистрации")
        return
    
    status_msg = await update.message.reply_text("⏳ Проверяю код...")
    
    success, message, account_data = await farm.complete_registration(phone, code)
    
    if success:
        await status_msg.edit_text(f"{message}\n\n📱 Номер: {account_data['phone']}")
        
        zip_file = os.path.join(ACCOUNTS_DIR, f"{account_data['phone'].replace('+', '')}.zip")
        if os.path.exists(zip_file):
            with open(zip_file, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename=os.path.basename(zip_file),
                    caption=f"✅ Аккаунт {account_data['phone']} готов!"
                )
        
        context.user_data.pop('waiting_code_phone', None)
    else:
        await status_msg.edit_text(f"❌ {message}")


async def export_all_accounts(query, context):
    accounts = farm.get_accounts_list()
    
    if not accounts:
        await query.edit_message_text("📭 Нет аккаунтов")
        return
    
    await query.edit_message_text("📦 Собираю архив...")
    
    all_zip = os.path.join(ACCOUNTS_DIR, "all_accounts.zip")
    
    try:
        with zipfile.ZipFile(all_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for acc in accounts:
                acc_path = os.path.join(ACCOUNTS_DIR, acc)
                if os.path.exists(acc_path):
                    zipf.write(acc_path, acc)
        
        with open(all_zip, 'rb') as f:
            await query.message.reply_document(
                document=f,
                filename="all_accounts.zip",
                caption=f"📦 Все аккаунты ({len(accounts)} шт.)"
            )
        
        os.remove(all_zip)
        await back_to_menu(query, context)
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")


async def download_account(query, context, filename):
    file_path = os.path.join(ACCOUNTS_DIR, filename)
    
    if not os.path.exists(file_path):
        await query.edit_message_text("❌ Файл не найден")
        return
    
    with open(file_path, 'rb') as f:
        await query.message.reply_document(document=f, filename=filename)
    
    await query.answer("Скачивание начато!")


async def cancel_registration(query, context, phone):
    if phone in farm.pending_registrations:
        client = farm.pending_registrations[phone]['client']
        await client.disconnect()
        del farm.pending_registrations[phone]
    
    if context.user_data.get('waiting_code_phone') == phone:
        context.user_data.pop('waiting_code_phone', None)
    
    context.user_data['state'] = None
    
    await query.edit_message_text(f"❌ Регистрация {phone} отменена")


async def show_stats(query, context):
    accounts = farm.get_accounts_list()
    pending = len(farm.pending_registrations)
    proxies = len(farm.proxy_manager.proxies)
    
    await query.edit_message_text(
        f"📊 *Статистика*\n\n"
        f"🌐 Прокси: {proxies}\n"
        f"✅ Аккаунтов: {len(accounts)}\n"
        f"⏳ В процессе: {pending}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back")]]),
        parse_mode=ParseMode.MARKDOWN
    )


async def show_help(query, context):
    help_text = (
        "🤖 *Telegram Farm Bot*\n\n"
        "*Как продавать аккаунты:*\n\n"
        "1️⃣ *Автоферма*\n"
        "   • Нажми «АВТОФЕРМА»\n"
        "   • Выбери страну\n"
        "   • Бот сам купит номер и зарегистрирует аккаунт\n\n"
        "2️⃣ *Ручная регистрация*\n"
        "   • Нажми «Регистрация»\n"
        "   • Введи номер из Tiger SMS\n"
        "   • Введи код\n\n"
        "3️⃣ *Продажа*\n"
        "   • «Мои аккаунты» → скачать архив (TData)\n"
        "   • Или нажать «QR» → отправить QR-код покупателю\n\n"
        f"📁 Папка: {ACCOUNTS_DIR}"
    )
    
    await query.edit_message_text(
        help_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back")]]),
        parse_mode=ParseMode.MARKDOWN
    )


async def back_to_menu(query, context):
    accounts_count = len(farm.get_accounts_list())
    proxies_count = len(farm.proxy_manager.proxies)
    
    keyboard = [
        [InlineKeyboardButton("📱 Регистрация", callback_data="register")],
        [InlineKeyboardButton("🤖 АВТОФЕРМА", callback_data="auto_farm")],
        [InlineKeyboardButton("📦 Мои аккаунты", callback_data="my_accounts")],
        [InlineKeyboardButton("📦 Все аккаунты", callback_data="export_all")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    
    await query.edit_message_text(
        f"🤖 *Telegram Farm Bot*\n\n🌐 Прокси: {proxies_count}\n📁 Аккаунтов: {accounts_count}\n⏳ В процессе: {len(farm.pending_registrations)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


def main():
    print("🌐 Загрузка прокси...")
    farm.load_proxies()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    print("🤖 Бот запущен и готов к работе!")
    print("📁 Аккаунты:", ACCOUNTS_DIR)
    print("=" * 50)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
