"""Стадия 1 онбординга (05-BOT-TWA.md §2) — минимальная HTML-страница без
React/Vite-тулчейна: тот появится в шаге 0.7 вместе с остальным TWA.
Здесь важно, чтобы поток /start -> форма -> профиль работал, а не как это
нарисовано."""

from datetime import date, time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.api.telegram_auth import InitDataError, verify_init_data
from core.bot.instance import bot
from core.bot.templates import onboarding_confirmation
from core.config import settings
from core.db.models import Goal, Profile
from core.db.session import async_session_factory

router = APIRouter()

_ONBOARDING_HTML = (Path(__file__).parent.parent / "templates" / "onboarding.html").read_text()


@router.get("/app/onboarding", response_class=HTMLResponse)
async def onboarding_page() -> HTMLResponse:
    return HTMLResponse(_ONBOARDING_HTML)


class OnboardingCoreIn(BaseModel):
    name: str = Field(min_length=1)
    birth_date: date
    city: str = Field(min_length=1)
    bedtime_target: time
    wake_target: time
    busy_weekdays: list[int] = Field(default_factory=list)
    goal_title: str = Field(min_length=1)
    goal_why: str = Field(min_length=1)


def _require_owner(init_data: str) -> dict:
    try:
        data = verify_init_data(init_data, settings.bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = data.get("user") or {}
    if user.get("id") != settings.owner_id:
        raise HTTPException(status_code=403, detail="not owner")
    return data


@router.post("/api/onboarding/core")
async def onboarding_core(
    payload: OnboardingCoreIn,
    x_telegram_init_data: str = Header(...),
) -> dict[str, str]:
    _require_owner(x_telegram_init_data)

    async with async_session_factory() as session:
        profile = await session.get(Profile, 1)
        if profile is None:
            profile = Profile(id=1)
            session.add(profile)

        profile.name = payload.name
        profile.birth_date = payload.birth_date
        profile.city = payload.city
        profile.bedtime_target = payload.bedtime_target
        profile.wake_target = payload.wake_target
        profile.onboarding_stage = "interview"
        profile.extra = {**(profile.extra or {}), "busy_weekdays": payload.busy_weekdays}

        goal = Goal(title=payload.goal_title, kind="main", why=payload.goal_why)
        session.add(goal)

        await session.commit()

    await bot.send_message(settings.owner_id, onboarding_confirmation(payload.goal_title))
    return {"status": "ok"}
