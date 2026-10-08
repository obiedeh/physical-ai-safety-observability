import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from edge.source_loader import load_json


class AppSettings(BaseModel):
    database_path: str = "data/observability.sqlite3"
    incident_window_seconds: int = Field(default=900, ge=1)
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    log_level: str = "INFO"
    log_format: Literal["json"] = "json"


class WorkerSettings(BaseModel):
    backend: str = "http://127.0.0.1:8080"
    adapter: Literal["mock", "openai-compatible", "cosmos-reason2"] = "mock"
    adapter_endpoint: str = "http://127.0.0.1:8000/v1"
    model: str = "nvidia/cosmos-reason2-2b"
    api_key_env: str = "COSMOS_API_KEY"
    post_events: bool = True
    post_batch: bool = False
    max_tokens: int = 4096
    think: bool = True
    json_schema: bool = False
    queue_depth_warning: int = 5
    inference_timeout_seconds: float = 60.0
    continuous: bool = True
    feedback_interval_seconds: float = Field(default=2.0, gt=0.0)
    clean_feedback_terminal: bool = True


class UploadSettings(BaseModel):
    """Limits for video files uploaded from the Cameras page.

    ``max_bytes`` defaults to 2 GiB and can be overridden with
    ``PHYSICAL_AI_UPLOAD_MAX_BYTES``. Files are stored next to the SQLite
    database unless ``dir`` (or ``PHYSICAL_AI_UPLOAD_DIR``) points elsewhere.
    """

    max_bytes: int = Field(default=2 * 1024**3, ge=1024)
    dir: str | None = None


class RuntimeSettings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    uploads: UploadSettings = Field(default_factory=UploadSettings)


_UPLOAD_ENV_KEYS = {"PHYSICAL_AI_UPLOAD_MAX_BYTES": "max_bytes", "PHYSICAL_AI_UPLOAD_DIR": "dir"}


def load_settings(path: str | Path | None = None) -> RuntimeSettings:
    config_path = path or os.getenv("PHYSICAL_AI_CONFIG")
    raw = load_json(config_path) if config_path else {}
    uploads = dict(raw.get("uploads") or {})
    for env_key, field in _UPLOAD_ENV_KEYS.items():
        value = os.getenv(env_key)
        if value:
            uploads[field] = value
    raw["uploads"] = uploads
    return RuntimeSettings.model_validate(raw)
