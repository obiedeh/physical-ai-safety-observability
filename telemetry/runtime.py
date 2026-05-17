from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from events.schemas import RuntimeContext, RuntimeStatus


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1)))
    return ordered[index]


def host_memory_pressure() -> float:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return 0.0
    values: dict[str, float] = {}
    for line in meminfo.read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = float(rest.strip().split()[0])
    total = values.get("MemTotal", 0.0)
    available = values.get("MemAvailable", 0.0)
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, 1 - available / total))


@dataclass
class RuntimeMonitor:
    frames_processed: int = 0
    frames_dropped: int = 0
    queue_depth: int = 0
    inference_latency_ms: float = 0.0
    rule_eval_latency_ms: float = 0.0
    backend_post_latency_ms: float = 0.0
    gpu_memory_pressure: float = 0.0
    thermal_pressure: float = 0.0
    notes: list[str] = field(default_factory=list)
    latency_samples_ms: list[float] = field(default_factory=list)

    def record_latency(self, latency_ms: float) -> None:
        self.latency_samples_ms.append(latency_ms)
        if len(self.latency_samples_ms) > 512:
            self.latency_samples_ms = self.latency_samples_ms[-512:]

    def snapshot(self) -> RuntimeContext:
        status = RuntimeStatus.NOMINAL
        notes = list(self.notes)
        memory_pressure = host_memory_pressure()
        if (
            self.frames_dropped > 0
            or self.queue_depth > 5
            or memory_pressure >= 0.85
            or self.gpu_memory_pressure >= 0.75
            or self.thermal_pressure >= 0.75
        ):
            status = RuntimeStatus.DEGRADED
        if self.gpu_memory_pressure >= 0.9 or self.thermal_pressure >= 0.9:
            status = RuntimeStatus.CRITICAL
        return RuntimeContext(
            frames_processed=self.frames_processed,
            latency_ms=self.inference_latency_ms + self.rule_eval_latency_ms,
            latency_p95_ms=_percentile(self.latency_samples_ms, 95),
            latency_p99_ms=_percentile(self.latency_samples_ms, 99),
            queue_depth=self.queue_depth,
            dropped_frames=self.frames_dropped,
            memory_pressure=memory_pressure,
            gpu_memory_pressure=self.gpu_memory_pressure,
            thermal_pressure=self.thermal_pressure,
            runtime_status=status,
            notes=notes,
        )


class Timer:
    def __enter__(self) -> "Timer":
        self._start = perf_counter()
        self.elapsed_ms = 0.0
        return self

    def __exit__(self, *_args: object) -> None:
        self.elapsed_ms = (perf_counter() - self._start) * 1000
