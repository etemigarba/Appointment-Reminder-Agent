"""Application configuration loaded from environment variables (prefix APP_)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./app.db"
    dispatch_interval_seconds: int = 60
    reminder_horizon_hours: int = 168


@lru_cache
def get_settings() -> Settings:
    return Settings()
