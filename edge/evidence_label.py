"""Burn a provenance label into evidence frames from non-live sources.

Frames captured from an uploaded recording, generated footage or the
synthetic test feed must never be mistaken for a live camera. Besides the
``source_kind`` field on the event, the stored evidence JPEG itself gets a
banner so the label survives a download or a screenshot.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

EVIDENCE_LABELS: dict[str, str] = {
    "uploaded_recorded": "UPLOADED RECORDING - not a live camera",
    "uploaded_generated": "GENERATED FOOTAGE - not a live camera",
    "synthetic": "SYNTHETIC TEST FEED - not a live camera",
}


def evidence_note(source_kind: str | None) -> str | None:
    """Human-readable note for non-live sources, ``None`` for live ones."""
    if not source_kind:
        return None
    return EVIDENCE_LABELS.get(source_kind)


def stamp_evidence(jpeg: bytes, source_kind: str | None, quality: int = 85) -> bytes:
    """Return ``jpeg`` with a banner for non-live sources, unchanged otherwise."""
    label = evidence_note(source_kind)
    if label is None or not jpeg:
        return jpeg
    try:
        loaded = Image.open(io.BytesIO(jpeg))
        loaded.load()
    except (OSError, ValueError):
        return jpeg
    image: Image.Image = loaded.convert("RGB") if loaded.mode != "RGB" else loaded
    band_h = max(18, image.height // 18)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([(0, 0), (image.width, band_h)], fill=(120, 60, 0, 190))
    draw.text((8, max(2, band_h // 2 - 6)), label, fill=(255, 230, 160, 255))
    stamped = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    stamped.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
