from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (register tables)
from .config import settings, validate_settings
from .routers import accounts, auth, journals, masters, transactions
from .security import require_auth


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings()  # schema is created by Alembic: `alembic upgrade head`
    yield


app = FastAPI(
    title="Fish Business Daily Journal API", version="1.1.0", lifespan=lifespan,
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
for r in (masters.router, journals.router, transactions.router, accounts.router):
    app.include_router(r, prefix="/api/v1", dependencies=[Depends(require_auth)])


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
