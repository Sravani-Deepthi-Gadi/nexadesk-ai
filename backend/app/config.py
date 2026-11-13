"""Application configuration, loaded from environment variables.

Nothing secret is ever hardcoded. Copy .env.example to .env and fill it in.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"
    llm_max_tokens: int = 1024
    llm_provider: str = "claude"

    # --- Database ---
    database_url: str = "sqlite:///./data/nexadesk.db"

    # --- Agent identity ---
    # The single agent identity used by the concierge in this prototype.
    default_agent_name: str = "nexadesk-concierge"

    # --- Agent loop safety ---
    max_tool_iterations: int = 5

    # --- Auth ---
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60
    #: Optional bootstrap admin. If either is blank, no admin is seeded and
    #: you create one with: python -m scripts.create_admin
    admin_email: str = ""
    admin_password: str = ""

    # --- CORS ---
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
