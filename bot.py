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
        await auto_farm(query, context)
    elif data.startswith("buy_"):
        country_id = data.replace("buy_", "")
        await buy_number(query, context, country_id)
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


async def auto_farm(query, context):
    """Показывает список стран с ценами"""
    await query.edit_message_text("🌍 Загружаю актуальные страны и цены...")

    prices = farm.get_countries_with_prices()

    if not prices:
        await query.edit_message_text("❌ Ошибка связи с Tiger SMS. Проверьте баланс и API ключ.")
        return

    keyboard = []
    for item in prices[:15]:  # Показываем 15 самых дешёвых
        # Предполагаемая структура ответа: {'name': 'Россия', 'price': 170.00, 'country_id': '0'}
        country_name = item.get('name', item.get('country', f"Страна {item.get('id', '?')}"))
        price = item.get('price', item.get('cost', 0))
        country_id = item.get('country_id', item.get('id', ''))

        keyboard.append([
            InlineKeyboardButton(
                f"✅ {country_name} — {price:.2f} ₽",
                callback_data=f"buy_{country_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])

    balance = farm.get_balance()
    balance_text = f"💰 Баланс: {balance:.2f} руб" if balance else "💰 Баланс: неизвестен"

    await query.edit_message_text(
        f"💰 **Выберите страну для регистрации:**\n\n{balance_text}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )


async def buy_number(query, context, country_id):
    """Покупает номер в выбранной стране"""
    balance = farm.get_balance()
    if balance is None:
        await query.edit_message_text("❌ Не удалось подключиться к Tiger SMS")
        return

    if balance < 5:
        await query.edit_message_text(
            f"❌ *Недостаточно средств!*\n\n"
            f"💰 Баланс: *{balance:.2f} руб*\n\n"
            f"Пополни баланс на Tiger SMS и попробуй снова.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    await query.edit_message_text(f"🤖 Покупаю номер...\n\n⏳ Жди, это может занять минуту.")

    success, message, account_data = await farm.buy_number_by_country_id(query.from_user.id, country_id)

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


# Остальные функции (show_my_accounts, generate_qr, message_handler, и т.д.) остаются без изменений
# Они такие же, как в предыдущих версиях. Если нужно, могу добавить их полностью.
