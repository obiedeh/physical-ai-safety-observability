"""Camera vendor profiles: default ports and main/sub stream paths.

A profile turns ``host + port + credentials + quality`` into a feed URL. The
stream path is auto-filled from the profile and may be overridden per camera
(``stream_path``), which is how UniFi Protect's per-camera token path and odd
firmware variants are handled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

from edge.redaction import mask_url


class CameraConfigError(ValueError):
    """Raised when a camera configuration is incomplete or unsupported."""


@dataclass(frozen=True)
class CameraProfile:
    model_type: str
    label: str
    default_port: int
    main_path: str
    sub_path: str
    protocol: str = "rtsp"
    requires_auth: bool = True
    requires_host: bool = True
    notes: str = ""

    def stream_path(self, quality: str = "main", channel: int = 1) -> str:
        template = self.main_path if quality != "sub" else self.sub_path
        return template.format(channel=channel, channel2=f"{channel:02d}")

    def build_url(
        self,
        host: str,
        username: str | None,
        password: str | None,
        port: int | None = None,
        *,
        channel: int = 1,
        quality: str = "main",
        path: str | None = None,
    ) -> str:
        if not self.requires_host:
            raise CameraConfigError(f"{self.label} cameras have no stream URL.")
        host = (host or "").strip()
        if not host:
            raise CameraConfigError("Camera host is required.")
        resolved_port = port or self.default_port
        feed_path = (path or "").strip() or self.stream_path(quality, channel)
        if not feed_path.startswith("/"):
            feed_path = "/" + feed_path
        auth = ""
        if username or password:
            auth = f"{quote(username or '', safe='')}:{quote(password or '', safe='')}@"
        elif self.requires_auth:
            raise CameraConfigError(f"{self.label} requires a username and password.")
        return f"{self.protocol}://{auth}{host}:{resolved_port}{feed_path}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["example_main_path"] = self.stream_path("main")
        data["example_sub_path"] = self.stream_path("sub")
        return data


CAMERA_PROFILES: dict[str, CameraProfile] = {
    "tapo": CameraProfile(
        "tapo", "TP-Link Tapo", 554, "/stream1", "/stream2",
        notes="Create a camera account in the Tapo app (Advanced Settings > Camera Account).",
    ),
    "hikvision": CameraProfile(
        "hikvision", "Hikvision", 554,
        "/Streaming/Channels/{channel}01", "/Streaming/Channels/{channel}02",
    ),
    "dahua": CameraProfile(
        "dahua", "Dahua", 554,
        "/cam/realmonitor?channel={channel}&subtype=0",
        "/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "amcrest": CameraProfile(
        "amcrest", "Amcrest", 554,
        "/cam/realmonitor?channel={channel}&subtype=0",
        "/cam/realmonitor?channel={channel}&subtype=1",
    ),
    "axis": CameraProfile(
        "axis", "Axis", 554,
        "/axis-media/media.amp", "/axis-media/media.amp?resolution=640x480",
    ),
    "reolink": CameraProfile(
        "reolink", "Reolink", 554,
        "/h264Preview_{channel2}_main", "/h264Preview_{channel2}_sub",
    ),
    "unifi_protect": CameraProfile(
        "unifi_protect", "UniFi Protect", 7447, "/{channel}", "/{channel}",
        requires_auth=False,
        notes="Paste the RTSPS/RTSP stream token from Protect as the stream path.",
    ),
    "generic_rtsp": CameraProfile(
        "generic_rtsp", "Generic RTSP", 554, "/stream", "/stream",
        requires_auth=False, notes="Edit the stream path to match the camera.",
    ),
    "http_mjpeg": CameraProfile(
        "http_mjpeg", "HTTP MJPEG", 80, "/video", "/video",
        protocol="http", requires_auth=False,
    ),
    "browser_webrtc": CameraProfile(
        "browser_webrtc", "Browser webcam (WebRTC)", 0, "", "",
        requires_auth=False, requires_host=False,
        notes="The operator's browser pushes webcam frames to this camera slot.",
    ),
    "synthetic": CameraProfile(
        "synthetic", "Synthetic test feed", 0, "", "",
        requires_auth=False, requires_host=False,
        notes="Generated frames for demos and tests. Labelled synthetic everywhere.",
    ),
}

STREAM_QUALITIES = ("main", "sub")


def list_profiles() -> list[dict[str, Any]]:
    return [p.to_dict() for p in CAMERA_PROFILES.values()]


def get_profile(model_type: str) -> CameraProfile:
    key = (model_type or "").strip().lower()
    if key not in CAMERA_PROFILES:
        supported = ", ".join(sorted(CAMERA_PROFILES))
        raise CameraConfigError(
            f"Unsupported camera model_type '{model_type}'. Supported: {supported}"
        )
    return CAMERA_PROFILES[key]




__all__ = ["CAMERA_PROFILES", "STREAM_QUALITIES", "CameraConfigError", "CameraProfile",
           "get_profile", "list_profiles", "mask_url"]
