"""The evidence page builds from the committed artifacts and carries their numbers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_evidence_pages.py"


def _load():
    spec = importlib.util.spec_from_file_location("build_evidence_pages", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_page_builds_from_committed_artifacts(tmp_path: Path) -> None:
    mod = _load()
    runs = mod.load_runs(REPO / "reports")
    assert len(runs) >= 4
    rows = [mod.row_view(r) for r in runs]
    page = mod.build_page(rows, {}, "https://example.invalid/repo")
    headline = json.loads((REPO / "reports" / "thor" / "mock_30fps_no_post.json").read_text())
    assert f"{headline['frames_per_second']:,.3f}".rstrip("0") in page
    assert "thor/mock_30fps_no_post.json" in page
    assert "not measured" in page  # the precision/recall card


def test_bar_chart_handles_missing_values() -> None:
    mod = _load()
    svg = mod.bar_chart("t", [("a", [1.0, None])], ["x", "y"], "u")
    assert svg.startswith("<svg") and "not measured" in svg and svg.rstrip().endswith("</svg>")
