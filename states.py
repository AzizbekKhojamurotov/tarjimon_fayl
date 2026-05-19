"""
states.py — Finite State Machine state groups for the translation workflow.
"""

from aiogram.fsm.state import State, StatesGroup


class TranslationFSM(StatesGroup):
    """
    States the user moves through during one translation session:

    waiting_for_source_language
        └─ (user picks source language)
    waiting_for_file
        └─ (user uploads .docx)
    waiting_for_target_language
        └─ (user picks target language)
    processing
        └─ (background translation runs; bot sends result)
    """

    waiting_for_source_language = State()
    waiting_for_file = State()
    waiting_for_target_language = State()
    processing = State()
