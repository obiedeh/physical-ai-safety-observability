import json
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field

from spatial.zones import Zone


class VideoSource(BaseModel):
    camera_id: str
    name: str
    source_uri: str
    source_type: Literal["synthetic", "video_file", "rtsp"] = "synthetic"
    frame_count: int = Field(default=3, ge=1)
    sample_interval_ms: int = Field(default=250, ge=0)
    frame_stride: int = Field(default=30, ge=1)
    zones: list[Zone] = Field(default_factory=list)
    frames: list[dict[str, Any]] = Field(default_factory=list)


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_source(path: str | Path) -> VideoSource:
    return VideoSource.model_validate(load_json(path))
