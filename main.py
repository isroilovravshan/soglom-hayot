"""
╔══════════════════════════════════════════════════════════════╗
║         🥗 SOGLOM TURMUSH TARZI BOT — main.py               ║
║         Aiogram 3.x | SQLite | Gemini Vision API            ║
║         Production-ready | By: Senior Python Dev            ║
╚══════════════════════════════════════════════════════════════╝

Ishga tushirish uchun:
    pip install aiogram aiosqlite google-generativeai python-dotenv aiohttp

Muhit o'zgaruvchilari (.env fayl):
    BOT_TOKEN=your_telegram_bot_token
    GEMINI_API_KEY=your_gemini_api_key
"""

import asyncio
import logging
import os
import sqlite3
from datetime import date, datetime
from io import BytesIO
from os import getenv

import aiohttp
from google import genai
from google.genai import types as genai_types
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (

    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# 🔧 KONFIGURATSIYA
# ─────────────────────────────────────────────
load_dotenv()

BOT_TOKEN=getenv("BOT_TOKEN")
GEMINI_API_KEY=getenv("GEMINI_API_KEY")
DB_PATH: str = "soglom_bot.db"

# Gemini modeli: gemini-2.0-flash — eng tez va bepul kvotali
GEMINI_MODEL_NAME: str = "gemini-2.5-flash"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# Logging sozlamalari
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 📊 MA'LUMOTLAR BAZASI (SQLite)
# ─────────────────────────────────────────────

def init_database() -> None:
    """Ma'lumotlar bazasini yaratish va jadvallarni sozlash."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Foydalanuvchilar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            joined_at   TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # Taomlar tarixi jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS food_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            food_name   TEXT NOT NULL,
            calories    REAL NOT NULL,
            protein_g   REAL DEFAULT 0,
            fat_g       REAL DEFAULT 0,
            carbs_g     REAL DEFAULT 0,
            benefits    TEXT,
            analysis_date TEXT DEFAULT (date('now', 'localtime')),
            created_at  TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅ Ma'lumotlar bazasi muvaffaqiyatli yaratildi.")


def upsert_user(user_id: int, username: str | None, full_name: str) -> None:
    """Foydalanuvchini bazaga qo'shish yoki yangilash."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username  = excluded.username,
            full_name = excluded.full_name
    """, (user_id, username, full_name))
    conn.commit()
    conn.close()


def save_food_entry(
    user_id: int,
    food_name: str,
    calories: float,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    benefits: str,
) -> int:
    """Taom ma'lumotlarini bazaga saqlash. Saqlangan yozuv ID'sini qaytaradi."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO food_history (user_id, food_name, calories, protein_g, fat_g, carbs_g, benefits)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, food_name, calories, protein_g, fat_g, carbs_g, benefits))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_user_history(user_id: int, limit: int = 10) -> list[dict]:
    """Foydalanuvchi tarixini olish (oxirgi N ta yozuv)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT food_name, calories, analysis_date, created_at
        FROM food_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "food_name": r[0],
            "calories": r[1],
            "analysis_date": r[2],
            "created_at": r[3],
        }
        for r in rows
    ]


def get_daily_calories(user_id: int, day: str | None = None) -> dict:
    """Foydalanuvchining bugungi umumiy kaloriya va makronutrientlarini olish."""
    if day is None:
        day = date.today().isoformat()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(SUM(calories), 0)  AS total_cal,
            COALESCE(SUM(protein_g), 0) AS total_protein,
            COALESCE(SUM(fat_g), 0)     AS total_fat,
            COALESCE(SUM(carbs_g), 0)   AS total_carbs,
            COUNT(*)                    AS meals_count
        FROM food_history
        WHERE user_id = ? AND analysis_date = ?
    """, (user_id, day))
    row = cursor.fetchone()
    conn.close()
    return {
        "total_cal": row[0],
        "total_protein": row[1],
        "total_fat": row[2],
        "total_carbs": row[3],
        "meals_count": row[4],
        "date": day,
    }


def get_total_analyses(user_id: int) -> int:
    """Foydalanuvchining jami tahlil soni."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM food_history WHERE user_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


# ─────────────────────────────────────────────
# 🤖 GEMINI VISION API INTEGRATSIYASI
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """
Sen professional dietolog va oziq-ovqat analitigi AI yordamchisisisan.
Foydalanuvchi senga taom rasmi yuboradi. Sen quyidagi ma'lumotlarni JSON formatida qaytarasan:

{
  "food_name": "Taom nomi (o'zbek tilida)",
  "detected": true,
  "confidence": "yuqori | o'rta | past",
  "calories_per_100g": 250,
  "calories_total": 400,
  "protein_g": 15.5,
  "fat_g": 8.2,
  "carbs_g": 45.0,
  "fiber_g": 3.1,
  "vitamins": ["C vitamini", "B6", "Kalsiy"],
  "benefits": [
    "Immunitetni mustahkamlaydi",
    "Hazm qilishni yaxshilaydi",
    "Energiya beradi"
  ],
  "warnings": ["Yuqori shakar miqdori bor", "Tuzga e'tibor bering"],
  "category": "Asosiy taom | Salat | Ichimlik | Shirinlik | Meva | Sabzavot | Boshqa",
  "is_food": true
}

QOIDALAR:
- Agar rasm taom bo'lmasa: is_food=false, detected=false qaytargin
- Kaloriya hisoblashda o'rtacha porsiya (200-400g) uchun hisoblash
- Barcha javoblar o'zbek tilida bo'lsin
- Faqat JSON qaytargin, hech qanday izoh yoki markdown yo'q
""".strip()


async def analyze_food_image(image_bytes: bytes) -> dict:
    import json
    import re

    # Asosiy model band bo'lsa, fallback ishlatiladi
    models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

    client = genai.Client(api_key=GEMINI_API_KEY)

    for model_name in models_to_try:
        try:
            logger.info(f"🤖 Model sinab ko'rilmoqda: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    genai_types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg",
                    ),
                    "Ushbu rasmdagi taomni tahlil qil va JSON qaytargin.",
                ],
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.2,
                    top_p=0.8,
                    max_output_tokens=2048,
                ),
            )

            raw_text = response.text.strip()
            logger.debug(f"🔍 Gemini raw javob: {raw_text[:300]}...")

            # Har qanday holatda { dan } gacha kesib olish
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1

            if start != -1 and end > start:
                raw_text = raw_text[start:end]
            else:
                logger.error(f"❌ JSON topilmadi. Raw: {raw_text[:200]}")
                return {"is_food": False, "detected": False, "error": "json_parse"}

            result = json.loads(raw_text.strip())
            logger.info(f"✅ [{model_name}] Tahlil muvaffaqiyatli: {result.get('food_name', 'Noma`lum')}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON parse xatosi ({model_name}): {e}")
            return {"is_food": False, "detected": False, "error": "json_parse"}

        except Exception as e:
            err_str = str(e).lower()

            if "503" in err_str or "unavailable" in err_str or "overloaded" in err_str:
                logger.warning(f"⚠️ [{model_name}] Server band (503), keyingi model sinab ko'riladi...")
                continue  # Fallback modelga o'tish

            if "quota" in err_str or "rate" in err_str or "429" in err_str:
                logger.warning(f"⚠️ API limit: {e}")
                return {"is_food": False, "detected": False, "error": "rate_limit"}

            if "api_key" in err_str or "401" in err_str or "403" in err_str:
                logger.error(f"❌ API kalit xatosi: {e}")
                return {"is_food": False, "detected": False, "error": "auth_error"}

            if "block" in err_str or "safety" in err_str:
                logger.warning(f"⚠️ Rasm bloklandi: {e}")
                return {"is_food": False, "detected": False, "error": "blocked"}

            logger.error(f"❌ Kutilmagan xato ({model_name}): {e}", exc_info=True)
            return {"is_food": False, "detected": False, "error": "unknown"}

    # Barcha modellar ishlamadi
    logger.error("❌ Barcha modellar 503 qaytardi")
    return {"is_food": False, "detected": False, "error": "rate_limit"}


# ─────────────────────────────────────────────
# 🎨 UI FORMATLASH YORDAMCHI FUNKSIYALAR
# HTML parse mode ishlatiladi — escape muammosi yo'q!
# ─────────────────────────────────────────────

def he(text: str) -> str:
    """
    HTML entity escape — foydalanuvchi ma'lumotlarini xavfsiz qilish.
    <, >, & belgilarini HTML kodiga o'tkazadi.
    """
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_analysis_result(data: dict, user_name: str) -> str:
    """Tahlil natijasini HTML formatda chiroyli ko'rsatish."""

    food_name  = he(data.get("food_name", "Noma'lum taom"))
    confidence = he(data.get("confidence", "o'rta"))
    calories   = data.get("calories_total", 0)
    protein    = data.get("protein_g", 0)
    fat        = data.get("fat_g", 0)
    carbs      = data.get("carbs_g", 0)
    fiber      = data.get("fiber_g", 0)
    vitamins   = data.get("vitamins", [])
    benefits   = data.get("benefits", [])
    warnings   = data.get("warnings", [])
    category   = he(data.get("category", "Boshqa"))

    # Ishonch darajasi emoji
    confidence_emoji = {"yuqori": "🟢", "o'rta": "🟡", "past": "🔴"}.get(
        data.get("confidence", ""), "🟡"
    )

    # Kaloriya darajasi
    if calories < 200:
        cal_emoji, cal_label = "🟢", "past kaloriyali"
    elif calories < 500:
        cal_emoji, cal_label = "🟡", "o'rtacha kaloriyali"
    else:
        cal_emoji, cal_label = "🔴", "yuqori kaloriyali"

    vitamins_str  = " • ".join(he(v) for v in vitamins) if vitamins else "Ma'lumot yo'q"
    benefits_str  = "\n".join(f"   ✅ {he(b)}" for b in benefits) if benefits else "   ✅ Ma'lumot yo'q"

    warnings_block = ""
    if warnings:
        warnings_block = "\n⚠️ <b>Diqqat:</b>\n" + "\n".join(f"   ⚡ {he(w)}" for w in warnings)

    return (
        f"🍽️ <b>TAOM TAHLILI NATIJASI</b>\n"
        f"{'─' * 30}\n\n"
        f"👤 <b>Foydalanuvchi:</b> {he(user_name)}\n"
        f"📅 <b>Sana:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"🔍 <b>Aniqlangan taom:</b>\n"
        f"   🍴 <b>{food_name}</b>\n"
        f"   {confidence_emoji} Ishonch darajasi: <code>{confidence}</code>\n"
        f"   🏷️ Kategoriya: <code>{category}</code>\n\n"
        f"🔥 <b>Kaloriya:</b>\n"
        f"   {cal_emoji} <b>{calories:.0f} kkal</b> ({cal_label})\n\n"
        f"⚗️ <b>Makronutrientlar (porsiya):</b>\n"
        f"   🥩 Oqsil (Protein): <code>{protein:.1f}g</code>\n"
        f"   🫙 Yog':            <code>{fat:.1f}g</code>\n"
        f"   🌾 Uglevodlar:      <code>{carbs:.1f}g</code>\n"
        f"   🌿 Kletchatka:      <code>{fiber:.1f}g</code>\n\n"
        f"💊 <b>Vitaminlar:</b>\n"
        f"   {vitamins_str}\n\n"
        f"💪 <b>Foydali xususiyatlari:</b>\n"
        f"{benefits_str}\n"
        f"{warnings_block}\n"
        f"{'─' * 30}\n"
        f"📊 /daily — bugungi umumiy kaloriya\n"
        f"📜 /history — taomlar tarixi"
    )


def format_history(history: list[dict], user_name: str) -> str:
    """Foydalanuvchi tarixini HTML formatda ko'rsatish."""
    if not history:
        return (
            "📭 <b>Tarix bo'sh</b>\n\n"
            "Hali hech qanday taom tahlil qilmadingiz.\n"
            "Taom rasmini yuboring va boshlaylik! 📸"
        )

    lines = [
        f"📜 <b>{he(user_name)} ning taomlar tarixi</b>\n",
        f"{'─' * 30}\n",
    ]
    for i, entry in enumerate(history, 1):
        date_str = he(entry["analysis_date"])
        time_str = entry["created_at"].split(" ")[-1][:5] if " " in entry["created_at"] else ""
        lines.append(
            f"{i}. 🍽️ <b>{he(entry['food_name'])}</b>\n"
            f"   🔥 {entry['calories']:.0f} kkal  "
            f"📅 {date_str}  🕐 {time_str}\n"
        )

    lines.append(f"\n{'─' * 30}")
    lines.append(f"Jami: <b>{len(history)} ta</b> tahlil ko'rsatildi.")
    return "\n".join(lines)


def format_daily_stats(stats: dict, user_name: str) -> str:
    """Kunlik statistikani HTML formatda ko'rsatish."""
    total_cal   = stats["total_cal"]
    protein     = stats["total_protein"]
    fat         = stats["total_fat"]
    carbs       = stats["total_carbs"]
    meals_count = stats["meals_count"]
    day         = stats["date"]

    DAILY_NORM:float = 2000.0
    progress   = min(total_cal / DAILY_NORM * 100, 100) if DAILY_NORM else 0

    filled = int(progress / 10)
    bar    = "🟩" * filled + "⬜" * (10 - filled)

    if total_cal == 0:
        status = "📭 Bugun hali taom tahlil qilinmagan"
    elif total_cal < DAILY_NORM * 0.5:
        status = "😴 Kunlik normaning kamida yarmi yeyilsin"
    elif total_cal < DAILY_NORM:
        status = "😊 Ajoyib! Normaga yaqinlashmoqdasiz"
    elif total_cal < DAILY_NORM * 1.2:
        status = "✅ Normani bajarib bo'ldingiz"
    else:
        status = "⚠️ Iste'mol ortiqcha, ehtiyot bo'ling"

    return (
        f"📊 <b>KUNLIK KALORIYA HISOBI</b>\n"
        f"{'─' * 30}\n\n"
        f"👤 <b>{he(user_name)}</b>\n"
        f"📅 <b>Sana:</b> {day}\n\n"
        f"🔥 <b>Iste'mol qilindi:</b> <code>{total_cal:.0f}</code> kkal\n"
        f"🎯 <b>Kunlik norma:</b>    <code>{DAILY_NORM:.0f}</code> kkal\n\n"
        f"📈 <b>Progress:</b> {bar} <code>{progress:.0f}%</code>\n\n"
        f"⚗️ <b>Makronutrientlar:</b>\n"
        f"   🥩 Oqsil:   <code>{protein:.1f}g</code>\n"
        f"   🫙 Yog':    <code>{fat:.1f}g</code>\n"
        f"   🌾 Uglevod: <code>{carbs:.1f}g</code>\n\n"
        f"🍽️ <b>Tahlil qilingan taomlar:</b> <code>{meals_count}</code> ta\n\n"
        f"{status}\n"
        f"{'─' * 30}"
    )


# ─────────────────────────────────────────────
# 🎹 INLINE KEYBOARD LARNI YARATISH
# ─────────────────────────────────────────────

def main_keyboard() -> InlineKeyboardMarkup:
    """Asosiy inline keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📸 Rasm yuborish", callback_data="send_photo"),
            InlineKeyboardButton(text="📜 Tarix", callback_data="view_history"),
        ],
        [
            InlineKeyboardButton(text="📊 Bugungi kaloriya", callback_data="daily_stats"),
            InlineKeyboardButton(text="ℹ️ Yordam", callback_data="help"),
        ],
    ])


def after_analysis_keyboard() -> InlineKeyboardMarkup:
    """Tahlildan so'ng ko'rsatiladigan keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📸 Yana rasm yuborish", callback_data="send_photo"),
            InlineKeyboardButton(text="📜 Tarixni ko'rish", callback_data="view_history"),
        ],
        [
            InlineKeyboardButton(text="📊 Bugungi kaloriya", callback_data="daily_stats"),
        ],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    """Orqaga qaytish keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="main_menu"),
            InlineKeyboardButton(text="📸 Rasm yuborish", callback_data="send_photo"),
        ],
    ])


# ─────────────────────────────────────────────
# 🔌 FSM HOLATLARI
# ─────────────────────────────────────────────

class AnalysisStates(StatesGroup):
    waiting_for_photo = State()


# ─────────────────────────────────────────────
# 🛣️ ROUTER VA HANDLERLAR
# ─────────────────────────────────────────────

router = Router()


# ──────────────────── /start ────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Bot ishga tushganda xush kelibsiz xabari."""
    user = message.from_user
    upsert_user(user.id, user.username, user.full_name)
    await state.clear()

    total = get_total_analyses(user.id)

    welcome_text = (
        f"🌿 <b>Salom, {he(user.first_name)}!</b>\n\n"
        f"Men — <b>Sog'lom Turmush Tarzi Bot</b>.\n"
        f"Taom rasmingizni yuboring va men:\n\n"
        f"   🔍 Taomni aniqlayman\n"
        f"   🔥 Kaloriyanı hisoblayman\n"
        f"   💊 Foydali xususiyatlarini ko'rsataman\n"
        f"   📊 Kunlik statistikangizni tutaman\n\n"
        f"📈 Siz allaqachon <b>{total} ta</b> taom tahlil qildingiz!\n\n"
        f"<i>Boshlash uchun taom rasmini yuboring</i> 📸"
    )
    await message.answer(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ──────────────────── /help ────────────────
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Yordam komandasi."""
    help_text = (
        "🤖 <b>BOT BUYRUQLARI</b>\n"
        "─────────────────────\n\n"
        "📸 <b>Rasm yuborish</b> — taom rasmini yuboring\n"
        "📊 /daily — bugungi kaloriya statistikasi\n"
        "📜 /history — so'nggi 10 ta tahlil tarixi\n"
        "🏠 /start — bosh menyuga qaytish\n"
        "❓ /help — yordam\n\n"
        "─────────────────────\n"
        "💡 <b>Maslahat:</b> Rasmlarni aniq va yaxshi yoritilgan holda yuboring — "
        "bu tahlil sifatini oshiradi!"
    )
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ──────────────────── /history ────────────────
@router.message(Command("history"))
async def cmd_history(message: Message) -> None:
    """Taomlar tarixini ko'rsatish."""
    user = message.from_user
    history = get_user_history(user.id, limit=10)
    text = format_history(history, user.first_name)

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


# ──────────────────── /daily ────────────────
@router.message(Command("daily"))
async def cmd_daily(message: Message) -> None:
    """Bugungi kaloriya statistikasini ko'rsatish."""
    user = message.from_user
    stats = get_daily_calories(user.id)
    text = format_daily_stats(stats, user.first_name)

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )


# ──────────────────── RASM QABUL QILISH ────────────────
@router.message(F.photo)
async def handle_photo(message: Message) -> None:
    """
    Foydalanuvchi yuborgan rasmni qabul qilish va AI orqali tahlil qilish.
    Bu — botning asosiy funksiyasi.
    """
    user = message.from_user
    upsert_user(user.id, user.username, user.full_name)

    # "Tahlil qilinmoqda..." xabari
    loading_msg = await message.answer(
        "⏳ <b>Rasm tahlil qilinmoqda...</b>\n\n"
        "🔍 Taom aniqlanmoqda\n"
        "🔥 Kaloriya hisoblanmoqda\n"
        "💊 Foydalilik tekshirilmoqda\n\n"
        "<i>Bu biroz vaqt olishi mumkin...</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Eng yuqori sifatli rasmni olish
        photo = message.photo[-1]
        bot: Bot = message.bot
        file = await bot.get_file(photo.file_id)

        # Rasmni yuklash
        image_bytes_buffer = BytesIO()
        await bot.download_file(file.file_path, destination=image_bytes_buffer)
        image_bytes = image_bytes_buffer.getvalue()

        logger.info(
            f"📷 Rasm qabul qilindi: user_id={user.id}, "
            f"size={len(image_bytes)} bayt"
        )

        # Claude API orqali tahlil
        result = await analyze_food_image(image_bytes)

        # Loading xabarini o'chirish
        await loading_msg.delete()

        # Taom topilmadi yoki rasm noto'g'ri
        if not result.get("is_food", False) or not result.get("detected", False):
            error_reason = result.get("error", "")
            if error_reason == "rate_limit":
                error_text = (
                    "⏳ <b>API limit tugadi</b>\n\n"
                    "Gemini API so'rovlar limiti tugadi.\n"
                    "Iltimos, bir daqiqa kuting va qayta urinib ko'ring."
                )
            elif error_reason == "auth_error":
                error_text = (
                    "🔑 <b>API kalit xatosi</b>\n\n"
                    "Gemini API kalit noto'g'ri yoki amal qilish muddati tugagan.\n"
                    "Administrator bilan bog'laning."
                )
            elif error_reason == "blocked":
                error_text = (
                    "🚫 <b>Rasm bloklandi</b>\n\n"
                    "Yuborilgan rasm AI tomonidan bloklandi.\n"
                    "Boshqa taom rasmini yuborib ko'ring! 📸"
                )
            elif error_reason in ("api_error", "stop_candidate"):
                error_text = (
                    "❌ <b>Xatolik yuz berdi</b>\n\n"
                    "AI servisi bilan aloqada muammo.\n"
                    "Iltimos, biroz kuting va qayta urinib ko'ring."
                )
            else:
                error_text = (
                    "🚫 <b>Taom aniqlanmadi</b>\n\n"
                    "Yuborilgan rasmdagi taom aniqlanmadi.\n\n"
                    "📌 <b>Iltimos:</b>\n"
                    "   • Aniq va yaxshi yoritilgan rasm yuboring\n"
                    "   • Taom to'liq ko'rinishda bo'lsin\n"
                    "   • Faqat taom rasmlari qabul qilinadi\n\n"
                    "<i>Boshqa rasm yuborib ko'ring!</i> 📸"
                )

            await message.answer(
                error_text,
                parse_mode=ParseMode.HTML,
                reply_markup=after_analysis_keyboard(),
            )
            return

        # Natijani bazaga saqlash
        save_food_entry(
            user_id=user.id,
            food_name=result.get("food_name", "Noma'lum"),
            calories=float(result.get("calories_total", 0)),
            protein_g=float(result.get("protein_g", 0)),
            fat_g=float(result.get("fat_g", 0)),
            carbs_g=float(result.get("carbs_g", 0)),
            benefits="; ".join(result.get("benefits", [])),
        )

        # Natijani formatlash va yuborish
        result_text = format_analysis_result(result, user.first_name)
        await message.answer(
            result_text,
            parse_mode=ParseMode.HTML,
            reply_markup=after_analysis_keyboard(),
        )

        logger.info(
            f"✅ Tahlil saqlandi: user_id={user.id}, "
            f"taom={result.get('food_name')}, "
            f"kaloriya={result.get('calories_total')}"
        )

    except aiohttp.ClientError as e:
        logger.error(f"❌ Tarmoq xatosi: {e}")
        await loading_msg.delete()
        await message.answer(
            "⚠️ <b>Tarmoq xatosi</b>\n\nInternet aloqasini tekshiring va qayta urinib ko'ring.",
            parse_mode=ParseMode.HTML,
            reply_markup=after_analysis_keyboard(),
        )
    except Exception as e:
        logger.error(f"❌ Kutilmagan xato: {e}", exc_info=True)
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await message.answer(
            "⛔ <b>Kutilmagan xato yuz berdi</b>\n\n"
            "Iltimos, qayta urinib ko'ring yoki /help buyrug'ini yuboring.",
            parse_mode=ParseMode.HTML,
            reply_markup=after_analysis_keyboard(),
        )


# ──────────────────── NOTO'G'RI MEDIA ────────────────
@router.message(F.document | F.video | F.audio | F.sticker | F.animation)
async def handle_wrong_media(message: Message) -> None:
    """Noto'g'ri media turiga javob."""
    await message.answer(
        "📵 <b>Bu turdagi fayl qabul qilinmaydi</b>\n\n"
        "Iltimos, faqat <b>rasm</b> (JPEG, PNG, WEBP) yuboring.\n"
        "Telefon kamerangizdan taom rasmini oling va yuboring! 📸",
        parse_mode=ParseMode.HTML,
        reply_markup=after_analysis_keyboard(),
    )


# ──────────────────── MATN XABARI ────────────────
@router.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message) -> None:
    """Oddiy matn xabariga javob."""
    await message.answer(
        "👋 Salom! Men faqat <b>taom rasmlarini</b> tahlil qilaman.\n\n"
        "📸 Taom rasmini yuboring va men:\n"
        "   - Taomni aniqlayman\n"
        "   - Kaloriyanı hisoblayman\n"
        "   - Foydali xususiyatlarini aytaman\n\n"
        "<i>Boshlash uchun rasm yuboring!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


# ─────────────────────────────────────────────
# 🎹 CALLBACK QUERY HANDLERLAR
# ─────────────────────────────────────────────

@router.callback_query(F.data == "send_photo")
async def cb_send_photo(callback: CallbackQuery) -> None:
    """'Rasm yuborish' tugmasi."""
    await callback.message.answer(
        "📸 <b>Taom rasmini yuboring!</b>\n\n"
        "<i>Aniq va yaxshi yoritilgan rasm yuboring — bu tahlil sifatini oshiradi.</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@router.callback_query(F.data == "view_history")
async def cb_history(callback: CallbackQuery) -> None:
    """'Tarix' tugmasi."""
    user = callback.from_user
    history = get_user_history(user.id, limit=10)
    text = format_history(history, user.first_name)

    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "daily_stats")
async def cb_daily(callback: CallbackQuery) -> None:
    """'Kunlik kaloriya' tugmasi."""
    user = callback.from_user
    stats = get_daily_calories(user.id)
    text = format_daily_stats(stats, user.first_name)

    await callback.message.answer(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery) -> None:
    """'Bosh menyu' tugmasi."""
    user = callback.from_user
    total = get_total_analyses(user.id)

    await callback.message.answer(
        f"🏠 <b>Bosh menyu</b>\n\n"
        f"👤 {he(user.first_name)}\n"
        f"📈 Jami tahlillar: <b>{total} ta</b>\n\n"
        f"<i>Taom rasmini yuboring yoki buyruq tanlang:</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    """'Yordam' tugmasi."""
    help_text = (
        "🤖 <b>BOT BUYRUQLARI</b>\n"
        "─────────────────────\n\n"
        "📸 <b>Rasm yuborish</b> — taom rasmini yuboring\n"
        "📊 /daily — bugungi kaloriya statistikasi\n"
        "📜 /history — so'nggi 10 ta tahlil tarixi\n"
        "🏠 /start — bosh menyuga qaytish\n"
        "❓ /help — yordam\n\n"
        "─────────────────────\n"
        "💡 <b>Maslahat:</b> Rasmlarni aniq va yaxshi yoritilgan holda yuboring!"
    )
    await callback.message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=back_keyboard(),
    )
    await callback.answer()


# ─────────────────────────────────────────────
# 🚀 BOT ISHGA TUSHIRISH
# ─────────────────────────────────────────────

async def on_startup(bot: Bot) -> None:
    """Bot ishga tushganda bajariladigan amallar."""
    logger.info("🚀 Bot ishga tushmoqda...")
    init_database()
    me = await bot.get_me()
    logger.info(f"✅ Bot muvaffaqiyatli ulandi: @{me.username} (ID: {me.id})")
    logger.info("📡 Xabarlar kutilmoqda...")


async def on_shutdown(bot: Bot) -> None:
    """Bot to'xtaganda bajariladigan amallar."""
    logger.info("🛑 Bot to'xtatilmoqda...")
    await bot.session.close()
    logger.info("👋 Xayr!")


async def main() -> None:
    """Asosiy funksiya — bot va dispatcher ni yaratish."""

    # Tokenlarni tekshirish
    if not BOT_TOKEN:
        logger.critical("❌ BOT_TOKEN o'rnatilmagan! .env faylini tekshiring.")
        return
    if not GEMINI_API_KEY:
        logger.critical("❌ GEMINI_API_KEY o'rnatilmagan! .env faylini tekshiring.")
        return

    # Bot yaratish
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Dispatcher va FSM storage
    dp = Dispatcher(storage=MemoryStorage())

    # Startup / shutdown hook larni ro'yxatdan o'tkazish
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Router ni qo'shish
    dp.include_router(router)

    # Polling ishga tushirish (production uchun webhook ham ishlaydi)
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,  # Eski xabarlarni o'tkazib yuborish
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard orqali to'xtatildi.")
    except Exception as e:
        logger.critical(f"💥 Kritik xato: {e}", exc_info=True)