from functools import lru_cache
from typing import Literal

from pydantic import RedisDsn, AnyHttpUrl, SecretStr, Field
from pydantic_settings import BaseSettings

class CelerySettings(BaseSettings):
    celery_broker_url: RedisDsn
    celery_result_backend: RedisDsn
    celery_visibility_timeout: int = Field(default=120, ge=30)


class S3Settings(BaseSettings):
    s3_endpoint: AnyHttpUrl
    s3_access_key: str
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"

    s3_bucket: str = "hh-lake"
    s3_input_key: str = "it_vacancies_2024.csv"
    s3_output_prefix: str = "results/"
    s3_intermediate_prefix: str = "intermediate/"


class Settings(BaseSettings):
    chunk_size: int = Field(default=1000, ge=1)
    max_in_flight: int = Field(default=2, ge=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    return Settings()

@lru_cache(maxsize=None)
def get_celery_settings() -> CelerySettings:
    return CelerySettings()

@lru_cache(maxsize=None)
def get_s3_settings() -> S3Settings:
    return S3Settings()