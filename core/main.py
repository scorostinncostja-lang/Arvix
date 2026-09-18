import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.api.routes import onboarding
from core.bot.handlers import register_handlers
from core.bot.instance import bot, dp
from core.bot.middlewares import OwnerOnlyMiddleware
from core.config import settings

dp.update.outer_middleware(OwnerOnlyMiddleware())
register_handlers(dp)


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    yield
    await dp.stop_polling()
    await polling_task


app = FastAPI(title="Arvix", lifespan=lifespan)
app.include_router(onboarding.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "domain": settings.domain}
