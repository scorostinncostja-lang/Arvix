from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from core.bot.templates import ONBOARDING_BUTTON_TEXT
from core.config import settings


def onboarding_keyboard() -> InlineKeyboardMarkup:
    url = f"{settings.public_url}/app/onboarding"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ONBOARDING_BUTTON_TEXT, web_app=WebAppInfo(url=url))]
        ]
    )
