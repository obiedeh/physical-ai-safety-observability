"""Pydantic models for UI-driven runtime configuration (cameras, model, inference)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from edge.camera_profiles import STREAM_QUALITIES, CameraConfigError, get_profile
from spatial.zones import Zone


class CameraIn(BaseModel):
    """Create/update payload. ``password`` blank on update keeps the stored one."""

    name: str = Field(min_length=1, max_length=80)
    profile: str = "generic_rtsp"
    host: str = ""
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str = ""
    password: str = ""
    stream_path: str = ""
    stream_quality: str = "main"
    channel: int = Field(default=1, ge=1, le=64)
    rtsp_transport: Literal["tcp", "udp"] = "tcp"
    enabled: bool = True
    location: str | None = None
    # Zones are normalised 0..1 polygons; the worker scales them to the frame.
    zones: list[Zone] = Field(default_factory=list)
    # Rule ids to evaluate for this camera (empty = all rules).
    rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> CameraIn:
        try:
            profile = get_profile(self.profile)
        except CameraConfigError as exc:
            raise ValueError(str(exc)) from exc
        self.profile = profile.model_type
        if self.stream_quality not in STREAM_QUALITIES:
            raise ValueError(f"stream_quality must be one of {STREAM_QUALITIES}")
        self.host = self.host.strip()
        self.stream_path = self.stream_path.strip()
        if profile.requires_host and not self.host:
            raise ValueError(f"host is required for {profile.label} cameras")
        if self.port is None and profile.requires_host:
            self.port = profile.default_port
        return self


class CameraRecord(BaseModel):
    """Camera as returned by the API — never carries the password."""

    camera_id: str
    name: str
    profile: str
    host: str = ""
    port: int | None = None
    username: str = ""
    has_password: bool = False
    stream_path: str = ""
    effective_stream_path: str = ""
    stream_quality: str = "main"
    channel: int = 1
    rtsp_transport: str = "tcp"
    enabled: bool = True
    location: str | None = None
    zones: list[Zone] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    masked_url: str = ""
    created_at: str | None = None
    updated_at: str | None = None


ModelBackend = Literal["cosmos-reason2", "openai-compatible", "mock"]


class ModelSettings(BaseModel):
    backend: ModelBackend = "mock"
    endpoint: str = "http://127.0.0.1:8000/v1"
    model: str = "nvidia/cosmos-reason2-2b"
    api_key: str = ""           # write-only; stored encrypted
    has_api_key: bool = False   # read-only echo
    think: bool = False
    json_schema: bool = False
    max_tokens: int = Field(default=512, ge=32, le=8192)
    timeout_s: float = Field(default=60.0, ge=5, le=900)
    # Whether the server at ``endpoint`` was started with --reasoning-parser.
    # vLLM 0.14 ignores response_format json_schema in that configuration, so
    # constrained runs are refused unless this is False. Set automatically when
    # the app launches the server; verified by a live probe before each run.
    reasoning_parser: bool | None = None
    label: str = ""

    def normalized_endpoint(self) -> str:
        ep = self.endpoint.strip().rstrip("/")
        if ep and not ep.endswith("/v1"):
            ep += "/v1"
        return ep

    @model_validator(mode="after")
    def _constrained_requires_no_reasoning_parser(self) -> ModelSettings:
        if self.json_schema and self.reasoning_parser is True:
            raise ValueError(
                "json_schema (constrained decoding) cannot be enabled against a server started "
                "with --reasoning-parser: vLLM 0.14 silently ignores the schema. Start the "
                "no-reasoning container or disable json_schema."
            )
        return self


class InferenceSettings(BaseModel):
    interval_ms: int = Field(default=2000, ge=100, le=60000)
    width: int = Field(default=640, ge=160, le=1920)
    height: int = Field(default=360, ge=120, le=1080)
    jpeg_quality: int = Field(default=80, ge=40, le=95)
    display_max_width: int = Field(default=1280, ge=320, le=3840)
    post_batch: bool = True
    post_feedback: bool = True


def camera_payload_public(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip secret fields from a stored camera payload."""
    return {k: v for k, v in payload.items() if k not in {"password_enc"}}
