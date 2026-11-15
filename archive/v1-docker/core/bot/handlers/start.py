from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from core.bot.keyboards import onboarding_keyboard
from core.bot.templates import ONBOARDING_INVITE, welcome_back
from core.db.models import Profile
from core.db.session import async_session_factory

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    async with async_session_factory() as session:
        profile = await session.get(Profile, 1)

    if profile is None or profile.onboarding_stage == "core":
        await message.answer(ONBOARDING_INVITE, reply_markup=onboarding_keyboard())
    else:
        await message.answer(welcome_back())
