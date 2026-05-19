"""
keyboards.py — All Inline Keyboard markup used by the bot.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def language_keyboard(prefix: str) -> InlineKeyboardMarkup:
    """
    Three-button keyboard shown for language selection.
    Callback data includes the prefix and the ISO language code.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇺🇿 Uzbek",   callback_data=f"{prefix}:uz"),
        InlineKeyboardButton(text="🇷🇺 Russian",  callback_data=f"{prefix}:ru"),
        InlineKeyboardButton(text="🇬🇧 English",  callback_data=f"{prefix}:en"),
    )
    return builder.as_markup()
