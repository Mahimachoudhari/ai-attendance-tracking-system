"""
backend/config.py
-----------------
Single source of truth for all runtime configuration.
Loaded once at import; accessed everywhere as `from backend.config import cfg`.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_env:  str = "development"

    # Database
    db_host:     str = "localhost"
    db_port:     int = 5432
    db_name:     str = "attendance_db"
    db_user:     str = "postgres"
    db_password: str = "postgres"
    db_pool_min: int = 2
    db_pool_max: int = 20

    @property
    def db_dsn(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} "
            f"dbname={self.db_name} user={self.db_user} "
            f"password={self.db_password}"
        )

    # Redis
    redis_host:          str = "localhost"
    redis_port:          int = 6379
    redis_db:            int = 0
    redis_password:      str = ""
    redis_embedding_ttl: int = 3600

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_events:      str = "attendance_events"
    kafka_topic_alerts:      str = "security_alerts"

    # AI model
    model_name:           str   = "buffalo_sc"
    gpu_id:               int   = 0
    similarity_threshold: float = 0.45
    min_face_size:        int   = 60
    blur_threshold:       float = 80.0
    max_yaw_degrees:      float = 35.0
    embedding_dim:        int   = 128
    max_faces_per_frame:  int   = 600

    # Camera
    camera_1_url:  str = "demo/entry_gate.mp4"
    camera_2_url:  str = "demo/exit_gate.mp4"
    frame_skip:    int = 3
    jpeg_quality:  int = 70

    # Company
    company_id:   int = 1
    company_code: str = "ACME_IND"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


cfg: Settings = get_settings()