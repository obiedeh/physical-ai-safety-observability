"""Asynchronous event/feedback posting, off the capture and inference threads.

The capture→inference loop hands payloads to ``AsyncPoster.enqueue`` and
returns immediately. One background thread drains the queue to the backend
with retries. Latency is measured end to end: ``packet_to_event`` is the time
from the frame's capture timestamp until the backend acknowledged the event.
If the queue overflows (backend down for a long time), the oldest payloads
are dropped and counted, never blocking capture.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import httpx

from edge.redaction import REDACTOR

logger = logging.getLogger("edge.poster")


@dataclass
class PostJob:
    kind: str                     # "event" | "events_batch" | "feedback"
    payload: Any
    captured_monotonic: float     # time.monotonic() when the frame was captured
    enqueued_monotonic: float = field(default_factory=time.monotonic)
    on_done: Any = None           # optional callback(job, ok: bool, latency_ms: float)


class AsyncPoster:
    def __init__(
        self,
        backend: str,
        *,
        max_queue: int = 500,
        retries: int = 3,
        timeout_s: float = 10.0,
    ) -> None:
        self.backend = backend.rstrip("/")
        self._queue: queue.Queue[PostJob] = queue.Queue(maxsize=max_queue)
        self._retries = retries
        self._timeout_s = timeout_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: httpx.Client | None = None
        self._lock = threading.Lock()
        self.posted = 0
        self.failed = 0
        self.dropped = 0
        self.post_latency_ms: deque[float] = deque(maxlen=2000)
        self.packet_to_event_ms: deque[float] = deque(maxlen=2000)
        self.last_error: str | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._client = httpx.Client(timeout=self._timeout_s)
        self._thread = threading.Thread(target=self._run, name="event-poster", daemon=True)
        self._thread.start()

    def stop(self, drain_timeout_s: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(drain_timeout_s)
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ── producer side ─────────────────────────────────────────────────────────

    def enqueue(self, job: PostJob) -> bool:
        """Never blocks. Drops the oldest job when the queue is full."""
        try:
            self._queue.put_nowait(job)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.dropped += 1
            except queue.Empty:  # pragma: no cover - race
                pass
            try:
                self._queue.put_nowait(job)
                return True
            except queue.Full:  # pragma: no cover - race
                self.dropped += 1
                return False

    # ── consumer side ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                job = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            ok, latency_ms = self._post(job)
            now = time.monotonic()
            with self._lock:
                if ok:
                    self.posted += 1
                    self.post_latency_ms.append(latency_ms)
                    if job.kind in {"event", "events_batch"}:
                        self.packet_to_event_ms.append((now - job.captured_monotonic) * 1000)
                else:
                    self.failed += 1
            if job.on_done is not None:
                try:
                    job.on_done(job, ok, latency_ms)
                except Exception:  # pragma: no cover - callback bugs must not kill the thread
                    logger.exception("poster callback failed")

    def _url(self, kind: str) -> str:
        path = {"event": "/events", "events_batch": "/events/batch", "feedback": "/feedback"}[kind]
        return f"{self.backend}{path}"

    def _post(self, job: PostJob) -> tuple[bool, float]:
        assert self._client is not None
        url = self._url(job.kind)
        started = time.perf_counter()
        for attempt in range(self._retries):
            try:
                response = self._client.post(url, json=job.payload)
                response.raise_for_status()
                return True, (time.perf_counter() - started) * 1000
            except httpx.HTTPStatusError as exc:
                self.last_error = REDACTOR.redact(f"{exc.response.status_code} from {url}")
                if exc.response.status_code < 500 or attempt == self._retries - 1:
                    break
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                self.last_error = REDACTOR.redact(f"{type(exc).__name__}: {exc}")
                if attempt == self._retries - 1:
                    break
            if self._stop.wait(0.5 * (2**attempt)):
                break
        return False, (time.perf_counter() - started) * 1000

    # ── stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            post = sorted(self.post_latency_ms)
            p2e = sorted(self.packet_to_event_ms)
        return {
            "backend": self.backend,
            "queue_depth": self.queue_depth,
            "posted": self.posted,
            "failed": self.failed,
            "dropped": self.dropped,
            "last_error": self.last_error,
            "post_latency_ms": _summary(post),
            "packet_to_event_ms": _summary(p2e),
        }


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}

    def pct(p: float) -> float:
        idx = min(len(values) - 1, round(p / 100 * (len(values) - 1)))
        return round(values[idx], 3)

    return {
        "n": len(values),
        "unit": "ms",
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "min": round(values[0], 3),
        "max": round(values[-1], 3),
        "mean": round(sum(values) / len(values), 3),
    }
