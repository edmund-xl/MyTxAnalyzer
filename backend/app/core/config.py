from functools import lru_cache
from pathlib import Path
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "On-chain RCA Workbench API"
    environment: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite+pysqlite:///./rca_workbench.db"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "REPLACE_ME_MINIO_SECRET_KEY"
    minio_bucket: str = "rca-artifacts"
    object_store_mode: str = "local"
    local_artifact_root: str = "./.artifacts"
    temporal_address: str = "localhost:7233"
    workflow_mode: str = "inline"
    txanalyzer_root: str = "/opt/txanalyzer"
    txanalyzer_python: str = sys.executable
    txanalyzer_timeout_seconds: int = 120
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3100",
        "http://127.0.0.1:3100"
    ]
    network_config_path: str = "docs/spec/onchain_rca_workbench_spec_v1/config/network_config.example.yaml"
    report_template_zh_path: str = "docs/spec/onchain_rca_workbench_spec_v1/templates/report_zh.md"
    report_template_en_path: str = "docs/spec/onchain_rca_workbench_spec_v1/templates/report_en.md"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.project_root / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
