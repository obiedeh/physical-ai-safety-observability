from pathlib import Path

from pydantic import BaseModel

from edge.source_loader import load_json
from spatial.zones import Zone


class CameraCalibration(BaseModel):
    camera_id: str
    zones: list[Zone] = []


def load_calibration(path: str | Path) -> CameraCalibration:
    return CameraCalibration.model_validate(load_json(path))

