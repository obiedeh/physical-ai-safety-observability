from typing import Any

from edge.adapters.base import VLMAdapter


class MockVLMAdapter(VLMAdapter):
    adapter_name = "mock_vlm"
    model_version = "mock-vlm-structured-v1"

    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        detections = frame_context.get("detections")
        if detections is None:
            detections = [
                {
                    "label": "person",
                    "confidence": 0.92,
                    "bbox": [80, 80, 150, 240],
                    "ppe": {"hard_hat": False, "vest": True},
                },
                {
                    "label": "robot",
                    "confidence": 0.88,
                    "bbox": [145, 95, 230, 245],
                },
                {
                    "label": "pallet",
                    "confidence": 0.81,
                    "bbox": [20, 260, 180, 330],
                    "blocking_emergency_path": True,
                },
            ]
        return {
            "adapter_name": self.adapter_name,
            "model_version": self.model_version,
            "detections": detections,
        }

