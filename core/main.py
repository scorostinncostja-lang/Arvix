import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.api.routes import onboarding
from core.bot.handlers import register_handlers
from core.bot.instance import bot, dp
from core.bot.middlewares import OwnerOnlyMiddleware
from core.config import settings
from core.db.session import async_session_factory
from core.scheduler.jobs import scheduler, start_scheduler
from core.scheduler.materialize import seed_default_templates

dp.update.outer_middleware(OwnerOnlyMiddleware())
register_handlers(dp)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_factory() as session:
        await seed_default_templates(session)
        await session.commit()

    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    start_scheduler()
    yield
    scheduler.shutdown(wait=False)
    await dp.stop_polling()
    await polling_task


app = FastAPI(title="Arvix", lifespan=lifespan)
app.include_router(onboarding.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "domain": settings.domain}
