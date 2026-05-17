from hashlib import sha256
from pathlib import Path


def hash_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def hash_text(payload: str) -> str:
    return hash_bytes(payload.encode("utf-8"))


def hash_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

