"""Validation and probing for uploaded video files.

An operator can upload an MP4, MOV or MKV from the Cameras page and play it
through the same capture, inference and pack path as a live camera. Files are
stored outside the repository next to the SQLite store. This module checks
the name, the container signature and the configured size limit, and reads
the stream properties (duration, size, frame rate, codec) with PyAV so the
player can run at the file's native rate.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 2 * 1024**3  # 2 GiB
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
}
UPLOAD_SOURCE_KINDS = ("recorded", "generated")
_ISO_BMFF_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")
_MATROSKA_MAGIC = b"\x1a\x45\xdf\xa3"
SNIFF_BYTES = 16


class UploadError(ValueError):
    """An upload was refused; ``status_code`` is the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float | None
    width: int | None
    height: int | None
    fps: float | None
    codec: str | None
    frames: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def safe_filename(name: str) -> str:
    """Keep only the base name, replace odd characters, keep the extension."""
    base = Path(name or "").name
    stem, ext = Path(base).stem, Path(base).suffix.lower()
    if not ext and base.startswith(".") and base.count(".") == 1:
        stem, ext = "", base.lower()  # ".mkv" is an extension with no name, not a dotfile
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "video"
    return f"{stem[:80]}{ext}"


def content_type_for(filename: str) -> str:
    """Return the media type for an allowed extension or raise ``UploadError`` (415)."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadError(f"Unsupported file type '{ext or 'none'}'. Allowed: {allowed}.", 415)
    return ALLOWED_EXTENSIONS[ext]


def check_signature(head: bytes, filename: str) -> None:
    """Refuse a file whose first bytes do not match its extension."""
    ext = Path(filename).suffix.lower()
    if len(head) < 12:
        raise UploadError("The file is too small to be a video.", 415)
    if ext in (".mp4", ".mov"):
        if head[4:8] not in _ISO_BMFF_BOXES:
            raise UploadError("The file does not look like an MP4/MOV container.", 415)
    elif ext == ".mkv" and not head.startswith(_MATROSKA_MAGIC):
        raise UploadError("The file does not look like a Matroska (MKV) container.", 415)


def check_size(size_bytes: int, max_bytes: int) -> None:
    """Raise ``UploadError`` (413) when ``size_bytes`` exceeds the configured limit."""
    if size_bytes > max_bytes:
        raise UploadError(
            f"The file is {size_bytes / 1024**2:.0f} MB; the upload limit is "
            f"{max_bytes / 1024**2:.0f} MB.",
            413,
        )


def validate_source_kind(value: str) -> str:
    kind = (value or "").strip().lower()
    if kind not in UPLOAD_SOURCE_KINDS:
        raise UploadError("source_kind must be 'recorded' or 'generated'.", 422)
    return kind


def upload_id_for(filename: str, sha256: str) -> str:
    stem = Path(safe_filename(filename)).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "video"
    return f"{stem[:40]}-{sha256[:10]}"


def probe_video_file(path: Path) -> VideoInfo:
    """Open the file with PyAV and read the first video stream's properties.

    Raises ``UploadError`` (422) when the file has no decodable video stream.
    """
    import av

    try:
        container = av.open(str(path))
    except Exception as exc:
        raise UploadError(f"The file could not be opened as video: {exc}", 422) from exc
    try:
        stream = next((s for s in container.streams.video), None)
        if stream is None:
            raise UploadError("The file has no video stream.", 422)
        fps = float(stream.average_rate) if stream.average_rate else None
        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            duration = container.duration / 1_000_000
        frames = int(stream.frames) if stream.frames else None
        if frames is None and duration and fps:
            frames = round(duration * fps)
        return VideoInfo(
            duration_s=round(duration, 3) if duration is not None else None,
            width=stream.codec_context.width or None,
            height=stream.codec_context.height or None,
            fps=round(fps, 3) if fps else None,
            codec=stream.codec_context.name,
            frames=frames,
        )
    finally:
        container.close()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
