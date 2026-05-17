from fastapi import FastAPI

from api.routes import cameras, events, health

app = FastAPI(
    title="Physical AI Safety Observability",
    description="Runtime-aware evidence pipeline for Physical AI safety events.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(cameras.router)
app.include_router(events.router)

