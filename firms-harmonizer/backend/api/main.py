"""FastAPI application. Refuses to start without a usable cube (see duckdb_engine.resolve_cube)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

load_dotenv()

from backend.api.routes import router
from backend.db.duckdb_engine import init_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_engine()  # raises CubeNotAvailableError with a clear message -> server does not start
    yield


app = FastAPI(title="FIRMS Harmonizer API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=1)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Cache", "Server-Timing"])
app.include_router(router)
