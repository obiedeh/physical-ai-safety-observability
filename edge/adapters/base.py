from abc import ABC, abstractmethod
from typing import Any


class VLMAdapter(ABC):
    adapter_name = "base"
    model_version = "unknown"

    @abstractmethod
    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        """Return structured detections for a frame."""

