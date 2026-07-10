from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://ands:ands@localhost:5432/ands"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "ands-packages"
    s3_access_key: str = "andsminio"
    s3_secret_key: str = "andsminio-secret"
    s3_region: str = "us-east-1"
    s3_enabled: bool = True
    cors_origins: str = "http://localhost:3000"
    cors_allow_vercel_previews: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    esg_mode: str = "mock"  # mock | test | production

    @field_validator("s3_enabled", "cors_allow_vercel_previews", mode="before")
    @classmethod
    def parse_bool(cls, value):  # noqa: N805
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
