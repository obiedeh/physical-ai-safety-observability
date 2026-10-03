"""Thread-safe latest-result hub for the Live view (SSE readers wait on it)."""
from __future__ import annotations

import threading
import time
from typing import Any


class ResultHub:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._seq = 0
        self._latest: dict[str, dict[str, Any]] = {}
        self._history: list[tuple[int, dict[str, Any]]] = []

    @property
    def latest(self) -> dict[str, dict[str, Any]]:
        with self._cond:
            return dict(self._latest)

    def publish(self, camera_id: str, result: dict[str, Any]) -> int:
        with self._cond:
            self._seq += 1
            result = {**result, "seq": self._seq, "published_at": time.time()}
            self._latest[camera_id] = result
            self._history.append((self._seq, result))
            if len(self._history) > 200:
                del self._history[: len(self._history) - 200]
            self._cond.notify_all()
            return self._seq

    def wait_after(self, after_seq: int, timeout: float) -> list[dict[str, Any]]:
        """Return results newer than ``after_seq``; block up to ``timeout`` for new ones."""
        with self._cond:
            newer = [r for s, r in self._history if s > after_seq]
            if newer:
                return newer
            self._cond.wait(timeout)
            return [r for s, r in self._history if s > after_seq]

    def forget(self, camera_id: str) -> None:
        with self._cond:
            self._latest.pop(camera_id, None)
