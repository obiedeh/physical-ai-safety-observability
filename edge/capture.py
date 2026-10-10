"""Per-camera capture sessions: decode at native rate, keep the latest JPEG.

One ``CameraSession`` thread per enabled camera. It decodes the stream with
PyAV, JPEG-encodes every frame (downscaled to ``display_max_width``) and
publishes it to a latest-frame slot. Two independent consumers read the slot:

* the MJPEG/snapshot HTTP routes, which push frames to the browser as fast as
  they arrive (the video loop), and
* the inference loop, which samples the latest frame on its own cadence.

The model server is never in the video path, so stopping it cannot stall the
Live page. Errors are redacted before they are stored or logged.
"""
from __future__ import annotations

import io
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw

from edge.redaction import REDACTOR, mask_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameRecord:
    jpeg: bytes
    width: int
    height: int
    seq: int
    monotonic: float
    wall_ms: int
    source_width: int = 0
    source_height: int = 0


@dataclass
class SessionStats:
    state: str = "starting"  # starting | connecting | streaming | reconnecting | error | stopped
    frames_decoded: int = 0
    frames_published: int = 0
    frames_dropped: int = 0  # decoded but not encoded because the encoder fell behind
    decode_errors: int = 0
    reconnects: int = 0
    fps: float = 0.0
    codec: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    source_fps: float | None = None
    connected_at: float | None = None
    last_frame_at: float | None = None
    last_error: str | None = None
    history: deque[float] = field(default_factory=lambda: deque(maxlen=120))

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        return {
            "state": self.state,
            "frames_decoded": self.frames_decoded,
            "frames_published": self.frames_published,
            "frames_dropped": self.frames_dropped,
            "decode_errors": self.decode_errors,
            "reconnects": self.reconnects,
            "fps": round(self.fps, 2),
            "codec": self.codec,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "source_fps": round(self.source_fps, 2) if self.source_fps else None,
            "uptime_s": round(now - self.connected_at, 1) if self.connected_at else None,
            "last_frame_age_s": round(now - self.last_frame_at, 2) if self.last_frame_at else None,
            "last_error": self.last_error,
        }


class LatestFrame:
    """Thread-safe single-slot holder with wait-for-newer support."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: FrameRecord | None = None

    @property
    def latest(self) -> FrameRecord | None:
        return self._frame

    def publish(self, frame: FrameRecord) -> None:
        with self._cond:
            self._frame = frame
            self._cond.notify_all()

    def wait_newer(self, after_seq: int, timeout: float) -> FrameRecord | None:
        with self._cond:
            if self._frame is not None and self._frame.seq > after_seq:
                return self._frame
            self._cond.wait(timeout)
            if self._frame is not None and self._frame.seq > after_seq:
                return self._frame
            return None


class CameraSession:
    """Base class: holds the slot, stats and lifecycle. Subclasses produce frames."""

    kind = "base"

    def __init__(
        self, camera_id: str, *, display_max_width: int = 1280, jpeg_quality: int = 80
    ) -> None:
        self.camera_id = camera_id
        self.display_max_width = display_max_width
        self.jpeg_quality = jpeg_quality
        self.slot = LatestFrame()
        self.stats = SessionStats()
        self._seq = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_guarded, name=f"camera-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        self.stats.state = "stopped"

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # pragma: no cover - last-resort guard
            self._set_error(exc)
        finally:
            if not self._stop.is_set():
                self.stats.state = "error"
            else:
                self.stats.state = "stopped"

    def _run(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    # ── frame publishing ──────────────────────────────────────────────────────

    def publish_image(
        self, image: Image.Image, *, source_size: tuple[int, int] | None = None
    ) -> None:
        src_w, src_h = source_size or image.size
        if image.width > self.display_max_width:
            new_h = max(1, int(image.height * self.display_max_width / image.width))
            image = image.resize((self.display_max_width, new_h))
        if image.mode != "RGB":
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=self.jpeg_quality)
        self.publish_jpeg(buf.getvalue(), image.width, image.height, source_size=(src_w, src_h))

    def publish_jpeg(
        self, jpeg: bytes, width: int, height: int, *, source_size: tuple[int, int] | None = None
    ) -> None:
        now = time.monotonic()
        with self._lock:
            self._seq += 1
            seq = self._seq
            stats = self.stats
            stats.frames_published += 1
            stats.last_frame_at = time.time()
            stats.history.append(now)
            if len(stats.history) >= 2:
                span = stats.history[-1] - stats.history[0]
                stats.fps = (len(stats.history) - 1) / span if span > 0 else 0.0
            if stats.state in {"starting", "connecting", "reconnecting"}:
                stats.state = "streaming"
                stats.connected_at = stats.connected_at or time.time()
        src_w, src_h = source_size or (width, height)
        self.slot.publish(
            FrameRecord(
                jpeg=jpeg, width=width, height=height, seq=seq, monotonic=now,
                wall_ms=int(time.time() * 1000), source_width=src_w, source_height=src_h,
            )
        )

    def _set_error(self, exc: BaseException | str) -> None:
        message = REDACTOR.redact(str(exc)) or exc.__class__.__name__
        self.stats.last_error = message
        self.stats.state = "error"
        logger.warning("camera %s: %s", self.camera_id, message)

    def status(self) -> dict[str, Any]:
        data = self.stats.to_dict()
        data["camera_id"] = self.camera_id
        data["kind"] = self.kind
        latest = self.slot.latest
        data["frame"] = (
            {"width": latest.width, "height": latest.height, "seq": latest.seq}
            if latest else None
        )
        return data


class StreamCameraSession(CameraSession):
    """RTSP / HTTP-MJPEG camera decoded with PyAV, with reconnect."""

    kind = "stream"

    def __init__(
        self,
        camera_id: str,
        url: str,
        *,
        rtsp_transport: str = "tcp",
        display_max_width: int = 1280,
        jpeg_quality: int = 80,
        open_timeout_s: float = 10.0,
        reconnect_backoff_s: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 20.0),
    ) -> None:
        super().__init__(camera_id, display_max_width=display_max_width, jpeg_quality=jpeg_quality)
        self._url = url
        self._rtsp_transport = rtsp_transport
        self._open_timeout_s = open_timeout_s
        self._backoff = reconnect_backoff_s
        self.masked_url = mask_url(url)

    def _run(self) -> None:
        import av

        attempt = 0
        while not self._stop.is_set():
            self.stats.state = "connecting" if attempt == 0 else "reconnecting"
            options: dict[str, str] = {}
            if self._url.startswith("rtsp"):
                options = {
                    "rtsp_transport": self._rtsp_transport or "tcp",
                    "stimeout": str(int(self._open_timeout_s * 1_000_000)),
                }
            try:
                container = av.open(self._url, options=options, timeout=self._open_timeout_s)
            except Exception as exc:
                self._set_error(exc)
                if self._sleep_backoff(attempt):
                    return
                attempt += 1
                continue
            try:
                self._decode_loop(container)
                if self._stop.is_set():
                    return
                self._set_error("stream ended; reconnecting")
            except Exception as exc:
                if self._stop.is_set():
                    return
                self.stats.decode_errors += 1
                self._set_error(exc)
            finally:
                try:
                    container.close()
                except Exception:
                    pass
            self.stats.reconnects += 1
            if self._sleep_backoff(attempt):
                return
            attempt += 1

    def _sleep_backoff(self, attempt: int) -> bool:
        """Sleep the backoff for ``attempt``; return True if stop was requested."""
        delay = self._backoff[min(attempt, len(self._backoff) - 1)]
        return self._stop.wait(delay)

    def _decode_loop(self, container: Any) -> None:
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            raise RuntimeError("no video stream in feed")
        stream.thread_type = "AUTO"
        self.stats.codec = stream.codec_context.name
        self.stats.source_width = stream.codec_context.width or None
        self.stats.source_height = stream.codec_context.height or None
        self.stats.source_fps = float(stream.average_rate) if stream.average_rate else None
        self.stats.connected_at = time.time()
        self.stats.last_error = None
        frame_interval = 1.0 / (self.stats.source_fps or 30.0)
        last_encode = 0.0
        for frame in container.decode(video=0):
            if self._stop.is_set():
                return
            self.stats.frames_decoded += 1
            now = time.monotonic()
            # If the encoder cannot keep up with the camera we drop frames rather
            # than build a growing backlog; drops are counted and reported.
            if self.stats.frames_published and (now - last_encode) < frame_interval * 0.5:
                self.stats.frames_dropped += 1
                continue
            image = frame.to_image()
            self.publish_image(image, source_size=(frame.width, frame.height))
            last_encode = now


class PushCameraSession(CameraSession):
    """Frames are pushed from elsewhere (browser webcam via POST /stream/{id}/push)."""

    kind = "push"

    def start(self) -> None:
        self.stats.state = "connecting"
        self._stop.clear()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.stats.state = "stopped"

    @property
    def running(self) -> bool:
        return not self._stop.is_set()

    def push_image(self, image: Image.Image) -> None:
        if self._stop.is_set():
            return
        self.stats.frames_decoded += 1
        self.publish_image(image)

    def push_jpeg(self, jpeg: bytes) -> None:
        if self._stop.is_set():
            return
        image = Image.open(io.BytesIO(jpeg))
        image.load()
        self.push_image(image)


class SyntheticCameraSession(CameraSession):
    """Generated test pattern, clearly labelled, for demos and tests."""

    kind = "synthetic"

    def __init__(
        self, camera_id: str, *, fps: float = 8.0, size: tuple[int, int] = (640, 360), **kw: Any
    ) -> None:
        super().__init__(camera_id, **kw)
        self._fps = fps
        self._size = size

    def _run(self) -> None:
        self.stats.codec = "synthetic"
        self.stats.source_width, self.stats.source_height = self._size
        self.stats.source_fps = self._fps
        interval = 1.0 / max(self._fps, 0.5)
        tick = 0
        while not self._stop.is_set():
            self.publish_image(self._render(tick))
            tick += 1
            if self._stop.wait(interval):
                return

    def _render(self, tick: int) -> Image.Image:
        w, h = self._size
        img = Image.new("RGB", (w, h), (12, 18, 28))
        draw = ImageDraw.Draw(img)
        for x in range(0, w, 64):
            draw.line([(x, 0), (x, h)], fill=(22, 34, 50))
        for y in range(0, h, 64):
            draw.line([(0, y), (w, y)], fill=(22, 34, 50))
        # A moving block so motion is visible and detections can be exercised.
        bx = int((tick * 7) % (w + 120)) - 60
        by = h // 2 + int(40 * ((tick // 20) % 2 * 2 - 1))
        draw.rectangle([(bx, by - 20), (bx + 60, by + 20)], fill=(0, 190, 100))
        draw.text((12, 12), f"SYNTHETIC FEED  {self.camera_id}", fill=(0, 220, 90))
        draw.text((12, h - 24), time.strftime("%H:%M:%S UTC", time.gmtime()), fill=(120, 130, 160))
        return img
