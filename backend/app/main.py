import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.storage import StorageNotConfigured
from app.routers import health, me, projects, references, styles, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title="Raw2Reel API",
    version="0.1.0",
    docs_url=None if settings.is_prod else "/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router, prefix="/v1")
app.include_router(styles.router, prefix="/v1")
app.include_router(references.router, prefix="/v1")
app.include_router(projects.router, prefix="/v1")
app.include_router(voice.router, prefix="/v1")


@app.exception_handler(StorageNotConfigured)
def storage_not_configured(_: Request, exc: StorageNotConfigured) -> JSONResponse:
    logging.getLogger(__name__).error("%s", exc)
    return JSONResponse(status_code=503, content={"detail": "File storage is not configured yet"})
