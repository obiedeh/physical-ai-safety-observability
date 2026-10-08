"""Enumerate USB (V4L2) cameras and the capture modes each one supports.

Linux exposes every video device under ``/dev/video*`` with a matching
``/sys/class/video4linux/videoN`` entry. A UVC camera registers two nodes:
the capture node (``index`` 0) and a metadata node (``index`` 1) that cannot
be opened for frames, so only capture nodes are listed. Supported pixel
formats, frame sizes and frame rates are read with the standard V4L2 ioctls
(no external tool is required). The per-device query is injectable so tests
can run with a fake device tree and no hardware.
"""
from __future__ import annotations

import array
import fcntl
import os
import struct
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEV_DIR = Path("/dev")
SYS_DIR = Path("/sys/class/video4linux")

# ioctl request numbers (linux/videodev2.h), built from the _IOR/_IOWR macros.
_IOC_READ, _IOC_WRITE = 2, 1


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("V") << 8) | nr


VIDIOC_QUERYCAP = _ioc(_IOC_READ, 0, 104)
VIDIOC_ENUM_FMT = _ioc(_IOC_READ | _IOC_WRITE, 2, 64)
VIDIOC_ENUM_FRAMESIZES = _ioc(_IOC_READ | _IOC_WRITE, 74, 44)
VIDIOC_ENUM_FRAMEINTERVALS = _ioc(_IOC_READ | _IOC_WRITE, 75, 52)
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_CAP_VIDEO_CAPTURE = 0x1
V4L2_FRMSIZE_TYPE_DISCRETE = 1
V4L2_FRMIVAL_TYPE_DISCRETE = 1


@dataclass
class UsbMode:
    """One frame size of one pixel format, with the frame rates it offers."""

    pixel_format: str
    width: int
    height: int
    fps: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UsbDevice:
    path: str
    name: str
    modes: list[UsbMode] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "modes": [m.to_dict() for m in self.modes],
            "error": self.error,
        }


def _fourcc(value: int) -> str:
    return struct.pack("<I", value).decode("ascii", errors="replace").strip("\x00 ")


def _ioctl(fd: int, request: int, buf: array.array) -> bool:
    """Run one ioctl; return False when the kernel reports the end of a list."""
    try:
        fcntl.ioctl(fd, request, buf, True)
    except OSError:
        return False
    return True


def query_capture_modes(path: str) -> list[UsbMode]:
    """Read pixel formats, discrete frame sizes and frame rates from a V4L2 node.

    Raises ``OSError`` when the node cannot be opened or is not a video
    capture device (for example the UVC metadata node).
    """
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    try:
        cap = array.array("B", bytes(104))
        if not _ioctl(fd, VIDIOC_QUERYCAP, cap):
            raise OSError(f"{path} does not answer VIDIOC_QUERYCAP")
        device_caps = struct.unpack_from("<I", cap, 88)[0]
        if not device_caps & V4L2_CAP_VIDEO_CAPTURE:
            raise OSError(f"{path} is not a video capture device")
        modes: list[UsbMode] = []
        fmt_index = 0
        while True:
            fmt = array.array("B", bytes(64))
            struct.pack_into("<II", fmt, 0, fmt_index, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            if not _ioctl(fd, VIDIOC_ENUM_FMT, fmt):
                break
            pixel_format = struct.unpack_from("<I", fmt, 44)[0]
            fourcc = _fourcc(pixel_format)
            size_index = 0
            while True:
                frm = array.array("B", bytes(44))
                struct.pack_into("<II", frm, 0, size_index, pixel_format)
                if not _ioctl(fd, VIDIOC_ENUM_FRAMESIZES, frm):
                    break
                kind = struct.unpack_from("<I", frm, 8)[0]
                if kind == V4L2_FRMSIZE_TYPE_DISCRETE:
                    sizes = [struct.unpack_from("<II", frm, 12)]
                else:  # stepwise/continuous: offer the smallest and largest size
                    min_w, max_w, _sw, min_h, max_h, _sh = struct.unpack_from("<6I", frm, 12)
                    sizes = [(min_w, min_h), (max_w, max_h)]
                for width, height in sizes:
                    rates = _frame_rates(fd, pixel_format, width, height)
                    modes.append(UsbMode(fourcc, width, height, rates))
                size_index += 1
                if kind != V4L2_FRMSIZE_TYPE_DISCRETE:
                    break
            fmt_index += 1
        modes.sort(key=lambda m: (-(m.width * m.height), m.pixel_format))
        return modes
    finally:
        os.close(fd)


def _frame_rates(fd: int, pixel_format: int, width: int, height: int) -> list[float]:
    rates: list[float] = []
    index = 0
    while True:
        buf = array.array("B", bytes(52))
        struct.pack_into("<IIII", buf, 0, index, pixel_format, width, height)
        if not _ioctl(fd, VIDIOC_ENUM_FRAMEINTERVALS, buf):
            break
        kind = struct.unpack_from("<I", buf, 16)[0]
        num, den = struct.unpack_from("<II", buf, 20)
        if kind == V4L2_FRMIVAL_TYPE_DISCRETE:
            if num:
                rates.append(round(den / num, 2))
        else:
            # stepwise: min interval gives the highest rate; report it alone
            if num:
                rates.append(round(den / num, 2))
            break
        index += 1
    return sorted(set(rates), reverse=True)


def list_usb_devices(
    dev_dir: Path = DEV_DIR,
    sys_dir: Path = SYS_DIR,
    query_modes: Callable[[str], list[UsbMode]] = query_capture_modes,
) -> list[UsbDevice]:
    """List capture-capable ``/dev/video*`` nodes with their names and modes.

    Nodes whose sysfs ``index`` is not 0 (metadata nodes) are skipped. A node
    that exists but cannot be queried is still listed with ``error`` set, so
    the operator sees it and the reason (permissions, busy).
    """
    devices: list[UsbDevice] = []
    for node in sorted(dev_dir.glob("video*"), key=_node_number):
        number = _node_number(node)
        if number < 0:
            continue
        sys_node = sys_dir / node.name
        name = _read(sys_node / "name") or node.name
        index = _read(sys_node / "index")
        if index not in ("", "0"):
            continue
        device = UsbDevice(path=str(node), name=name)
        try:
            device.modes = query_modes(str(node))
        except OSError as exc:
            if "not a video capture device" in str(exc):
                continue
            device.error = describe_device_error(exc)
        devices.append(device)
    return devices


# V4L2 fourcc -> libavdevice ``input_format`` name. Cameras usually offer MJPG at
# their higher frame rates and raw YUYV only at low ones, so the format matters.
INPUT_FORMATS: dict[str, str] = {
    "MJPG": "mjpeg",
    "YUYV": "yuyv422",
    "UYVY": "uyvy422",
    "NV12": "nv12",
    "H264": "h264",
    "GREY": "gray",
    "RGB3": "rgb24",
    "BGR3": "bgr24",
}


def v4l2_options(
    width: int | None, height: int | None, fps: float | None, pixel_format: str | None = None
) -> dict[str, str]:
    """libav input options for a V4L2 device; blank values keep the driver default."""
    options: dict[str, str] = {}
    if width and height:
        options["video_size"] = f"{width}x{height}"
    if fps:
        options["framerate"] = f"{fps:g}"
    fmt = INPUT_FORMATS.get((pixel_format or "").upper())
    if fmt:
        options["input_format"] = fmt
    return options


def describe_device_error(exc: BaseException) -> str:
    """Turn an OS/libav error on a V4L2 node into a sentence the operator can act on."""
    text = str(exc)
    lower = text.lower()
    if "busy" in lower:
        return "The device is busy: another program (or another camera entry) is using it."
    if "no such file" in lower or "no such device" in lower:
        return "No camera at this device path. It may have been unplugged or renumbered."
    if "permission denied" in lower:
        return "Permission denied opening the device. Add the service user to the video group."
    if "inappropriate ioctl" in lower or "not a video capture" in lower:
        return "This node is not a video capture device (it may be the camera's metadata node)."
    return text


def _node_number(path: Path) -> int:
    digits = path.name[len("video"):]
    return int(digits) if digits.isdigit() else -1


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
