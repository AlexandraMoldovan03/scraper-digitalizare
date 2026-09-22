"""
Scraping router — endpoints pentru joburi de scraping.

POST /scraping/jobs            → declanșează un job (sursă specifică sau "all")
GET  /scraping/jobs/latest     → ultimul job + cooldown per sursă
GET  /scraping/jobs/{job_id}   → status detaliat
GET  /scraping/status          → status toate sursele simultan
"""
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.database.session import get_session
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.market.models import Source
from app.modules.scraping.models import ScrapeJob
from app.modules.scraping.orchestrator import ACTIVE_STATUSES, run_scrape_job
from app.modules.scraping.registry import is_registered, list_source_keys
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scraping", tags=["scraping"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class ScrapeJobRequest(BaseModel):
    source: str = "publi24"


class ScrapeJobOut(BaseModel):
    id: int
    source_name: str | None
    trigger_type: str
    status: str
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    pages_total: int
    pages_processed: int
    listings_found: int
    listings_created: int
    listings_updated: int
    listings_unchanged: int
    listings_failed: int
    warnings_count: int
    error_message: str | None
    already_active: bool = False

    model_config = {"from_attributes": True}


class LatestJobOut(BaseModel):
    active_job: ScrapeJobOut | None
    last_completed: ScrapeJobOut | None
    cooldown_remaining_seconds: int


class SourceStatusOut(BaseModel):
    """Status complet pentru o sursă: activ în DB, job activ, ultimul job, cooldown."""
    source_key: str
    is_active: bool
    display_name: str
    active_job: ScrapeJobOut | None
    last_completed: ScrapeJobOut | None
    cooldown_remaining_seconds: int


class MultiJobResponse(BaseModel):
    """Răspuns pentru source=all: un job per sursă activă."""
    jobs: list[ScrapeJobOut]
    skipped: list[dict]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _job_to_out(job: ScrapeJob, already_active: bool = False) -> ScrapeJobOut:
    return ScrapeJobOut(
        id=job.id,
        source_name=job.source_name,
        trigger_type=job.trigger_type,
        status=job.status,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        pages_total=job.pages_total,
        pages_processed=job.pages_processed,
        listings_found=job.listings_found,
        listings_created=job.listings_created,
        listings_updated=job.listings_updated,
        listings_unchanged=job.listings_unchanged,
        listings_failed=job.listings_failed,
        warnings_count=job.warnings_count,
        error_message=job.error_message,
        already_active=already_active,
    )


def _get_active_job(session: Session, source_name: str) -> ScrapeJob | None:
    return session.exec(
        select(ScrapeJob)
        .where(ScrapeJob.source_name == source_name)
        .where(ScrapeJob.status.in_(list(ACTIVE_STATUSES)))
        .order_by(ScrapeJob.queued_at.desc())
    ).first()


def _get_last_completed(session: Session, source_name: str) -> ScrapeJob | None:
    return session.exec(
        select(ScrapeJob)
        .where(ScrapeJob.source_name == source_name)
        .where(ScrapeJob.status.in_(["completed", "success"]))
        .order_by(ScrapeJob.finished_at.desc())
    ).first()


def _cooldown_remaining(last_completed: ScrapeJob | None) -> int:
    if not last_completed or not last_completed.finished_at:
        return 0
    elapsed = (datetime.utcnow() - last_completed.finished_at).total_seconds()
    remaining = settings.scrape_manual_cooldown_minutes * 60 - elapsed
    return max(0, int(remaining))


def _get_db_source(session: Session, source_key: str) -> Source | None:
    """Lookup sursă după slug; fallback după name (ilike)."""
    source = session.exec(
        select(Source).where(Source.slug == source_key)
    ).first()
    if not source:
        source = session.exec(
            select(Source).where(Source.name.ilike(source_key))
        ).first()
    return source


_DISPLAY_NAMES: dict[str, str] = {
    "publi24": "Publi24",
    "imobiliare_ro": "Imobiliare.ro",
    "romimo": "Romimo",
    "storia": "Storia",
}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/jobs", status_code=202)
def trigger_scrape_job(
    body: ScrapeJobRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    _: User = Depends(require_roles("owner", "manager", "agent")),
):
    """
    Declanșează manual un job de scraping.

    - source specific → ScrapeJobOut (202)
    - source=all      → MultiJobResponse (202)
    - sursă inactivă  → 400
    - job activ       → ScrapeJobOut cu already_active=true
    - cooldown        → 429
    """
    source = body.source.lower().strip()

    # ── source=all ────────────────────────────────────────────────────────────
    if source == "all":
        jobs_out = []
        skipped = []

        for key in list_source_keys():
            db_source = _get_db_source(session, key)
            if not db_source or not db_source.is_active:
                skipped.append({"source": key, "reason": "source_inactive"})
                continue

            active = _get_active_job(session, key)
            if active:
                jobs_out.append(_job_to_out(active, already_active=True))
                continue

            last_completed = _get_last_completed(session, key)
            cooldown = _cooldown_remaining(last_completed)
            if cooldown > 0:
                skipped.append({
                    "source": key,
                    "reason": "cooldown",
                    "cooldown_remaining_seconds": cooldown,
                })
                continue

            job = ScrapeJob(
                source_name=key,
                trigger_type="manual",
                status="queued",
                queued_at=datetime.utcnow(),
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            logger.info("Manual trigger (all): created job %s for %s", job.id, key)
            background_tasks.add_task(run_scrape_job, job.id)
            jobs_out.append(_job_to_out(job))

        return MultiJobResponse(jobs=jobs_out, skipped=skipped)

    # ── sursă individuală ─────────────────────────────────────────────────────
    if not is_registered(source):
        raise HTTPException(
            status_code=400,
            detail=f"Sursă necunoscută: '{source}'. Surse disponibile: {list_source_keys()}",
        )

    db_source = _get_db_source(session, source)
    if not db_source or not db_source.is_active:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "source_inactive",
                "source": source,
                "message": f"Sursa '{source}' este dezactivată.",
            },
        )

    active = _get_active_job(session, source)
    if active:
        logger.info("Manual trigger: job %s already active for %s", active.id, source)
        return _job_to_out(active, already_active=True)

    last_completed = _get_last_completed(session, source)
    remaining = _cooldown_remaining(last_completed)
    if remaining > 0:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "cooldown",
                "cooldown_remaining_seconds": remaining,
                "last_completed_at": (
                    last_completed.finished_at.isoformat()
                    if last_completed and last_completed.finished_at
                    else None
                ),
            },
        )

    job = ScrapeJob(
        source_name=source,
        trigger_type="manual",
        status="queued",
        queued_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    logger.info("Manual trigger: created job %s for %s", job.id, source)
    background_tasks.add_task(run_scrape_job, job.id)
    return _job_to_out(job)


@router.get("/status")
def get_all_sources_status(
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Returnează statusul curent pentru toate sursele înregistrate."""
    result: dict[str, dict] = {}

    for key in list_source_keys():
        db_source = _get_db_source(session, key)
        is_active = db_source.is_active if db_source else False

        if is_active:
            active_job = _get_active_job(session, key)
            last_completed = _get_last_completed(session, key)
            cooldown = _cooldown_remaining(last_completed)
        else:
            active_job = None
            last_completed = None
            cooldown = 0

        result[key] = {
            "source_key": key,
            "is_active": is_active,
            "display_name": _DISPLAY_NAMES.get(key, key),
            "active_job": _job_to_out(active_job).model_dump() if active_job else None,
            "last_completed": _job_to_out(last_completed).model_dump() if last_completed else None,
            "cooldown_remaining_seconds": cooldown,
        }

    return result


@router.get("/jobs/latest", response_model=LatestJobOut)
def get_latest_job(
    source: str = "publi24",
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    source = source.lower()
    active = _get_active_job(session, source)
    last_completed = _get_last_completed(session, source)
    remaining = _cooldown_remaining(last_completed)

    return LatestJobOut(
        active_job=_job_to_out(active) if active else None,
        last_completed=_job_to_out(last_completed) if last_completed else None,
        cooldown_remaining_seconds=remaining,
    )


@router.get("/jobs/{job_id}", response_model=ScrapeJobOut)
def get_job(
    job_id: int,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    job = session.get(ScrapeJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job negăsit.")
    return _job_to_out(job)
