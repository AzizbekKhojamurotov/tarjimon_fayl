"""
bot.py — Entry point for the DOCX Translation Telegram Bot.

Start with:
    python bot.py

Requires BOT_TOKEN in environment (or .env file via python-dotenv).
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from handlers import router
# 8470959300:AAEogSWL4TZCbQs0GR5e-qz3NS9laFSVXXM
# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()  # Read BOT_TOKEN (and any other vars) from .env if present


async def main() -> None:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("BOT_TOKEN environment variable is not set!")

    # MemoryStorage is fine for a single-process bot.
    # Swap for RedisStorage for multi-worker / persistent FSM.
    storage = MemoryStorage()

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)
    dp.include_router(router)



    from aiohttp import web

    async def handle(request):
        return web.Response(text="Bot is running!")

    # main() funksiyangiz ichiga, start_polling dan oldin qo'shasiz:
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000)))
    asyncio.create_task(site.start())




    logger.info("Bot is starting — polling for updates…")
    # Drop any queued updates from while the bot was offline
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
