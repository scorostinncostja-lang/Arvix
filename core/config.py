from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    owner_id: int
    domain: str = "localhost"
    public_url: str = "https://localhost"

    database_url: str
    redis_url: str

    # LLM провайдеры (OpenAI-compatible API)
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None
    apinet_api_key: str | None = None
    apinet_base_url: str = "https://apinet.cloud/v1"


settings = Settings()  # type: ignore[call-arg]
