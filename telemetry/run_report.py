"""Write a measured run artifact from the edge worker.

One JSON file per run, carrying everything a reader needs to trust a number:
device identity and software versions, the adapter and model that produced
detections, the source and its hash, per-frame timings, event counts, process
memory, and on Jetson a 1 Hz ``tegrastats`` summary of rails and temperatures.

The recorder never invents a value. Fields that cannot be read on the host are
written as ``null``.
"""

from __future__ import annotations

import json
import os
import platform
import re
import resource
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence.hashing import hash_file

SCHEMA_VERSION = "run-report-v1"


def _percentile(values: list[float], percentile: float) -> float | None:
    """Index-based percentile: sorted value at round(p * (n - 1))."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1)))
    return ordered[index]


def _read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def jetson_soc() -> str | None:
    raw = _read_text("/sys/firmware/devicetree/base/compatible")
    if not raw:
        return None
    parts = [p for p in raw.split("\x00") if p]
    for part in parts:
        if part.startswith("nvidia,tegra"):
            return part.split(",", 1)[1]
    return parts[0] if parts else None


def device_provenance(repo_root: Path | None = None) -> dict[str, Any]:
    soc = jetson_soc()
    l4t = _read_text("/etc/nv_tegra_release")
    meminfo = _read_text("/proc/meminfo") or ""
    match = re.search(r"MemTotal:\s+(\d+) kB", meminfo)
    try:
        load1, load5, _ = os.getloadavg()
    except OSError:
        load1 = load5 = None
    git_sha = _run(["git", "-C", str(repo_root or Path.cwd()), "rev-parse", "--short", "HEAD"])
    return {
        "host": platform.node(),
        "machine": platform.machine(),
        "kernel": platform.release(),
        "soc": soc,
        "is_jetson": soc is not None,
        "l4t_release": l4t.splitlines()[0].strip() if l4t else None,
        "nvpmodel": (_run(["nvpmodel", "-q"]) or "").replace("\n", " ") or None,
        "cpu_count": os.cpu_count(),
        "mem_total_gb": round(int(match.group(1)) / 1024 / 1024, 2) if match else None,
        "loadavg_1m_at_start": load1,
        "loadavg_5m_at_start": load5,
        "python": platform.python_version(),
        "git_sha": git_sha,
    }


_RAIL_RE = re.compile(r"(V[A-Z0-9_]+)\s+(\d+)mW/(\d+)mW")
_TEMP_RE = re.compile(r"([a-z0-9]+)@([0-9.]+)C")
_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")


class TegrastatsSampler:
    """Background 1 Hz ``tegrastats`` reader; no-op when the binary is absent."""

    def __init__(self, interval_ms: int = 1000) -> None:
        self.interval_ms = interval_ms
        self.samples: list[dict[str, Any]] = []
        self._proc: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                ["tegrastats", "--interval", str(self.interval_ms)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return True

    def _pump(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            if not line.strip():
                continue
            sample: dict[str, Any] = {"t": time.time()}
            ram = _RAM_RE.search(line)
            if ram:
                sample["ram_used_mb"] = int(ram.group(1))
                sample["ram_total_mb"] = int(ram.group(2))
            sample["temps_c"] = {k: float(v) for k, v in _TEMP_RE.findall(line)}
            sample["rails_mw"] = {k: int(v) for k, v, _avg in _RAIL_RE.findall(line)}
            self.samples.append(sample)

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"n_samples": 0}
        rails: dict[str, list[int]] = {}
        temps: dict[str, list[float]] = {}
        ram: list[int] = []
        for s in self.samples:
            for k, v in s.get("rails_mw", {}).items():
                rails.setdefault(k, []).append(v)
            for k, v in s.get("temps_c", {}).items():
                temps.setdefault(k, []).append(v)
            if "ram_used_mb" in s:
                ram.append(s["ram_used_mb"])
        return {
            "n_samples": len(self.samples),
            "rails_mw": {
                k: {"p50": _percentile([float(x) for x in v], 50), "peak": max(v), "min": min(v)}
                for k, v in rails.items()
            },
            "temps_c": {k: {"p50": _percentile(v, 50), "peak": max(v)} for k, v in temps.items()},
            "board_ram_used_mb": (
                {"p50": _percentile([float(x) for x in ram], 50), "peak": max(ram)} if ram else None
            ),
        }


@dataclass
class RunRecorder:
    """Collects per-frame timings and event counts for one worker run."""

    adapter_name: str
    model_version: str
    source_path: str | None = None
    source_info: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    frames: list[dict[str, Any]] = field(default_factory=list)
    events_by_rule: dict[str, int] = field(default_factory=dict)
    events_by_severity: dict[str, int] = field(default_factory=dict)
    detections_by_label: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    tegrastats: TegrastatsSampler | None = None
    _mono_start: float = field(default_factory=time.monotonic)

    def start_tegrastats(self) -> bool:
        sampler = TegrastatsSampler()
        if sampler.start():
            self.tegrastats = sampler
            return True
        return False

    def record_frame(
        self,
        *,
        frame_id: str,
        inference_ms: float,
        rule_ms: float,
        post_ms: float | None,
        events: list[dict[str, Any]],
        detections: int | None = None,
        usage: dict[str, Any] | None = None,
        labels: list[str] | None = None,
    ) -> None:
        usage = usage or {}
        for label in labels or []:
            self.detections_by_label[label] = self.detections_by_label.get(label, 0) + 1
        self.frames.append(
            {
                "frame_id": frame_id,
                "t": time.monotonic() - self._mono_start,
                "inference_ms": round(inference_ms, 4),
                "rule_ms": round(rule_ms, 4),
                "post_ms": round(post_ms, 4) if post_ms is not None else None,
                "events": len(events),
                "detections": detections,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            }
        )
        for event in events:
            rule = str(event.get("rule_id", "unknown"))
            severity = str(event.get("severity", "unknown"))
            self.events_by_rule[rule] = self.events_by_rule.get(rule, 0) + 1
            self.events_by_severity[severity] = self.events_by_severity.get(severity, 0) + 1

    def _stats(self, key: str) -> dict[str, Any]:
        values = [f[key] for f in self.frames if f.get(key) is not None]
        if not values:
            return {"n": 0}
        unit = "ms" if key.endswith("_ms") else "count"
        return {
            "n": len(values),
            "unit": unit,
            "p50": _percentile(values, 50),
            "p95": _percentile(values, 95),
            "p99": _percentile(values, 99),
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 4),
        }

    def report(self, repo_root: Path | None = None) -> dict[str, Any]:
        if self.tegrastats:
            self.tegrastats.stop()
        elapsed = time.monotonic() - self._mono_start
        n = len(self.frames)
        source_hash = None
        if self.source_path and Path(self.source_path).is_file():
            source_hash = hash_file(self.source_path)
        return {
            "schema": SCHEMA_VERSION,
            "status": "failed" if self.error else "complete",
            "error": self.error,
            "note": (
                "Measured runtime overhead of the edge worker on the named device. Detections come "
                "from the named adapter; a mock adapter produces fixed detections and this artifact "
                "then says nothing about detection quality."
            ),
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "elapsed_s": round(elapsed, 3),
            "device": device_provenance(repo_root),
            "adapter": {"name": self.adapter_name, "model_version": self.model_version},
            "config": self.config,
            "source": {**self.source_info, "path": self.source_path, "sha256": source_hash},
            "frames_processed": n,
            "frames_per_second": round(n / elapsed, 3) if elapsed > 0 and n else None,
            "latency": {
                "inference": self._stats("inference_ms"),
                "rule_eval": self._stats("rule_ms"),
                "backend_post": self._stats("post_ms"),
            },
            "model_tokens": {
                "prompt": self._stats("prompt_tokens"),
                "completion": self._stats("completion_tokens"),
                "note": "Present only when the adapter returns an OpenAI-style usage block.",
            },
            "detections_per_frame": self._stats("detections"),
            "detections_by_label": dict(sorted(self.detections_by_label.items())),
            "events": {
                "total": sum(self.events_by_rule.values()),
                "by_rule": dict(sorted(self.events_by_rule.items())),
                "by_severity": dict(sorted(self.events_by_severity.items())),
            },
            "memory": {
                "process_peak_rss_gb": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 4
                ),
            },
            "tegrastats": self.tegrastats.summary() if self.tegrastats else None,
            "per_frame": self.frames,
        }

    def write(self, path: str | Path, repo_root: Path | None = None) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        report = self.report(repo_root)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if self.tegrastats and self.tegrastats.samples:
            side = out.with_name(out.stem + "_tegrastats.jsonl")
            with side.open("w", encoding="utf-8") as fh:
                for s in self.tegrastats.samples:
                    fh.write(json.dumps(s) + "\n")
        return out
