"""Process-wide EdgeService singleton (the API hosts the camera workers)."""
from __future__ import annotations

import os

from api.services.store import store
from edge.service import EdgeService
from runtime_settings import load_settings

_settings = load_settings()

edge_service = EdgeService(
    store,
    backend=os.getenv("PHYSICAL_AI_BACKEND", _settings.worker.backend),
    post_enabled=os.getenv("PHYSICAL_AI_POST_EVENTS", "1") != "0",
    reports_dir=os.getenv("PHYSICAL_AI_REPORTS_DIR", "reports"),
)
