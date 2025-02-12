import sqlite3
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.enums.parse_mode import ParseMode
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from config import BOT_TOKEN, FORUM_CHAT_ID, ADMIN_ID

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()

def execute_query(query, params=(), fetchone=False, fetchall=False):
    with sqlite3.connect("valentines.db", check_same_thread=False) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        if fetchone:
            return cursor.fetchone()
        if fetchall:
            return cursor.fetchall()

execute_query('''CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    is_banned INTEGER DEFAULT 0
)''')

execute_query('''CREATE TABLE IF NOT EXISTS valentines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER,
    to_user_id INTEGER,
    message TEXT,
    FOREIGN KEY(from_user_id) REFERENCES users(telegram_id),
    FOREIGN KEY(to_user_id) REFERENCES users(telegram_id)
)''')

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Отправить валентинку")],
                [KeyboardButton(text="Мои валентинки")]], resize_keyboard=True
)

class ValentineState(StatesGroup):
    waiting_for_username = State()
    waiting_for_message = State()
    waiting_for_reply = State()

@router.message(Command('start'))
async def start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username.lower() if message.from_user.username else None
    execute_query(
        "INSERT INTO users (telegram_id, username) VALUES (?, ?) ON CONFLICT(telegram_id) DO UPDATE SET username = excluded.username",
        (user_id, username)
    )
    await message.answer("Привет! Отправь анонимную валентинку или посмотри свои полученные!", reply_markup=main_keyboard)

@router.message(F.text == "Отправить валентинку")
async def send_valentine(message: Message, state: FSMContext):
    await message.answer("Введите @username получателя:")
    await state.set_state(ValentineState.waiting_for_username)

@router.message(ValentineState.waiting_for_username)
async def get_recipient(message: Message, state: FSMContext):
    input_username = message.text.strip('@').lower()
    recipient = execute_query("SELECT telegram_id FROM users WHERE username = ?", (input_username,), fetchone=True)
    if not recipient:
        await message.answer("❌ Пользователь не зарегистрирован в боте.")
        await state.clear()
        return
    await state.update_data(recipient_id=recipient[0], username=input_username)
    await message.answer("Теперь отправьте текст в качестве валентинки:")
    await state.set_state(ValentineState.waiting_for_message)

@router.message(ValentineState.waiting_for_message)
async def get_message(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return

    user_data = await state.get_data()
    recipient_id = user_data.get("recipient_id")
    from_user_id = message.from_user.id
    from_username = message.from_user.username or "Аноним"
    to_username = user_data["username"]

    recipient = execute_query("SELECT telegram_id FROM users WHERE telegram_id = ?", (recipient_id,), fetchone=True)
    if not recipient:
        await message.answer("❌ Пользователь не зарегистрирован в боте. Валентинка не отправлена.")
        await state.clear()
        return

    forum_message = f"@{to_username} вам была отправлена валентинка 💌"
    reply_text = "💌 Вам пришла валентинка! Вы можете ответить на нее."
    
    if message.text:
        valentine_message = message.text
        execute_query("INSERT INTO valentines (from_user_id, to_user_id, message) VALUES (?, ?, ?)",
                        (from_user_id, recipient_id, valentine_message))
        await bot.send_message(recipient_id, f"{reply_text}\n\n<b>{valentine_message}</b>", 
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ответить", callback_data=f"reply_{from_user_id}")]]))
    elif message.photo:
        await bot.send_photo(recipient_id, message.photo[-1].file_id, caption=reply_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ответить", callback_data=f"reply_{from_user_id}")]]))
    elif message.sticker:
        await bot.send_sticker(recipient_id, message.sticker.file_id, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ответить", callback_data=f"reply_{from_user_id}")]]))
    else:
        await message.answer("❌ Неподдерживаемый формат сообщения.")
        await state.clear()
        return

    await bot.send_message(FORUM_CHAT_ID, text=forum_message, message_thread_id=49858)
    await message.answer("💌 Валентинка отправлена!")
    await state.clear()

@router.callback_query(F.data.startswith("reply_"))
async def reply_callback(callback: types.CallbackQuery, state: FSMContext):
    sender_id = int(callback.data.split("_")[1])
    await state.update_data(sender_id=sender_id)
    await state.set_state(ValentineState.waiting_for_reply)
    await callback.message.answer("Введите ваш ответ:")
    await callback.answer()

@router.message(ValentineState.waiting_for_reply)
async def reply_to_valentine(message: Message, state: FSMContext):
    user_data = await state.get_data()
    sender_id = user_data.get("sender_id")
    recipient_id = message.from_user.id
    reply_message = message.text
    reply_text = "💌 Вам пришла валентинка! Вы можете ответить на нее."
    if message.text:
        valentine_message = message.text
        execute_query("INSERT INTO valentines (from_user_id, to_user_id, message) VALUES (?, ?, ?)",
                    (recipient_id, sender_id, reply_message))
        await bot.send_message(sender_id, f"💌 Вам пришел ответ: \n\n<b>{reply_message}</b>")
    elif message.photo:
        await bot.send_photo(sender_id, message.photo[-1].file_id, caption=reply_text)
    elif message.sticker:
        await bot.send_sticker(sender_id, message.sticker.file_id)
    else:
        await message.answer("❌ Неподдерживаемый формат сообщения.")
        await state.clear()
        return
    await message.answer("💌 Ваш ответ отправлен!")
    await state.clear()

@router.message(F.text == "Мои валентинки")
async def my_valentines(message: Message):
    user_id = message.from_user.id
    valentines = execute_query("SELECT message FROM valentines WHERE to_user_id = ?", (user_id,), fetchall=True)
    
    if not valentines:
        await message.answer("У вас пока нет валентинок.")
    else:
        for val in valentines:
            await message.answer(f'💌 - {val[0]}')

@router.message(Command('ban'))
async def ban_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_user_id = int(message.text.split()[1])
        execute_query("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (target_user_id,))
        await message.answer(f"Пользователь с ID {target_user_id} заблокирован.")
    except:
        await message.answer("Укажите telegram_id пользователя.")

@router.message(Command('unban'))
async def unban_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target_user_id = int(message.text.split()[1])
        execute_query("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (target_user_id,))
        await message.answer(f"Пользователь с ID {target_user_id} разблокирован.")
    except:
        await message.answer("Укажите telegram_id пользователя.")

async def main():
    logging.basicConfig(level=logging.INFO)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())