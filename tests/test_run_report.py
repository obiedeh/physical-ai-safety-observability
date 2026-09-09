from __future__ import annotations

import json
from pathlib import Path

from edge.adapters.mock_vlm import MockVLMAdapter
from edge.source_loader import load_source
from edge.worker import run_worker
from telemetry.run_report import RunRecorder, _percentile

ROOT = Path(__file__).resolve().parents[1]


def test_percentile_is_index_based() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0], 50) == 3.0
    assert _percentile([1.0, 2.0, 3.0, 4.0], 95) == 4.0
    assert _percentile([], 50) is None


def test_recorder_summarises_frames_and_events(tmp_path: Path) -> None:
    rec = RunRecorder(adapter_name="mock_vlm", model_version="v1")
    rec.record_frame(frame_id="f1", inference_ms=1.0, rule_ms=0.5, post_ms=None,
                     events=[{"rule_id": "ppe", "severity": "high"}])
    rec.record_frame(frame_id="f2", inference_ms=3.0, rule_ms=0.5, post_ms=2.0,
                     events=[{"rule_id": "ppe", "severity": "high"}, {"rule_id": "zone", "severity": "critical"}])
    rec.record_frame(frame_id="f3", inference_ms=5.0, rule_ms=0.5, post_ms=None, events=[])
    out = rec.write(tmp_path / "run.json", repo_root=ROOT)
    data = json.loads(out.read_text())
    assert data["schema"] == "run-report-v1"
    assert data["frames_processed"] == 3
    assert data["latency"]["inference"]["p50_ms"] == 3.0
    assert data["latency"]["inference"]["max_ms"] == 5.0
    assert data["latency"]["backend_post"]["n"] == 1
    assert data["events"] == {"total": 3, "by_rule": {"ppe": 2, "zone": 1}, "by_severity": {"critical": 1, "high": 2}}
    assert set(data["device"]) >= {"host", "machine", "python", "is_jetson", "git_sha"}
    assert data["memory"]["process_peak_rss_gb"] > 0
    assert data["source"]["sha256"] is None


def test_worker_populates_recorder_without_posting(tmp_path: Path) -> None:
    source = load_source(ROOT / "examples" / "sample_source.json")
    rec = RunRecorder(adapter_name="mock_vlm", model_version="mock-vlm-structured-v1",
                      source_path=str(ROOT / "examples" / "sample_source.json"))
    events = run_worker(source=source, backend="http://127.0.0.1:1", adapter=MockVLMAdapter(),
                        post_events=False, recorder=rec)
    data = json.loads(rec.write(tmp_path / "run.json", repo_root=ROOT).read_text())
    assert data["frames_processed"] == source.frame_count == len(rec.frames)
    assert data["events"]["total"] == len(events)
    assert len(data["source"]["sha256"]) == 64
    assert data["tegrastats"] is None
