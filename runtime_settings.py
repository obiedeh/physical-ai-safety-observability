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
    queue_depth_warning: int = 5
    inference_timeout_seconds: float = 60.0
    continuous: bool = True
    feedback_interval_seconds: float = Field(default=2.0, gt=0.0)
    clean_feedback_terminal: bool = True


class RuntimeSettings(BaseModel):
    app: AppSettings = Field(default_factory=AppSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)


def load_settings(path: str | Path | None = None) -> RuntimeSettings:
    config_path = path or os.getenv("PHYSICAL_AI_CONFIG")
    if not config_path:
        return RuntimeSettings()
    return RuntimeSettings.model_validate(load_json(config_path))
