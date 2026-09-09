from __future__ import annotations

from pathlib import Path

import pytest

import edge.worker as worker_mod
from edge.adapters.openai_compatible import CosmosReason2Adapter
from edge.source_loader import load_source

ROOT = Path(__file__).resolve().parents[1]


def test_worker_posts_one_batch_per_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    source = load_source(ROOT / "examples" / "sample_source.json")
    batches: list[list[dict]] = []
    singles: list[dict] = []
    monkeypatch.setattr(worker_mod, "post_events_batch", lambda backend, payloads, **kw: batches.append(payloads))
    monkeypatch.setattr(worker_mod, "post_event", lambda backend, payload, **kw: singles.append(payload))
    monkeypatch.setattr(worker_mod, "post_feedback", lambda backend, payload, **kw: None)
    events = worker_mod.run_worker(source=source, backend="http://backend", post_events=True, post_batch=True)
    assert singles == []
    assert len(batches) == source.frame_count
    assert sum(len(b) for b in batches) == len(events)


def test_cosmos_adapter_honours_max_tokens_and_no_think(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "<answer>{\"detections\": []}</answer>"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr("edge.adapters.openai_compatible.httpx.post", fake_post)
    adapter = CosmosReason2Adapter(endpoint="http://x/v1", max_tokens=256, think=False)
    out = adapter.analyze_frame({"camera_id": "c", "frame_id": "f", "frame_bytes": b"\xff\xd8"})
    payload = captured["payload"]
    assert payload["max_tokens"] == 256
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    prompt = payload["messages"][1]["content"][-1]["text"]
    assert "<think>" not in prompt and "Do not think aloud" in prompt
    assert out["detections"] == [] and out["raw_response"]["usage"]["completion_tokens"] == 1

    adapter_think = CosmosReason2Adapter(endpoint="http://x/v1")
    adapter_think.analyze_frame({"camera_id": "c", "frame_id": "f", "frame_bytes": b"\xff\xd8"})
    assert captured["payload"]["max_tokens"] == 4096 and "chat_template_kwargs" not in captured["payload"]
