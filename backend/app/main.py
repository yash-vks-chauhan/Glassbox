from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_db
from app.routers import ask, audit, determinism, llm_status, metrics


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="GlassBox", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)
    now = time.time()
    client = request.client.host if request.client else "unknown"
    window = _requests[client]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.rate_limit_per_min:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "GlassBox is busy. Please wait a minute and try again."
            },
        )
    window.append(now)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(ask.router)
app.include_router(audit.router)
app.include_router(metrics.router)
app.include_router(determinism.router)
app.include_router(llm_status.router)
