from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.database.session import get_session
from app.modules.auth.router import router as auth_router
from app.modules.clients.router import router as clients_router
from app.modules.market.router import router as market_router
from app.modules.opportunities.router import router as opportunities_router
from app.modules.organizations.router import router as organizations_router
from app.modules.scraping.router import router as scraping_router
from app.modules.extension.router import router as extension_router


# ── Rate limiter ───────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    # Recuperare joburi blocate (crashed fără să termine)
    from app.modules.scraping.orchestrator import recover_stuck_jobs
    recover_stuck_jobs(timeout_minutes=60)

    # Pornire scheduler
    from app.modules.scraping.scheduler import setup_scheduler
    setup_scheduler()

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    from app.modules.scraping.scheduler import teardown_scheduler
    teardown_scheduler()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    redirect_slashes=False,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — permite doar frontend-ul local în development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Extension-Key"],
)

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api/v1")
app.include_router(market_router, prefix="/api/v1")
app.include_router(organizations_router, prefix="/api/v1")
app.include_router(clients_router, prefix="/api/v1")
app.include_router(opportunities_router, prefix="/api/v1")
app.include_router(scraping_router, prefix="/api/v1")
app.include_router(extension_router, prefix="/api/v1")


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "status": "running",
        "environment": settings.environment,
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def database_health_check(session: Session = Depends(get_session)):
    result = session.execute(text("SELECT 1")).scalar()
    return {"status": "ok", "database": result}
