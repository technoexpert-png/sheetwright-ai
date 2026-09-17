"""Application settings, read from the environment.

Everything that differs between a laptop, CI, and Fly lives here, so no module
below has to know which one it is running on. Defaults are chosen so that
`docker compose up` works with no .env file at all — a reviewer should be able
to run this without reading configuration docs first.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sheetwright AI"
    environment: str = "development"

    # The one hostname the site should be reachable at, e.g. "sheetwrightai.com".
    # Empty disables the redirect, which is what dev, tests, and the bare
    # *.fly.dev hostname want.
    canonical_host: str = ""

    # Postgres. The default matches docker-compose so local dev needs no setup.
    database_url: str = "postgresql+psycopg://sheetwright:sheetwright@localhost:5432/sheetwright"

    # Signed-cookie secret. Overridden in every real deployment; the default
    # exists only so the dev stack starts.
    secret_key: str = "dev-only-insecure-change-me"
    session_cookie: str = "sw_session"
    session_days: int = 30

    # Anonymous trials get a real (throwaway) org so tenancy has exactly one
    # code path. See db.models.Org.is_trial for why.
    trial_upload_limit: int = 5
    trial_retention_hours: int = 24

    # Uploads. Local filesystem in dev; S3-compatible (Fly Tigris / AWS) in prod.
    storage_backend: str = "local"          # "local" | "s3"
    storage_local_dir: str = "./.uploads"
    # Accept both our own names and the AWS-style ones Fly/Tigris inject, so a
    # provisioned bucket works with no manual re-mapping. boto3 reads
    # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION itself.
    s3_bucket: str | None = Field(
        default=None, validation_alias=AliasChoices("S3_BUCKET", "BUCKET_NAME")
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("S3_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3"),
    )

    max_upload_bytes: int = 10 * 1024 * 1024

    # LLM. Mock by default: the whole stack must be runnable and testable with
    # no API key, which is what makes the repo useful to a stranger.
    llm_provider: str = "mock"              # "mock" | "anthropic"
    anthropic_api_key: str | None = None
    model_mapping: str = "claude-opus-5"    # hard one-shot reasoning, once per upload
    model_chat: str = "claude-sonnet-5"     # cheap and conversational

    # Worker
    worker_poll_seconds: float = 1.0
    worker_max_attempts: int = 3


@lru_cache
def settings() -> Settings:
    return Settings()
