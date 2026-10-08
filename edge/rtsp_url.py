"""Parse a pasted RTSP link and separate the credentials from the address.

The "RTSP URL" camera profile lets an operator paste a complete
``rtsp://`` or ``rtsps://`` link, as copied from a camera's web page or an
NVR. Links often carry ``user:password@`` in the authority. This module
splits that out so the password can be encrypted like every other camera
password and the address stored and displayed without it. Nothing here logs
or keeps the raw link.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from edge.camera_profiles import CameraConfigError

RTSP_SCHEMES = ("rtsp", "rtsps")
DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322}


@dataclass(frozen=True)
class ParsedRtspUrl:
    """A pasted link with the credentials taken out.

    ``stripped_url`` is the address without ``user:password@`` and without a
    fragment. ``username`` and ``password`` are decoded (``%40`` becomes
    ``@``) and may be empty when the link carried none.
    """

    scheme: str
    host: str
    port: int
    path: str
    stripped_url: str
    username: str = ""
    password: str = ""

    @property
    def has_credentials(self) -> bool:
        return bool(self.username or self.password)


def parse_rtsp_url(text: str) -> ParsedRtspUrl:
    """Validate ``text`` as an RTSP link and strip embedded credentials.

    Raises :class:`CameraConfigError` with an operator-readable message when
    the scheme is not rtsp/rtsps or the host is missing. The message never
    includes the pasted link.
    """
    raw = (text or "").strip()
    if not raw:
        raise CameraConfigError("Paste the camera's rtsp:// or rtsps:// link.")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in RTSP_SCHEMES:
        raise CameraConfigError("The link must start with rtsp:// or rtsps://.")
    host = (parts.hostname or "").strip()
    if not host:
        raise CameraConfigError("The link has no host; expected rtsp://host:port/path.")
    try:
        port = parts.port
    except ValueError as exc:
        raise CameraConfigError("The link's port is not a number.") from exc
    netloc = host if ":" not in host else f"[{host}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parts.path or ""
    stripped = urlunsplit((scheme, netloc, path, parts.query, ""))
    return ParsedRtspUrl(
        scheme=scheme,
        host=host,
        port=port or DEFAULT_PORTS[scheme],
        path=path + (f"?{parts.query}" if parts.query else ""),
        stripped_url=stripped,
        username=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
    )


def with_credentials(stripped_url: str, username: str | None, password: str | None) -> str:
    """Put ``username:password@`` back into a credential-free link for the decoder."""
    if not (username or password):
        return stripped_url
    parts = urlsplit(stripped_url)
    host = parts.hostname or ""
    netloc = host if ":" not in host else f"[{host}]"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    auth = f"{quote(username or '', safe='')}:{quote(password or '', safe='')}@"
    return urlunsplit((parts.scheme, auth + netloc, parts.path, parts.query, ""))
