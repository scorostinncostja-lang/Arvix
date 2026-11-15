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


# --- Клавиатуры для напоминаний о задачах ---


def reminder_t_minus_5_keyboard(task_id: str) -> InlineKeyboardMarkup:
    """Кнопки для напоминания за 5 минут: [Начать сейчас] [+15 мин] [Не смогу]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="▶️ Начать сейчас", callback_data=f"task_start:{task_id}"),
                InlineKeyboardButton(text="⏳ +15 мин", callback_data=f"task_defer:{task_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Не смогу", callback_data=f"task_fail:{task_id}"),
            ],
        ]
    )


def completion_check_keyboard(task_id: str, proof: str) -> InlineKeyboardMarkup:
    """Кнопки для проверки выполнения: [✅ Да] [⚠️ Частично] [❌ Нет]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"task_done:{task_id}:{proof}"),
                InlineKeyboardButton(text="⚠️ Частично", callback_data=f"task_partial:{task_id}"),
            ],
            [
                InlineKeyboardButton(text="❌ Нет", callback_data=f"task_fail:{task_id}"),
            ],
        ]
    )

