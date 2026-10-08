import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import cameras, config, events, health, models, runtime, stream
from api.services.edge import edge_service
from edge.redaction import install_logging_filter


@asynccontextmanager
async def lifespan(app: FastAPI):
    install_logging_filter()
    # The API hosts the camera workers; PHYSICAL_AI_AUTOSTART=0 keeps tests and
    # CLI-only deployments from opening cameras.
    if os.getenv("PHYSICAL_AI_AUTOSTART", "1") != "0":
        edge_service.start()
    yield
    edge_service.stop()


app = FastAPI(
    title="Physical AI Safety Observability",
    description="Runtime-aware evidence pipeline for Physical AI safety events.",
    version="0.3.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Standard 422 body, except camera routes drop the echoed input.

    A rejected camera payload may hold a password or a pasted RTSP link with
    credentials; those must never come back in a response.
    """
    errors = exc.errors()
    if request.url.path.startswith("/config/cameras"):
        errors = [{k: v for k, v in e.items() if k not in {"input", "url", "ctx"}} for e in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})

app.include_router(health.router)
app.include_router(cameras.router)
app.include_router(events.router)
app.include_router(config.router)
app.include_router(models.router)
app.include_router(stream.router)
app.include_router(runtime.router)

# ── Operator UI (built with `pnpm build` in web/; served when present) ────────
_web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if _web_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_web_dist / "assets")), name="web-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/ui/{path:path}", include_in_schema=False)
    async def spa(path: str = "") -> FileResponse:
        return FileResponse(str(_web_dist / "index.html"))
