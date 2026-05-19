"""
handlers.py — All Telegram update handlers for the translation bot.

FSM flow
--------
/start
  └─> TranslationFSM.waiting_for_file

User uploads .docx
  └─> validate → save → show language keyboard
  └─> TranslationFSM.waiting_for_language

User taps a language button
  └─> notify "processing…"
  └─> TranslationFSM.processing
  └─> asyncio.to_thread(translate_docx_file, …)   ← non-blocking!
  └─> send translated file back
  └─> cleanup temp files
  └─> clear FSM state  (user can /start again)
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
        "👋 <b>Hello!</b> I'm your DOCX translation bot.\n\n"
        "First, please select the <b>source language</b> of your document:",
        reply_markup=language_keyboard(prefix="src")
    )


@router.callback_query(
    TranslationFSM.waiting_for_source_language,
    F.data.startswith("src:"),
)
async def handle_source_language_choice(callback: CallbackQuery, state: FSMContext) -> None:
    source_lang = callback.data.split(":")[1]
    
    if source_lang not in SUPPORTED_LANGS:
        await callback.answer("Unknown language selection. Please try again.", show_alert=True)
        return

    await callback.answer()
    
    # Store source language in state
    await state.update_data(source_lang=source_lang)
    
    lang_label = SUPPORTED_LANGS[source_lang]
    await callback.message.edit_text(
        f"✅ Source language selected: <b>{lang_label}</b>\n\n"
        "Now, please upload your <b>.docx</b> file."
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
            "⚠️ Please send a <b>.docx</b> file (Microsoft Word format).\n"
            "Other formats are not supported yet."
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
            "❌ Sorry, I couldn't download your file. Please try sending it again."
        )
        _safe_remove(input_path)
        return

    # Persist the input path so the language callback can find it
    await state.update_data(input_path=input_path, original_name=doc.file_name)
    await state.set_state(TranslationFSM.waiting_for_target_language)

    await message.answer(
        f"✅ File <b>{doc.file_name}</b> received!\n\n"
        "Now choose the <b>target language</b> for translation:",
        reply_markup=language_keyboard(prefix="tgt"),
    )


# ── Edge case: user sends a non-document while waiting for a file ─────────────
@router.message(TranslationFSM.waiting_for_file)
async def handle_wrong_input_waiting_file(message: Message) -> None:
    await message.answer(
        "📎 Please upload a <b>.docx</b> file to get started.\n"
        "Use /start if you'd like to restart."
    )


# ─────────────────────────────────────────────────────────────────────────────
# User taps a language button (callback query)
# ─────────────────────────────────────────────────────────────────────────────

@router.callback_query(
    TranslationFSM.waiting_for_target_language,
    F.data.startswith("tgt:"),
)
async def handle_language_choice(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    target_lang = callback.data.split(":")[1]   # e.g. "uz"

    if target_lang not in SUPPORTED_LANGS:
        await callback.answer("Unknown language selection. Please try again.", show_alert=True)
        return

    # Acknowledge the button tap immediately (removes "loading" spinner in Telegram)
    await callback.answer()

    lang_label = SUPPORTED_LANGS[target_lang]   # e.g. "Uzbek 🇺🇿"

    # Remove the keyboard from the previous message
    await callback.message.edit_reply_markup(reply_markup=None)

    # Notify user that processing has started
    processing_msg = await callback.message.answer(
        f"⏳ Translating to <b>{lang_label}</b>… This may take a moment, please wait."
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
        # ── Run blocking translation in a thread pool ─────────────────────────
        # asyncio.to_thread wraps the synchronous function so the Telegram event
        # loop stays responsive while potentially large documents are processed.
        await asyncio.to_thread(
            translate_docx_file,
            input_path,
            output_path,
            source_lang,
            target_lang,
        )

        # ── Build a nice output filename ──────────────────────────────────────
        base = os.path.splitext(original_name)[0]
        out_filename = f"{base}_translated_{target_lang}.docx"

        # ── Read the translated file and send it back ─────────────────────────
        with open(output_path, "rb") as fh:
            file_bytes = fh.read()

        await callback.message.answer_document(
            document=BufferedInputFile(file_bytes, filename=out_filename),
            caption=(
                f"✅ <b>Translation complete!</b>\n\n"
                f"  • Source language : <b>{SUPPORTED_LANGS.get(source_lang, source_lang)}</b>\n"
                f"  • Target language : <b>{lang_label}</b>\n\n"
                f"📄 <i>{out_filename}</i>"
            ),
        )

        # Delete the "processing…" status message for a clean chat
        await processing_msg.delete()

    except SameLanguageError as exc:
        source = str(exc)
        await processing_msg.edit_text(
            f"ℹ️ The document is already in <b>{SUPPORTED_LANGS.get(source, source)}</b> — "
            f"no translation needed!\n\n"
            f"Use /start to upload a different file."
        )

    except Exception as exc:
        logger.exception("Translation failed for user %s: %s", callback.from_user.id, exc)
        await processing_msg.edit_text(
            "❌ <b>An error occurred</b> during translation.\n\n"
            "This could be a temporary issue with the translation service. "
            "Please try again in a moment, or use /start to upload a new file."
        )

    finally:
        # ── Always clean up temp files — regardless of success or failure ─────
        _safe_remove(input_path, output_path)
        await state.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────────────

@router.message(TranslationFSM.processing)
async def handle_message_while_processing(message: Message) -> None:
    """Politely ask the user to wait while translation is running."""
    await message.answer(
        "⏳ Still translating your document… please wait a moment!"
    )


@router.message(StateFilter(None))
@router.message(~StateFilter(TranslationFSM))
async def handle_unexpected_message(message: Message, state: FSMContext) -> None:
    """Any message outside a known state — guide the user back to /start."""
    await state.clear()
    await message.answer(
        "👋 Use /start to begin a new translation session."
    )
