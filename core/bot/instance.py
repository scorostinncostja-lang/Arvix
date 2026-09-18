"""Единственный экземпляр Bot/Dispatcher на процесс — общий для aiogram-поллинга
и для API-хендлеров, которым нужно послать сообщение (например, после онбординга)."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from core.config import settings

bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
