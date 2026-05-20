import argparse
import logging
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx

from edge.adapters.base import VLMAdapter
from edge.adapters.mock_vlm import MockVLMAdapter
from edge.adapters.openai_compatible import CosmosReason2Adapter, OpenAICompatibleAdapter
from edge.frame_sampler import sample_frames
from edge.source_loader import VideoSource, load_source
from events.schemas import PersonPPEFeedback
from runtime_settings import RuntimeSettings, load_settings
from rules.engine import SafetyPolicyEngine
from telemetry.logging import configure_logging, log_event
from telemetry.metrics import metrics
from telemetry.runtime import RuntimeMonitor, Timer

logger = logging.getLogger("edge.worker")


def build_adapter(settings: RuntimeSettings) -> VLMAdapter:
    worker = settings.worker
    if worker.adapter == "mock":
        return MockVLMAdapter()
    if worker.adapter == "openai-compatible":
        api_key = os.getenv(worker.api_key_env) if worker.api_key_env else None
        return OpenAICompatibleAdapter(
            endpoint=worker.adapter_endpoint,
            model=worker.model,
            api_key=api_key,
            timeout=worker.inference_timeout_seconds,
        )
    if worker.adapter == "cosmos-reason2":
        api_key = os.getenv(worker.api_key_env) if worker.api_key_env else None
        return CosmosReason2Adapter(
            endpoint=worker.adapter_endpoint,
            model=worker.model,
            api_key=api_key,
            timeout=worker.inference_timeout_seconds,
        )
    raise ValueError(f"unsupported adapter: {worker.adapter}")


def post_event(backend: str, event_payload: dict[str, Any], *, retries: int = 3) -> None:
    url = f"{backend.rstrip('/')}/events"
    for attempt in range(retries):
        try:
            response = httpx.post(url, json=event_payload, timeout=10)
            response.raise_for_status()
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == retries - 1:
                raise
        except (httpx.NetworkError, httpx.TimeoutException):
            if attempt == retries - 1:
                raise
        time.sleep(0.5 * (2**attempt))


def post_feedback(backend: str, feedback_payload: dict[str, Any], *, retries: int = 3) -> None:
    url = f"{backend.rstrip('/')}/feedback"
    for attempt in range(retries):
        try:
            response = httpx.post(url, json=feedback_payload, timeout=10)
            response.raise_for_status()
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == retries - 1:
                raise
        except (httpx.NetworkError, httpx.TimeoutException):
            if attempt == retries - 1:
                raise
        time.sleep(0.5 * (2**attempt))


def run_worker(
    *,
    source: VideoSource,
    backend: str,
    adapter: VLMAdapter | None = None,
    post_events: bool = True,
    continuous: bool = False,
    feedback_interval_seconds: float = 2.0,
    max_cycles: int | None = None,
    clean_feedback_terminal: bool = False,
) -> list[dict[str, Any]]:
    adapter = adapter or MockVLMAdapter()
    engine = SafetyPolicyEngine(zones=source.zones)
    runtime = RuntimeMonitor()
    emitted: list[dict[str, Any]] = []

    for frame_context in iter_frame_contexts(source, continuous=continuous, max_cycles=max_cycles):
        cycle_started = time.monotonic()
        runtime.frames_processed += 1
        metrics.increment("frames_processed_total")
        with Timer() as inference_timer:
            analysis = adapter.analyze_frame(frame_context)
        runtime.inference_latency_ms = inference_timer.elapsed_ms
        runtime.record_latency(runtime.inference_latency_ms)

        feedback = build_person_ppe_feedback(
            frame_context=frame_context, detections=analysis.get("detections", [])
        )
        feedback_payload = feedback.model_dump(mode="json")
        if post_events:
            post_feedback(backend, feedback_payload)
        if clean_feedback_terminal:
            print(f"\r{feedback.message:<32}", end="", flush=True)
        else:
            log_event(
                logger,
                "person_ppe_feedback",
                camera_id=source.camera_id,
                frame_id=frame_context["frame_id"],
                feedback=feedback.message,
            )

        with Timer() as rule_timer:
            events = engine.evaluate(
                frame_context=frame_context,
                analysis=analysis,
                runtime_context=runtime.snapshot(),
            )
        runtime.rule_eval_latency_ms = rule_timer.elapsed_ms
        runtime.record_latency(runtime.inference_latency_ms + runtime.rule_eval_latency_ms)
        metrics.set_gauge("rule_eval_latency_ms", rule_timer.elapsed_ms)

        for event in events:
            payload = event.model_dump(mode="json")
            if post_events:
                with Timer() as post_timer:
                    post_event(backend, payload)
                runtime.backend_post_latency_ms = post_timer.elapsed_ms
                metrics.set_gauge("backend_post_latency_ms", post_timer.elapsed_ms)
            emitted.append(payload)
            if not clean_feedback_terminal:
                log_event(
                    logger,
                    "safety_event_emitted",
                    event_id=event.event_id,
                    rule_id=event.rule_id,
                    severity=event.severity,
                    confidence=event.confidence,
                )

        if continuous:
            sleep_remaining = feedback_interval_seconds - (time.monotonic() - cycle_started)
            if sleep_remaining > 0:
                time.sleep(sleep_remaining)
    return emitted


def iter_frame_contexts(
    source: VideoSource, *, continuous: bool, max_cycles: int | None = None
) -> Iterator[dict[str, Any]]:
    emitted = 0
    while True:
        frame_emitted = False
        for frame_context in sample_frames(source):
            frame_emitted = True
            yield frame_context
            emitted += 1
            if max_cycles is not None and emitted >= max_cycles:
                return
            if continuous:
                break
        if not continuous:
            return
        if not frame_emitted:
            time.sleep(0.5)


def build_person_ppe_feedback(
    *, frame_context: dict[str, Any], detections: list[dict[str, Any]]
) -> PersonPPEFeedback:
    return PersonPPEFeedback(
        camera_id=frame_context["camera_id"],
        frame_id=frame_context["frame_id"],
        timestamp=frame_context["timestamp"],
        message=person_ppe_feedback(detections),
        detections=detections,
    )


def person_ppe_feedback(detections: list[dict[str, Any]]) -> str:
    people = [item for item in detections if item.get("label") == "person"]
    if not people:
        return "No Person Detected"
    if any(
        not person.get("ppe", {}).get("hard_hat") or not person.get("ppe", {}).get("vest")
        for person in people
    ):
        return "Person Detected with No PPE"
    return "Person Detected with PPE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run edge safety observability worker.")
    parser.add_argument("--config", help="Path to runtime config JSON")
    parser.add_argument("--source", required=True, help="Path to source JSON")
    parser.add_argument("--backend", help="Backend base URL")
    parser.add_argument(
        "--adapter",
        choices=["mock", "openai-compatible", "cosmos-reason2"],
        help="Inference adapter to use",
    )
    parser.add_argument(
        "--adapter-endpoint",
        help="OpenAI-compatible base URL for real VLM/reasoning adapters",
    )
    parser.add_argument(
        "--model",
        help="Model name passed to the OpenAI-compatible endpoint",
    )
    parser.add_argument(
        "--api-key-env",
        help="Environment variable containing adapter API key, if required",
    )
    parser.add_argument("--no-post", action="store_true", help="Generate events without posting")
    parser.add_argument("--once", action="store_true", help="Process the source once and then exit")
    parser.add_argument(
        "--feedback-interval-seconds",
        type=float,
        help="Seconds between person/PPE feedback checks in continuous mode",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print structured worker logs instead of clean feedback-only output",
    )
    return parser


def settings_from_args(args: argparse.Namespace) -> RuntimeSettings:
    settings = load_settings(args.config)
    if args.backend:
        settings.worker.backend = args.backend
    if args.adapter:
        settings.worker.adapter = args.adapter
    if args.adapter_endpoint:
        settings.worker.adapter_endpoint = args.adapter_endpoint
    if args.model:
        settings.worker.model = args.model
    if args.api_key_env:
        settings.worker.api_key_env = args.api_key_env
    if args.no_post:
        settings.worker.post_events = False
    if args.once:
        settings.worker.continuous = False
    if args.feedback_interval_seconds is not None:
        settings.worker.feedback_interval_seconds = args.feedback_interval_seconds
    if args.verbose:
        settings.worker.clean_feedback_terminal = False
    return settings


def main() -> None:
    args = build_parser().parse_args()
    settings = settings_from_args(args)
    configure_logging(getattr(logging, settings.app.log_level.upper()))
    if settings.worker.clean_feedback_terminal:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logger.setLevel(logging.WARNING)
    source = load_source(args.source)
    adapter = build_adapter(settings)
    events = run_worker(
        source=source,
        backend=settings.worker.backend,
        adapter=adapter,
        post_events=settings.worker.post_events,
        continuous=settings.worker.continuous,
        feedback_interval_seconds=settings.worker.feedback_interval_seconds,
        clean_feedback_terminal=settings.worker.clean_feedback_terminal,
    )
    if settings.worker.clean_feedback_terminal:
        print()
    else:
        log_event(logger, "worker_complete", events=len(events), camera_id=source.camera_id)


if __name__ == "__main__":
    main()
