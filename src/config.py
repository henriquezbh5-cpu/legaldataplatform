"""Centralized configuration using Pydantic Settings.

Pydantic Settings reads from environment variables and .env files with
type-safe validation, eliminating runtime config errors.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    db: str = "legaldata"
    user: str = "ldp_admin"
    password: str = "ldp_dev_password"

    @computed_field  # type: ignore[misc]
    @property
    def sync_dsn(self) -> str:
        return f"postgresql+psycopg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[misc]
    @property
    def async_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class PgBouncerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PGBOUNCER_", env_file=".env", extra="ignore")

    host: str = "localhost"
    port: int = 6432


class AwsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AWS_", env_file=".env", extra="ignore")

    region: str = "us-east-1"
    access_key_id: str = ""
    secret_access_key: str = ""
    s3_endpoint: str | None = None  # Set for MinIO local

    @property
    def is_local(self) -> bool:
        return self.s3_endpoint is not None and "localhost" in self.s3_endpoint


class S3Buckets(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="S3_", env_file=".env", extra="ignore")

    bronze_bucket: str = "bronze"
    silver_bucket: str = "silver"
    gold_bucket: str = "gold"
    quarantine_bucket: str = "quarantine"


class DataQualitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DQ_", env_file=".env", extra="ignore")

    fail_fast: bool = False
    ge_data_docs_dir: Path = Path("./data_docs")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    env: str = Field(default="development")
    log_level: str = Field(default="INFO")
    project_root: Path = Path(__file__).parent.parent


class Settings:
    """Unified settings facade."""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.postgres = PostgresSettings()
        self.pgbouncer = PgBouncerSettings()
        self.aws = AwsSettings()
        self.s3 = S3Buckets()
        self.dq = DataQualitySettings()


@lru_cache
def get_settings() -> Settings:
    """Cached settings factory — loaded once per process."""
    return Settings()
