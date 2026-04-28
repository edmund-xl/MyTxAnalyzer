from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://rca:REPLACE_ME_POSTGRES_PASSWORD@localhost:5432/rca_workbench"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "REPLACE_ME_MINIO_ROOT_PASSWORD"
    minio_bucket: str = "rca-artifacts"
    temporal_address: str = "localhost:7233"
    txanalyzer_root: str = "/opt/txanalyzer"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
