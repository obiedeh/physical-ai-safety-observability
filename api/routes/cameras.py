from fastapi import APIRouter

from api.models.camera import Camera, CameraRegistration
from api.services.store import store

router = APIRouter()


@router.post("/cameras", response_model=Camera)
def register_camera(camera: CameraRegistration) -> Camera:
    return store.register_camera(camera)


@router.get("/cameras", response_model=list[Camera])
def list_cameras() -> list[Camera]:
    return store.list_cameras()

