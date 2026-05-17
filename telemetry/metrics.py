from collections import defaultdict
from threading import Lock

from events.schemas import SafetyEvent, Severity


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self.counters: defaultdict[str, float] = defaultdict(float)
        self.gauges: defaultdict[str, float] = defaultdict(float)

    def increment(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self.counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self.gauges[name] = value

    def reset(self) -> None:
        with self._lock:
            self.counters.clear()
            self.gauges.clear()

    def observe_event(self, event: SafetyEvent) -> None:
        self.increment("events_total")
        if event.severity == Severity.CRITICAL:
            self.increment("critical_events_total")
        self.set_gauge("frames_processed_total", event.runtime_context.frames_processed)
        self.set_gauge("inference_latency_ms", event.runtime_context.latency_ms)
        self.set_gauge("latency_p95_ms", event.runtime_context.latency_p95_ms)
        self.set_gauge("latency_p99_ms", event.runtime_context.latency_p99_ms)
        self.set_gauge("queue_depth", event.runtime_context.queue_depth)
        self.set_gauge("frames_dropped_total", event.runtime_context.dropped_frames)
        self.set_gauge("memory_pressure", event.runtime_context.memory_pressure)
        self.set_gauge("gpu_memory_pressure", event.runtime_context.gpu_memory_pressure)

    _COUNTER_NAMES = frozenset({"events_total", "critical_events_total"})

    def render_prometheus(self) -> str:
        required = {
            "events_total": self.counters.get("events_total", 0.0),
            "critical_events_total": self.counters.get("critical_events_total", 0.0),
            "frames_processed_total": self.gauges.get("frames_processed_total", 0.0),
            "frames_dropped_total": self.gauges.get("frames_dropped_total", 0.0),
            "gpu_memory_pressure": self.gauges.get("gpu_memory_pressure", 0.0),
            "inference_latency_ms": self.gauges.get("inference_latency_ms", 0.0),
            "latency_p95_ms": self.gauges.get("latency_p95_ms", 0.0),
            "latency_p99_ms": self.gauges.get("latency_p99_ms", 0.0),
            "memory_pressure": self.gauges.get("memory_pressure", 0.0),
            "queue_depth": self.gauges.get("queue_depth", 0.0),
            "rule_eval_latency_ms": self.gauges.get("rule_eval_latency_ms", 0.0),
            "backend_post_latency_ms": self.gauges.get("backend_post_latency_ms", 0.0),
        }
        lines: list[str] = []
        for name, value in sorted(required.items()):
            metric_type = "counter" if name in self._COUNTER_NAMES else "gauge"
            lines.append(f"# TYPE {name} {metric_type}")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()
