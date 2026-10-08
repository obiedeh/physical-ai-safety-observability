"""UI-driven configuration: cameras (CRUD, test, enable), USB devices, uploads, model.

Pasted RTSP links are stored and echoed without their credentials. Uploaded
videos arrive as a raw request body (no multipart parser needed) and are kept
next to the database. Camera changes are applied to the running EdgeService.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.services.edge import edge_service
from edge.camera_profiles import CameraConfigError, get_profile, list_profiles
from edge.config_models import (
    CameraIn,
    CameraRecord,
    InferenceSettings,
    ModelSettings,
    UploadRecord,
)
from edge.probe import probe_stream
from edge.redaction import REDACTOR
from edge.rtsp_url import with_credentials
from edge.uploads import (
    SNIFF_BYTES,
    UploadError,
    check_signature,
    check_size,
    content_type_for,
    probe_video_file,
    safe_filename,
    upload_id_for,
    validate_source_kind,
)
from edge.usb_devices import list_usb_devices, v4l2_options
from runtime_settings import load_settings

router = APIRouter(prefix="/config", tags=["config"])

# Configured upload limit (PHYSICAL_AI_UPLOAD_MAX_BYTES, default 2 GiB); tests patch it.
UPLOAD_MAX_BYTES: int = load_settings().uploads.max_bytes
# V4L2 enumerator; tests patch it with a fake device list.
usb_lister = list_usb_devices


class EnableIn(BaseModel):
    enabled: bool


class CameraOut(CameraRecord):
    runtime: dict | None = None


def _out(record: CameraRecord) -> CameraOut:
    session = edge_service.session(record.camera_id)
    worker = edge_service.workers.get(record.camera_id)
    runtime = None
    if session is not None:
        runtime = {**session.status(), "worker": worker.status() if worker else None}
    return CameraOut(**record.model_dump(), runtime=runtime)


@router.get("/profiles")
def camera_profiles() -> list[dict]:
    return list_profiles()


# ── USB devices ───────────────────────────────────────────────────────────────


@router.get("/usb-devices")
async def usb_devices() -> dict:
    """List ``/dev/video*`` capture devices with their names and supported modes.

    An empty list means no camera is plugged in (or none is visible to this
    process); ``note`` carries the message to show. A device that exists but
    cannot be queried is listed with its ``error``.
    """
    devices = await asyncio.to_thread(usb_lister)
    note = None
    if not devices:
        note = (
            "No USB camera found. Plug one in and refresh; it must appear as /dev/video* "
            "and be readable by the user running the API (video group)."
        )
    return {"devices": [d.to_dict() for d in devices], "note": note}


# ── Uploaded videos ───────────────────────────────────────────────────────────


@router.get("/uploads", response_model=list[UploadRecord])
def list_uploads() -> list[UploadRecord]:
    return edge_service.store.list_uploads()


@router.post("/uploads", response_model=UploadRecord, status_code=201)
async def upload_video(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    source_kind: str = Query("recorded"),
) -> UploadRecord:
    """Receive an MP4/MOV/MKV as the raw request body and register it.

    The file is streamed to a temporary name next to the database while its
    hash is computed and the size limit enforced, checked for a matching
    container signature, then opened with PyAV to read its native frame rate,
    size and duration. ``source_kind`` records whether the footage is a real
    recording or generated, and is shown on every event the file produces.
    """
    store = edge_service.store
    max_bytes = UPLOAD_MAX_BYTES
    try:
        kind = validate_source_kind(source_kind)
        safe = safe_filename(filename)
        content_type = content_type_for(safe)
        declared = request.headers.get("content-length", "")
        if declared.isdigit():
            check_size(int(declared), max_bytes)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    store.upload_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".upload-", suffix=Path(safe).suffix, dir=store.upload_dir
    )
    tmp = Path(tmp_name)
    digest = hashlib.sha256()
    size = 0
    head = b""
    sniffed = False
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                check_size(size, max_bytes)
                if not sniffed:
                    head += chunk[: SNIFF_BYTES - len(head)]
                    if len(head) >= SNIFF_BYTES:
                        check_signature(head, safe)
                        sniffed = True
                digest.update(chunk)
                await asyncio.to_thread(fh.write, chunk)
        if size == 0:
            raise UploadError("The upload is empty.", 400)
        if not sniffed:
            check_signature(head, safe)
        info = await asyncio.to_thread(probe_video_file, tmp)
        sha = digest.hexdigest()
        upload_id = upload_id_for(safe, sha)
        stored_name = f"{upload_id}{Path(safe).suffix}"
        os.replace(tmp, store.upload_dir / stored_name)
    except UploadError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    record = UploadRecord(
        id=upload_id, filename=safe, stored_name=stored_name, content_type=content_type,
        size_bytes=size, sha256=sha, source_kind=kind,  # type: ignore[arg-type]
        created_at=datetime.now(UTC).isoformat(), **info.to_dict(),
    )
    return store.add_upload(record)


@router.get("/uploads/{upload_id}", response_model=UploadRecord)
def get_upload(upload_id: str) -> UploadRecord:
    record = edge_service.store.get_upload(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return record


@router.delete("/uploads/{upload_id}", status_code=204)
def delete_upload(upload_id: str) -> None:
    """Delete the upload row and its file. Refused (409) while a camera still plays it."""
    record = edge_service.store.get_upload(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="upload not found")
    if record.camera_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "upload_in_use",
                "camera_ids": record.camera_ids,
                "message": (
                    "This video is used by camera(s) "
                    + ", ".join(record.camera_ids)
                    + ". Delete or re-point those cameras first."
                ),
            },
        )
    edge_service.store.delete_upload(upload_id)


@router.get("/cameras", response_model=list[CameraOut])
def list_cameras() -> list[CameraOut]:
    return [_out(c) for c in edge_service.list_cameras()]


@router.post("/cameras", response_model=CameraOut, status_code=201)
def create_camera(req: CameraIn) -> CameraOut:
    try:
        record = edge_service.create_camera(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _out(record)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str) -> CameraOut:
    record = edge_service.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: str, req: CameraIn) -> CameraOut:
    try:
        record = edge_service.update_camera(camera_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.post("/cameras/{camera_id}/enabled", response_model=CameraOut)
def set_enabled(camera_id: str, req: EnableIn) -> CameraOut:
    record = edge_service.set_enabled(camera_id, req.enabled)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.post("/cameras/{camera_id}/restart", response_model=CameraOut)
def restart_camera(camera_id: str) -> CameraOut:
    """Restart the capture session: reconnects a stream or replays a play-once video."""
    record = edge_service.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    edge_service.refresh_camera(camera_id)
    return _out(record)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: str) -> None:
    if not edge_service.delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="camera not found")


def _probe(
    url: str,
    transport: str,
    input_format: str | None = None,
    input_options: dict[str, str] | None = None,
) -> dict:
    data = probe_stream(
        url, rtsp_transport=transport, input_format=input_format, input_options=input_options
    ).to_dict()
    if data.get("error"):
        data["error"] = REDACTOR.redact(data["error"])
    return data


def _no_stream_note(label: str) -> dict:
    return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
            "note": f"{label} has no stream to probe."}


def _upload_note(upload: UploadRecord | None) -> dict:
    if upload is None:
        return {"ok": False, "stage": "url", "masked_url": "",
                "error": "Uploaded video not found. Upload it first."}
    size = f"{upload.width}x{upload.height}" if upload.width and upload.height else "unknown size"
    fps = f"{upload.fps:g} fps" if upload.fps else "unknown rate"
    dur = f"{upload.duration_s:.1f} s" if upload.duration_s else "unknown length"
    return {
        "ok": True, "stage": "ok", "error": None, "masked_url": upload.filename,
        "width": upload.width, "height": upload.height, "fps": upload.fps, "codec": upload.codec,
        "note": f"{upload.source_kind} footage, {size}, {fps}, {dur}",
    }


class CameraTestIn(CameraIn):
    # Editing a saved camera with the password left blank: the stored one is used.
    camera_id: str | None = None


@router.post("/cameras/test")
def test_unsaved_camera(req: CameraTestIn) -> dict:
    """Probe the stream, device or file described by the form (not yet saved)."""
    profile = get_profile(req.profile)
    if profile.connector == "usb":
        options = v4l2_options(
            req.capture_width, req.capture_height, req.capture_fps, req.capture_format
        )
        return _probe(req.device, "tcp", "v4l2", options)
    if profile.connector == "upload":
        return _upload_note(edge_service.store.get_upload(req.upload_id))
    if not profile.requires_host and profile.connector != "rtsp_url":
        return _no_stream_note(profile.label)
    password = req.password
    if not password and req.camera_id:
        cfg = edge_service.store.get_camera_config(req.camera_id)
        if cfg is None:
            return {"ok": False, "stage": "url", "masked_url": "",
                    "error": f"Camera '{req.camera_id}' is not saved; enter the password."}
        # The stored password is only ever sent to the host it was saved for.
        saved_port = cfg.get("port") or profile.default_port
        if (cfg.get("host"), saved_port) != (req.host, req.port):
            return {
                "ok": False, "stage": "url", "masked_url": "",
                "error": (
                    "Host or port differs from the saved camera, so the stored password "
                    "cannot be reused. Enter the password to test the new address."
                ),
            }
        password = edge_service.secrets.decrypt(cfg.get("password_enc") or "")
    try:
        if profile.connector == "rtsp_url":
            url = with_credentials(req.source_url, req.username or None, password or None)
        else:
            url = profile.build_url(
                host=req.host, username=req.username or None, password=password or None,
                port=req.port, channel=req.channel, quality=req.stream_quality,
                path=req.stream_path or None,
            )
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    REDACTOR.register(password)
    return _probe(url, req.rtsp_transport)


@router.post("/cameras/{camera_id}/test")
def test_saved_camera(camera_id: str) -> dict:
    record = edge_service.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    profile = get_profile(record.profile)
    if profile.connector == "usb":
        options = v4l2_options(
            record.capture_width, record.capture_height, record.capture_fps, record.capture_format
        )
        return _probe(record.device, "tcp", "v4l2", options)
    if profile.connector == "upload":
        return _upload_note(record.upload)
    if not profile.requires_host and profile.connector != "rtsp_url":
        return _no_stream_note(profile.label)
    try:
        url = edge_service.feed_url(camera_id)
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    return _probe(url, record.rtsp_transport)


# ── model / inference ─────────────────────────────────────────────────────────


@router.get("/model", response_model=ModelSettings)
def get_model() -> ModelSettings:
    return edge_service.get_model_settings()


@router.put("/model", response_model=ModelSettings)
def put_model(req: ModelSettings) -> ModelSettings:
    return edge_service.put_model_settings(req)


@router.get("/model/guard")
def model_guard() -> dict:
    return {
        "guard": edge_service.guard.to_dict() if edge_service.guard else None,
        "constrained_allowed": edge_service.constrained_allowed(),
        "json_schema": edge_service.model_settings.json_schema,
    }


@router.post("/model/guard")
def rerun_model_guard() -> dict:
    result = edge_service.run_guard()
    return {
        "guard": result.to_dict(),
        "constrained_allowed": edge_service.constrained_allowed(),
        "json_schema": edge_service.model_settings.json_schema,
    }


@router.get("/inference", response_model=InferenceSettings)
def get_inference() -> InferenceSettings:
    return edge_service.get_inference_settings()


@router.put("/inference", response_model=InferenceSettings)
def put_inference(req: InferenceSettings) -> InferenceSettings:
    return edge_service.put_inference_settings(req)
