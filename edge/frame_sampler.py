from collections.abc import Iterator
from datetime import UTC, datetime
from time import sleep
from typing import Any

from edge.source_loader import VideoSource
from evidence.hashing import hash_bytes, hash_text


def sample_frames(source: VideoSource) -> Iterator[dict[str, Any]]:
    if source.frames or source.source_type == "synthetic":
        yield from sample_synthetic_frames(source)
        return
    yield from sample_opencv_frames(source)


def sample_synthetic_frames(source: VideoSource) -> Iterator[dict[str, Any]]:
    frames = source.frames or [{} for _ in range(source.frame_count)]
    for index, frame in enumerate(frames[: source.frame_count], start=1):
        timestamp = datetime.now(UTC)
        context = {
            "frame_id": frame.get("frame_id", f"frame-{index:04d}"),
            "camera_id": source.camera_id,
            "source_uri": source.source_uri,
            "timestamp": timestamp,
            "frame_hash": frame.get(
                "frame_hash",
                hash_text(f"{source.camera_id}:{source.source_uri}:{index}:{timestamp.isoformat()}"),
            ),
            "metadata": frame.get("metadata", {}),
            "detections": frame.get("detections"),
        }
        yield context
        if source.sample_interval_ms:
            sleep(source.sample_interval_ms / 1000)


def sample_opencv_frames(source: VideoSource) -> Iterator[dict[str, Any]]:
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is required for video_file and RTSP sources. "
            "Install with `pip install -e .[opencv]`."
        ) from exc

    capture = cv2.VideoCapture(source.source_uri)
    if not capture.isOpened():
        raise RuntimeError(f"unable to open video source: {source.source_uri}")

    emitted = 0
    frame_index = 0
    try:
        while emitted < source.frame_count:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % source.frame_stride != 0:
                continue
            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            timestamp = datetime.now(UTC)
            frame_bytes = encoded.tobytes()
            emitted += 1
            yield {
                "frame_id": f"frame-{frame_index:08d}",
                "camera_id": source.camera_id,
                "source_uri": source.source_uri,
                "timestamp": timestamp,
                "frame_hash": hash_bytes(frame_bytes),
                "metadata": {
                    "source_type": source.source_type,
                    "frame_index": frame_index,
                    "height": int(frame.shape[0]),
                    "width": int(frame.shape[1]),
                },
                "frame_bytes": frame_bytes,
                "detections": None,
            }
            if source.sample_interval_ms:
                sleep(source.sample_interval_ms / 1000)
    finally:
        capture.release()
