from events.schemas import RuntimeContext, Severity


def require_review(severity: Severity, confidence: float, runtime: RuntimeContext) -> bool:
    return severity in {Severity.HIGH, Severity.CRITICAL} or confidence < 0.85 or (
        runtime.runtime_status != "nominal"
    )


def adjust_confidence(base_confidence: float, runtime: RuntimeContext) -> float:
    penalty = 0.0
    if runtime.runtime_status == "degraded":
        penalty += 0.08
    if runtime.runtime_status == "critical":
        penalty += 0.18
    penalty += min(runtime.dropped_frames * 0.01, 0.1)
    return max(0.0, min(1.0, base_confidence - penalty))

