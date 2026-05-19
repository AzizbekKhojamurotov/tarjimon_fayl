# 📄 DOCX Translation Telegram Bot

A production-ready Telegram bot built with **aiogram 3.x** that translates Microsoft Word (`.docx`) documents between Uzbek 🇺🇿, Russian 🇷🇺, and English 🇬🇧 — preserving all original fonts, styles, and formatting.

---

## Project Structure

```
docx_translate_bot/
├── bot.py              — Entry point: creates Bot + Dispatcher, starts polling
├── handlers.py         — All aiogram message & callback handlers (FSM logic)
├── states.py           — FSM state group (TranslationFSM)
├── keyboards.py        — Inline keyboard builder
├── translator_core.py  — Core DOCX translation logic (adapted from notebook)
├── requirements.txt    — Python dependencies
├── .env.example        — Environment variable template
└── temp_files/         — Auto-created; holds in-flight .docx files (auto-cleaned)
```

---

## Quick Start

### 1. Clone / copy the project

```bash
cd docx_translate_bot
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your bot token

```bash
cp .env.example .env
# Open .env and replace  your_telegram_bot_token_here  with the token from @BotFather
```

### 5. Run

```bash
python bot.py
```

---

## How It Works

```
User sends /start
    └─> Bot greets, asks for a .docx file
        └─> [FSM: waiting_for_file]

User uploads document.docx
    └─> Bot validates extension
    └─> Bot downloads & saves file with unique name  (user_id + timestamp)
    └─> Bot shows Inline Keyboard: 🇺🇿 Uzbek | 🇷🇺 Russian | 🇬🇧 English
        └─> [FSM: waiting_for_language]

User taps a language button
    └─> Bot notifies "Translating…"
        └─> [FSM: processing]
    └─> asyncio.to_thread(translate_docx_file)   ← non-blocking!
        ├─ detect_language() on first non-empty paragraph
        ├─ if source == target → SameLanguageError → user informed, no API call
        └─ translate_document() → write_text_to_runs() preserves formatting
    └─> Bot sends translated file back
    └─> Temp files deleted immediately (both input & output)
        └─> [FSM: cleared]
```

---

## Core Logic Notes

| Concern | Implementation |
|---|---|
| Language detection | Counts Cyrillic / Latin / Uzbek-apostrophe chars (from notebook) |
| Same-language optimisation | Raises `SameLanguageError` before any API call |
| Formatting preservation | `write_text_to_runs()` distributes translated text across original runs |
| Nested tables | `iter_paragraphs_in_cell()` recurses into tables-within-cells |
| Headers / footers | `translate_document()` iterates `doc.sections` |
| Non-blocking execution | `asyncio.to_thread()` wraps all synchronous code |
| Privacy | Temp files deleted in `finally` block — even on error |
| Error handling | `try/except` around download, translation, and file I/O |

---

## Environment Variables

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from [@BotFather](https://t.me/BotFather) |

---

## Adding More Languages

1. Add the ISO code + label to `SUPPORTED_LANGS` in `translator_core.py`.
2. Add a new `InlineKeyboardButton` in `keyboards.py`.

`deep-translator`'s `GoogleTranslator` supports all languages that Google Translate supports.
