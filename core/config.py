from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    owner_id: int
    domain: str = "localhost"
    public_url: str = "https://localhost"

    database_url: str
    redis_url: str

    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None


settings = Settings()  # type: ignore[call-arg]
