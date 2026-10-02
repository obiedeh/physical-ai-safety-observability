"""Model settings, hot-swap, API-key masking, catalog preflight and the constrained-mode guard."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.edge import edge_service
from edge import model_guard
from edge.adapters.mock_vlm import MockVLMAdapter
from edge.adapters.openai_compatible import CosmosReason2Adapter, OpenAICompatibleAdapter
from edge.config_models import ModelSettings
from edge.model_server import CatalogEntry, annotate_catalog, find_entry
from edge.service import build_adapter_from_settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_model():
    yield
    client.put("/config/model", json={"backend": "mock"})


def test_build_adapter_switches_backend() -> None:
    assert isinstance(build_adapter_from_settings(ModelSettings(backend="mock")), MockVLMAdapter)
    cosmos = build_adapter_from_settings(
        ModelSettings(backend="cosmos-reason2", endpoint="http://127.0.0.1:8000", model="m",
                      json_schema=True, think=False, max_tokens=256)
    )
    assert isinstance(cosmos, CosmosReason2Adapter)
    assert cosmos.endpoint == "http://127.0.0.1:8000/v1"
    assert cosmos.json_schema is True and cosmos.think is False and cosmos.max_tokens == 256
    generic = build_adapter_from_settings(ModelSettings(backend="openai-compatible", model="x"))
    assert isinstance(generic, OpenAICompatibleAdapter)


def test_put_model_persists_hot_swaps_and_masks_key(monkeypatch) -> None:
    monkeypatch.setattr(edge_service, "run_guard", lambda: None)  # no network in tests
    r = client.put(
        "/config/model",
        json={"backend": "cosmos-reason2", "endpoint": "http://127.0.0.1:8000",
              "model": "nvidia/cosmos-reason2-8b", "api_key": "nvapi-SECRET", "json_schema": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["has_api_key"] is True and r.json()["api_key"] == ""
    assert "nvapi-SECRET" not in r.text
    assert isinstance(edge_service.adapter, CosmosReason2Adapter)
    assert edge_service.adapter.model_version == "nvidia/cosmos-reason2-8b"
    assert edge_service.model_api_key() == "nvapi-SECRET"
    again = client.get("/config/model").json()
    assert again["model"] == "nvidia/cosmos-reason2-8b" and again["has_api_key"] is True
    status = client.get("/runtime/status").json()["model"]
    assert status["model"] == "nvidia/cosmos-reason2-8b" and "nvapi" not in str(status)


def test_json_schema_against_reasoning_parser_is_refused() -> None:
    r = client.put(
        "/config/model",
        json={"backend": "cosmos-reason2", "model": "m", "json_schema": True,
              "reasoning_parser": True},
    )
    assert r.status_code == 422
    assert "reasoning-parser" in r.text


def test_inference_settings_round_trip() -> None:
    r = client.put("/config/inference", json={"interval_ms": 500, "width": 800, "height": 450})
    assert r.status_code == 200, r.text
    assert client.get("/config/inference").json()["interval_ms"] == 500
    assert client.get("/runtime/status").json()["inference"]["width"] == 800
    client.put("/config/inference", json={})


def test_catalog_preflight_and_constrained_flags(monkeypatch) -> None:
    monkeypatch.setattr("edge.model_server.host_memory", lambda: (122.0, 20.0))
    monkeypatch.setattr("edge.model_server.shutil.which", lambda name: "/usr/bin/docker")
    data = annotate_catalog()
    models = {m["key"]: m for m in data["models"]}
    assert models["cosmos-reason2-2b"]["constrained_ok"] is True
    assert models["cosmos-reason2-2b-reasoning"]["constrained_ok"] is False
    # 0.35 * 122 + 2 = 44.7 GB needed; only 20 GB available → blocked.
    assert models["cosmos-reason2-8b"]["can_run"] is False
    assert any("needs" in r for r in models["cosmos-reason2-8b"]["blocked_reasons"])
    assert models["cosmos-reason2-2b"]["recommended"] is True
    assert find_entry("nvidia/cosmos-reason2-8b") is not None


def test_server_start_refuses_constrained_with_reasoning_entry(monkeypatch) -> None:
    started: list[CatalogEntry] = []
    monkeypatch.setattr(
        edge_service.model_server, "start",
        lambda entry, port=8000, model_path=None: started.append(entry) or {"state": "starting"},
    )
    monkeypatch.setattr(edge_service, "run_guard", lambda: None)
    r = client.post(
        "/models/server/start",
        json={"key": "cosmos-reason2-2b-reasoning", "json_schema": True},
    )
    assert r.status_code == 422
    r = client.post("/models/server/start", json={"key": "cosmos-reason2-2b", "json_schema": True})
    assert r.status_code == 200, r.text
    assert r.json()["applied"]["json_schema"] is True
    assert r.json()["applied"]["reasoning_parser"] is False
    assert started[-1].key == "cosmos-reason2-2b"
    assert client.post("/models/server/start", json={"key": "nope"}).status_code == 404


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._payload


def test_guard_detects_server_that_ignores_json_schema(monkeypatch) -> None:
    monkeypatch.setattr(
        model_guard.httpx, "post",
        lambda *a, **k: _FakeResponse({"choices": [{"message": {"content": "banana"}}]}),
    )
    result = model_guard.probe_constrained("http://127.0.0.1:8000/v1", "m")
    assert not result.ok and result.constrained_enforced is False
    assert "reasoning-parser" in result.message


def test_guard_accepts_enforcing_server(monkeypatch) -> None:
    monkeypatch.setattr(
        model_guard.httpx, "post",
        lambda *a, **k: _FakeResponse(
            {"choices": [{"message": {"content": '{"status": "grammar_ok"}'}}]}
        ),
    )
    result = model_guard.probe_constrained("http://127.0.0.1:8000/v1", "m")
    assert result.ok and result.constrained_enforced is True


def test_guard_check_server_reports_model_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        model_guard.httpx, "get",
        lambda *a, **k: _FakeResponse({"data": [{"id": "nvidia/cosmos-reason2-2b"}]}),
    )
    result = model_guard.check_server("http://127.0.0.1:8000/v1", "nvidia/cosmos-reason2-8b")
    assert not result.ok and result.stage == "model"
    ok = model_guard.check_server("http://127.0.0.1:8000/v1", "nvidia/cosmos-reason2-2b")
    assert ok.ok

    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(model_guard.httpx, "get", boom)
    down = model_guard.check_server("http://127.0.0.1:8000/v1", "m")
    assert not down.ok and down.stage == "server"
