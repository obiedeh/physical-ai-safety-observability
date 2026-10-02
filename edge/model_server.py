"""App-managed Cosmos-Reason2 vLLM containers on Jetson (and a catalog).

The only supported vLLM on JetPack 7 is NVIDIA's container, so "load model"
means ``docker run ... vllm serve``. Each catalog entry records whether the
launch uses ``--reasoning-parser``; constrained (json_schema) runs are only
allowed against servers started without it, and the model settings carry
that flag so the guard can refuse a mismatch.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_LOG_LINES = 500

JETSON_VLLM_IMAGE = os.getenv(
    "PHYSICAL_AI_VLLM_IMAGE", "ghcr.io/nvidia-ai-iot/vllm:0.14.0-r38.3-arm64-sbsa-cu130-24.04"
)
MODELS_DIR = os.getenv("PHYSICAL_AI_MODELS_DIR", "~/models")


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    label: str
    served_model_name: str
    model_dir: str                 # directory name under MODELS_DIR
    params_b: float
    gpu_memory_utilization: float  # fraction of unified memory vLLM reserves
    max_model_len: int = 8192
    reasoning_parser: str | None = None   # e.g. "qwen3"; None = no-reasoning (constrained OK)
    description: str = ""
    measured_note: str = ""

    def required_memory_gb(self, total_gb: float | None) -> float | None:
        if total_gb is None:
            return None
        return round(total_gb * self.gpu_memory_utilization + 2.0, 1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        key="cosmos-reason2-2b",
        label="Cosmos Reason 2 (2B), no reasoning parser",
        served_model_name="nvidia/cosmos-reason2-2b",
        model_dir="cosmos-reason2-2b",
        params_b=2.0,
        gpu_memory_utilization=0.25,
        description="Constrained (json_schema) runs supported.",
        measured_note="Thor 2026-09-09: 0.37 fps constrained, 60 frames (reports/thor).",
    ),
    CatalogEntry(
        key="cosmos-reason2-2b-reasoning",
        label="Cosmos Reason 2 (2B), reasoning parser (think mode)",
        served_model_name="nvidia/cosmos-reason2-2b",
        model_dir="cosmos-reason2-2b",
        params_b=2.0,
        gpu_memory_utilization=0.25,
        reasoning_parser="qwen3",
        description="For think-mode runs only; json_schema is NOT enforced by vLLM 0.14 here.",
        measured_note="Thor 2026-09-09: 0.15 fps think mode (reports/thor).",
    ),
    CatalogEntry(
        key="cosmos-reason2-8b",
        label="Cosmos Reason 2 (8B), no reasoning parser",
        served_model_name="nvidia/cosmos-reason2-8b",
        model_dir="cosmos-reason2-8b",
        params_b=8.0,
        gpu_memory_utilization=0.35,
        description="Constrained (json_schema) runs supported.",
        measured_note="Thor 2026-09-09: 0.23 fps constrained (reports/thor).",
    ),
]


def find_entry(key: str) -> CatalogEntry | None:
    return next((e for e in CATALOG if e.key == key or e.served_model_name == key), None)


def host_memory() -> tuple[float | None, float | None]:
    total = avail = None
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total = float(line.split()[1]) / (1024 * 1024)
                elif line.startswith("MemAvailable:"):
                    avail = float(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return total, avail


def is_jetson() -> bool:
    return Path("/etc/nv_tegra_release").exists()


def annotate_catalog() -> dict[str, Any]:
    total, avail = host_memory()
    docker = shutil.which("docker") is not None
    models_dir = Path(MODELS_DIR).expanduser()
    entries = []
    for entry in CATALOG:
        required = entry.required_memory_gb(total)
        present = (models_dir / entry.model_dir).exists()
        reasons: list[str] = []
        if not docker:
            reasons.append("docker not found on this host")
        if not present:
            reasons.append(f"weights not found at {models_dir / entry.model_dir}")
        if required is not None and avail is not None and required > avail:
            reasons.append(f"needs ~{required:.0f} GB, {avail:.0f} GB available")
        entries.append(
            {
                **entry.to_dict(),
                "required_memory_gb": required,
                "weights_present": present,
                "can_run": not reasons,
                "blocked_reasons": reasons,
                "constrained_ok": entry.reasoning_parser is None,
                "recommended": entry.key == "cosmos-reason2-2b",
            }
        )
    return {
        "host": {
            "is_jetson": is_jetson(),
            "has_docker": docker,
            "ram_total_gb": round(total, 1) if total else None,
            "ram_available_gb": round(avail, 1) if avail else None,
            "image": JETSON_VLLM_IMAGE,
            "models_dir": str(models_dir),
        },
        "models": entries,
    }


class ModelServerManager:
    """Owns one vLLM container started by this app; never touches other containers."""

    def __init__(self, container_name: str = "physical-ai-vllm") -> None:
        self.container_name = container_name
        self._proc: subprocess.Popen[str] | None = None
        self._entry: CatalogEntry | None = None
        self._port: int = 8000
        self._started_at: float | None = None
        self._log: list[str] = []
        self._lock = threading.RLock()

    def start(self, entry: CatalogEntry, *, port: int = 8000, model_path: str | None = None) -> dict:
        docker = shutil.which("docker")
        if not docker:
            raise FileNotFoundError("docker executable not found on this host")
        path = Path(model_path or (Path(MODELS_DIR).expanduser() / entry.model_dir)).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"model directory {path} does not exist")
        total, avail = host_memory()
        required = entry.required_memory_gb(total)
        if required is not None and avail is not None and required > avail:
            raise MemoryError(
                f"{entry.label} needs ~{required:.0f} GB but only {avail:.0f} GB is available."
            )
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                if self._entry is not None and self._entry.key == entry.key and self._port == port:
                    return self.status()
                self._stop_locked()
            subprocess.run([docker, "rm", "-f", self.container_name], capture_output=True, check=False)
            cache = Path("~/.cache/vllm").expanduser()
            cache.mkdir(parents=True, exist_ok=True)
            mount = f"/models/{path.name}"
            command = [
                docker, "run", "--rm", "--name", self.container_name,
                "--runtime", "nvidia", "--network", "host", "--ipc", "host",
                "-v", f"{path}:{mount}",
                "-v", f"{cache}:/root/.cache/vllm",
                JETSON_VLLM_IMAGE,
                "vllm", "serve", mount,
                "--served-model-name", entry.served_model_name,
                "--host", "0.0.0.0", "--port", str(port),
                "--gpu-memory-utilization", str(entry.gpu_memory_utilization),
                "--max-model-len", str(entry.max_model_len),
                "--media-io-kwargs", '{"video": {"num_frames": -1}}',
            ]
            if entry.reasoning_parser:
                command += ["--reasoning-parser", entry.reasoning_parser]
            self._proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            self._entry = entry
            self._port = port
            self._started_at = time.time()
            self._log = [" ".join(command)]
            threading.Thread(target=self._drain, daemon=True).start()
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_locked()
            return self.status()

    def _stop_locked(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            docker = shutil.which("docker")
            if docker:
                subprocess.run(
                    [docker, "stop", "-t", "20", self.container_name], capture_output=True, check=False
                )
            self._proc.terminate()
            try:
                self._proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None
        self._started_at = None
        self._log.append("managed model server stopped")

    def _drain(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            clean = line.rstrip()
            if clean:
                with self._lock:
                    self._log.append(clean)
                    if len(self._log) > MAX_LOG_LINES:
                        del self._log[: len(self._log) - MAX_LOG_LINES]

    def status(self) -> dict:
        with self._lock:
            entry = self._entry.to_dict() if self._entry else None
            base = {
                "container_name": self.container_name,
                "entry": entry,
                "endpoint": f"http://127.0.0.1:{self._port}/v1" if self._entry else None,
                "reasoning_parser": self._entry.reasoning_parser if self._entry else None,
                "log_tail": list(self._log[-60:]),
            }
            if self._proc is None:
                return {**base, "state": "stopped", "pid": None, "uptime_s": None, "exit_code": None}
            code = self._proc.poll()
            running = code is None
            return {
                **base,
                "state": "starting" if running else ("failed" if code else "stopped"),
                "pid": self._proc.pid,
                "uptime_s": round(time.time() - self._started_at, 1) if running and self._started_at else None,
                "exit_code": code,
            }
