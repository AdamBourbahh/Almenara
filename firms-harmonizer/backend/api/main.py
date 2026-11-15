"""FastAPI application. Refuses to start without a usable cube (see duckdb_engine.resolve_cube)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

load_dotenv()

from backend.api.routes import router
from backend.db import nrt_poller
from backend.db.duckdb_engine import init_engine
from backend.api.request_limits import RequestLimits


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_engine()  # raises CubeNotAvailableError with a clear message -> server does not start
    nrt_poller.start_nrt_poller()
    try:
        yield
    finally:
        nrt_poller.stop_nrt_poller()


app = FastAPI(title="FIRMS Harmonizer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=1)
app.add_middleware(RequestLimits)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(','),
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                   expose_headers=["X-Cache", "Server-Timing"])
app.include_router(router)
