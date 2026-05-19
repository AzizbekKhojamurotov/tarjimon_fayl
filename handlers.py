"""
handlers.py — All Telegram update handlers for the translation bot.

FSM flow (Optimized)
--------------------
/start yoki kutilmagan xabar
  └─> TranslationFSM.waiting_for_source_language  <───┐
                                                      │
User selects source language                          │ (Bot avtomat shu yerga qaytadi)
  └─> TranslationFSM.waiting_for_file                 │
                                                      │
User uploads .docx                                    │
  └─> validate → save → show target language keyboard │
  └─> TranslationFSM.waiting_for_target_language      │
                                                      │
User taps a target language button                    │
  └─> notify "processing…"                            │
  └─> TranslationFSM.processing                       │
  └─> asyncio.to_thread(translate_docx_file, …)       │
  └─> send translated file back                       │
  └─> cleanup temp files                              │
  └─> reset state to waiting_for_source_language ─────┘
"""

import asyncio
import logging
import os
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Document,
    Message,
)

from keyboards import language_keyboard
from states import TranslationFSM
from translator_core import (
    SUPPORTED_LANGS,
    SameLanguageError,
    translate_docx_file,
)

logger = logging.getLogger(__name__)
router = Router()

# Directory where temporary files are stored
TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp_files")
os.makedirs(TEMP_DIR, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _temp_path(user_id: int, suffix: str) -> str:
    """Build a unique temp-file path using user_id + timestamp."""
    ts = int(time.time() * 1000)
    return os.path.join(TEMP_DIR, f"{user_id}_{ts}{suffix}")


def _safe_remove(*paths: str) -> None:
    """Delete files silently — never crash on cleanup failure."""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
                logger.debug("Removed temp file: %s", path)
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)


# ─────────────────────────────────────────────────────────────────────────────
# /start — greet and ask for a file
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TranslationFSM.waiting_for_source_language)
    await message.answer(
        "👋 <b>Assalomu alaykum!</b> Men DOCX formatidagi hujjatlarni tarjima qiluvchi botman.\n\n"
        "Tarjima qilishni boshlash uchun, iltimos, hujjatning <b>manba tilini</b> tanlang:",
        reply_markup=language_keyboard(prefix="src")
    )


@router.callback_query(
    TranslationFSM.waiting_for_source_language,
    F.data.startswith("src:"),
)
async def handle_source_language_choice(callback: CallbackQuery, state: FSMContext) -> None:
    source_lang = callback.data.split(":")[1]
    
    if source_lang not in SUPPORTED_LANGS:
        await callback.answer("Noma'lum til tanlandi. Iltimos, qaytadan urinib ko'ring.", show_alert=True)
        return

    await callback.answer()
    
    # Store source language in state
    await state.update_data(source_lang=source_lang)
    
    lang_label = SUPPORTED_LANGS[source_lang]
    await callback.message.edit_text(
        f"✅ Manba tili tanlandi: <b>{lang_label}</b>\n\n"
        "Endi, iltimos, tarjima qilinishi kerak bo'lgan <b>.docx</b> faylingizni yuklang."
    )
    await state.set_state(TranslationFSM.waiting_for_file)


# ─────────────────────────────────────────────────────────────────────────────
# User sends a document while in waiting_for_file state
# ─────────────────────────────────────────────────────────────────────────────

@router.message(
    TranslationFSM.waiting_for_file,
    F.document,
)
async def handle_document_upload(message: Message, state: FSMContext, bot: Bot) -> None:
    doc: Document = message.document

    # ── Validate extension ────────────────────────────────────────────────────
    if not doc.file_name or not doc.file_name.lower().endswith(".docx"):
        await message.answer(
            "⚠️ Iltimos, faqat <b>.docx</b> formatidagi faylni yuboring (Microsoft Word).\n"
            "Boshqa formatlar hozircha qo'llab-quvvatlanmaydi."
        )
        return

    # ── Download and save with a unique name ─────────────────────────────────
    input_path = _temp_path(message.from_user.id, ".docx")
    try:
        file_info = await bot.get_file(doc.file_id)
        await bot.download_file(file_info.file_path, destination=input_path)
    except Exception as exc:
        logger.error("Failed to download file from Telegram: %s", exc)
        await message.answer(
            "❌ Kechirasiz, faylni yuklab olishda xatolik yuz berdi. Iltimos, qaytadan yuboring."
        )
        _safe_remove(input_path)
        return

    # Persist the input path so the language callback can find it
    await state.update_data(input_path=input_path, original_name=doc.file_name)
    await state.set_state(TranslationFSM.waiting_for_target_language)

    await message.answer(
        f"✅ Fayl <b>{doc.file_name}</b> muvaffaqiyatli qabul qilindi!\n\n"
        "Endi hujjat qaysi <b>maqsadli tilga</b> tarjima qilinishini tanlang:",
        reply_markup=language_keyboard(prefix="tgt"),
    )


# ── Edge case: user sends a non-document while waiting for a file ─────────────
@router.message(TranslationFSM.waiting_for_file)
async def handle_wrong_input_waiting_file(message: Message) -> None:
    await message.answer(
        "📎 Jarayonni boshlash uchun <b>.docx</b> faylini yuklang.\n"
        "Agar adashib ketgan bo'lsangiz, /start buyrug'idan foydalanishingiz mumkin."
    )


# ─────────────────────────────────────────────────────────────────────────────
# User taps a language button (callback query)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(
    TranslationFSM.waiting_for_target_language,
    F.data.startswith("tgt:"),
)
async def handle_language_choice(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    target_lang = callback.data.split(":")[1]

    if target_lang not in SUPPORTED_LANGS:
        await callback.answer("Noma'lum til tanlandi. Iltimos, qaytadan urinib ko'ring.", show_alert=True)
        return

    # Acknowledge the button tap immediately
    await callback.answer()

    lang_label = SUPPORTED_LANGS[target_lang]

    # Remove the keyboard from the previous message
    await callback.message.edit_reply_markup(reply_markup=None)

    # Notify user that processing has started
    processing_msg = await callback.message.answer(
        f"⏳ Hujjat <b>{lang_label}</b> tiliga tarjima qilinmoqda… Bu biroz vaqt olishi mumkin(fayl hajmiga nisbatan 5-10 daqiqa), iltimos kuting."
    )

    # Retrieve stored state data
    data = await state.get_data()
    input_path: str = data.get("input_path", "")
    original_name: str = data.get("original_name", "document.docx")
    source_lang: str = data.get("source_lang", "uz")

    # Switch to 'processing' state so stray messages don't interfere
    await state.set_state(TranslationFSM.processing)

    output_path = _temp_path(callback.from_user.id, f"_translated_{target_lang}.docx")

    try:
        # Run blocking translation in a thread pool
        await asyncio.to_thread(
            translate_docx_file,
            input_path,
            output_path,
            source_lang,
            target_lang,
        )

        # Build a nice output filename
        base = os.path.splitext(original_name)[0]
        out_filename = f"{base}_translated_{target_lang}.docx"

        # Read the translated file and send it back
        with open(output_path, "rb") as fh:
            file_bytes = fh.read()

        await callback.message.answer_document(
            document=BufferedInputFile(file_bytes, filename=out_filename),
            caption=(
                f"✅ <b>Tarjima yakunlandi!</b>\n\n"
                f"  • Manba tili : <b>{SUPPORTED_LANGS.get(source_lang, source_lang)}</b>\n"
                f"  • O'girilgan til : <b>{lang_label}</b>\n\n"
                f"📄 <i>{out_filename}</i>\n\n"
                f"📥 <b>Yangi fayl tarjima qilish uchun to'g'ridan-to'g'ri manba tilini tanlang:</b>"
            ),
        )

        # Automatically show the source language keyboard for the NEXT translation
        await callback.message.answer(
            "Yangi hujjatning <b>manba tilini</b> tanlang:",
            reply_markup=language_keyboard(prefix="src")
        )

        # Delete the "processing…" status message
        await processing_msg.delete()

    except SameLanguageError as exc:
        source = str(exc)
        await processing_msg.edit_text(
            f"ℹ️ Hujjat allaqachon <b>{SUPPORTED_LANGS.get(source, source)}</b> tilida — "
            f"tarjima qilish shart emas!\n\n"
            f"Yangi fayl yuborish uchun pastdan manba tilini tanlang:",
            reply_markup=language_keyboard(prefix="src")
        )

    except Exception as exc:
        logger.exception("Translation failed for user %s: %s", callback.from_user.id, exc)
        await processing_msg.edit_text(
            "❌ Tarjima jarayonida <b>xatolik yuz berdi</b>.\n\n"
            "Bu xizmatdagi vaqtinchalik muammo bo'lishi mumkin. Qayta urinish uchun manba tilini tanlang:",
            reply_markup=language_keyboard(prefix="src")
        )

    finally:
        # ── Always clean up temp files ────────────────────────────────────────
        _safe_remove(input_path, output_path)
        
        # Reset state to the very first step instead of completely clearing it
        await state.clear()
        await state.set_state(TranslationFSM.waiting_for_source_language)


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────

@router.message(TranslationFSM.processing)
async def handle_message_while_processing(message: Message) -> None:
    """Politely ask the user to wait while translation is running."""
    await message.answer(
        "⏳ Hujjatingiz hali ham tarjima qilinmoqda… iltimos, biroz kuting!"
    )


@router.message(StateFilter(None))
@router.message(~StateFilter(TranslationFSM))
async def handle_unexpected_message(message: Message, state: FSMContext) -> None:
    """Any message outside a known state — seamlessly guide them to select a source language."""
    await state.clear()
    await state.set_state(TranslationFSM.waiting_for_source_language)
    await message.answer(
        "👋 Yangi faylni tarjima qilishni boshlash uchun pastdagi tugmalardan <b>manba tilini</b> tanlang:",
        reply_markup=language_keyboard(prefix="src")
    )
