from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class CameraRegistration(BaseModel):
    camera_id: str = Field(min_length=1)
    name: str
    source_uri: str
    location: str | None = None
    profile: Literal["local", "jetson", "edge-cluster", "cloud-hybrid"] = "local"
    metadata: dict = Field(default_factory=dict)


class Camera(CameraRegistration):
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

