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


def _arg_after(args: list[str], flag: str) -> str | None:
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


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
    """Owns one vLLM container started by this app; never touches other containers.

    The container is detached (``docker run -d``) so it outlives an API restart:
    another app on the device may be using the same model server. On start-up
    the manager adopts a container of its name that is still running; only an
    explicit stop (UI / API) removes it.
    """

    def __init__(self, container_name: str = "physical-ai-vllm") -> None:
        self.container_name = container_name
        self._proc: subprocess.Popen[str] | None = None
        self._entry: CatalogEntry | None = None
        self._port: int = 8000
        self._started_at: float | None = None
        self._log: list[str] = []
        self._lock = threading.RLock()
        self._adopted = self._adopt_running()

    def _adopt_running(self) -> bool:
        docker = shutil.which("docker")
        if not docker:
            return False
        probe = subprocess.run(
            [docker, "inspect", "--format",
             "{{.State.Running}}|{{.Config.Image}}|{{join .Config.Cmd \" \"}}", self.container_name],
            capture_output=True, text=True, check=False,
        )
        if probe.returncode != 0:
            return False
        running, _image, cmd = (probe.stdout.strip().split("|", 2) + ["", ""])[:3]
        if running != "true":
            return False
        served = _arg_after(cmd.split(), "--served-model-name")
        port = _arg_after(cmd.split(), "--port")
        parser = _arg_after(cmd.split(), "--reasoning-parser")
        entry = next(
            (e for e in CATALOG if e.served_model_name == served
             and (e.reasoning_parser or None) == (parser or None)),
            None,
        )
        self._entry = entry
        self._port = int(port) if port and port.isdigit() else 8000
        self._started_at = time.time()
        self._log = [f"adopted running container {self.container_name}: {cmd}"]
        return True

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
            if self._container_running():
                if self._entry is not None and self._entry.key == entry.key and self._port == port:
                    return self.status()
                self._stop_locked()
            subprocess.run([docker, "rm", "-f", self.container_name], capture_output=True, check=False)
            cache = Path("~/.cache/vllm").expanduser()
            cache.mkdir(parents=True, exist_ok=True)
            mount = f"/models/{path.name}"
            command = [
                docker, "run", "-d", "--rm", "--name", self.container_name,
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
            launched = subprocess.run(command, capture_output=True, text=True, check=False)
            self._entry = entry
            self._port = port
            self._started_at = time.time()
            self._adopted = False
            self._log = [" ".join(command), launched.stdout.strip() or launched.stderr.strip()]
            if launched.returncode != 0:
                raise RuntimeError(f"docker run failed: {launched.stderr.strip()[:300]}")
            # Follow the container log so the UI can show progress.
            self._proc = subprocess.Popen(
                [docker, "logs", "-f", self.container_name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            threading.Thread(target=self._drain, daemon=True).start()
            return self.status()

    def stop(self) -> dict:
        """Explicit stop from the UI/API: removes the container."""
        with self._lock:
            self._stop_locked()
            return self.status()

    def detach(self) -> None:
        """Called on API shutdown: leave the container running, stop following its log."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None

    def _container_running(self) -> bool:
        docker = shutil.which("docker")
        if not docker:
            return False
        probe = subprocess.run(
            [docker, "inspect", "--format", "{{.State.Running}}", self.container_name],
            capture_output=True, text=True, check=False,
        )
        return probe.returncode == 0 and probe.stdout.strip() == "true"

    def _stop_locked(self) -> None:
        docker = shutil.which("docker")
        if docker and self._container_running():
            subprocess.run(
                [docker, "stop", "-t", "20", self.container_name], capture_output=True, check=False
            )
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
        self._started_at = None
        self._entry = None
        self._adopted = False
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
            running = self._container_running() if (self._entry or self._started_at) else False
            base = {
                "container_name": self.container_name,
                "entry": entry,
                "endpoint": f"http://127.0.0.1:{self._port}/v1" if running else None,
                "reasoning_parser": self._entry.reasoning_parser if self._entry else None,
                "adopted": self._adopted,
                "log_tail": list(self._log[-60:]),
            }
            if not running:
                if self._started_at is not None:
                    # Launched by us but no longer running: the container exited.
                    self._started_at = None
                    return {**base, "state": "failed", "pid": None, "uptime_s": None, "exit_code": 1}
                return {**base, "state": "stopped", "pid": None, "uptime_s": None, "exit_code": None}
            return {
                **base,
                "state": "starting",
                "pid": self._proc.pid if self._proc else None,
                "uptime_s": round(time.time() - self._started_at, 1) if self._started_at else None,
                "exit_code": None,
            }
