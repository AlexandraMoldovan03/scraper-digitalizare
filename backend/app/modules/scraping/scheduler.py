"""
APScheduler generic — rulează fiecare sursă activă la intervalul configurat.

Pornit/oprit prin lifespan FastAPI.
Fiecare sursă are propriul job APScheduler cu propriul interval.
Dacă o sursă este dezactivată în config, nu se adaugă în scheduler.

Limitări single-instance:
- max_instances=1 + coalesce=True previne overlap per job APScheduler.
- Pe mai multe instanțe backend, protecția reală este la nivel DB
  (verificare job activ înainte de creare).
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from app.core.config import settings
from app.database.session import engine
from app.modules.scraping.models import ScrapeJob
from app.modules.scraping.orchestrator import ACTIVE_STATUSES, run_scrape_job
from app.modules.scraping.registry import list_source_keys

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


# ── Configurație per sursă ────────────────────────────────────────────────────

def _source_schedule_config() -> dict[str, tuple[bool, int]]:
    """
    Returnează {source_key: (enabled, interval_minutes)} pentru toate sursele.
    Adaugă o sursă nouă = o linie nouă aici.
    """
    return {
        "publi24": (
            settings.scraping_scheduler_enabled,
            settings.scrape_publi24_interval_minutes,
        ),
        "imobiliare_ro": (
            settings.scrape_imobiliare_ro_enabled,
            settings.scrape_imobiliare_ro_interval_minutes,
        ),
        "romimo": (
            settings.scrape_romimo_enabled,
            settings.scrape_romimo_interval_minutes,
        ),
    }


# ── Scheduled task generic ────────────────────────────────────────────────────

async def _scheduled_scrape(source_key: str) -> None:
    """
    Funcție apelată de scheduler pentru orice sursă.
    Verifică dacă există deja un job activ → dacă da, skip.
    """
    with Session(engine) as session:
        active = session.exec(
            select(ScrapeJob)
            .where(ScrapeJob.source_name == source_key)
            .where(ScrapeJob.status.in_(list(ACTIVE_STATUSES)))
        ).first()

        if active:
            logger.info(
                "Scheduler: skip — job %s already %s for %s",
                active.id, active.status, source_key,
            )
            return

        job = ScrapeJob(
            source_name=source_key,
            trigger_type="scheduled",
            status="queued",
            queued_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    logger.info("Scheduler: created job %s for %s", job_id, source_key)
    await run_scrape_job(job_id)


# ── Setup / teardown ──────────────────────────────────────────────────────────

def setup_scheduler() -> None:
    """
    Adaugă un job APScheduler pentru fiecare sursă activată în config.
    Apelat din lifespan FastAPI la startup.
    """
    config = _source_schedule_config()
    registered = set(list_source_keys())
    sources_added = 0

    for source_key, (enabled, interval_minutes) in config.items():
        if source_key not in registered:
            logger.warning("Scheduler: '%s' not in registry — skip", source_key)
            continue
        if not enabled:
            logger.info("Scheduler: '%s' disabled in config — skip", source_key)
            continue

        scheduler.add_job(
            _scheduled_scrape,
            args=[source_key],
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=f"scrape_{source_key}",
            name=f"Scrape {source_key}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduler: '%s' added — every %d minutes", source_key, interval_minutes)
        sources_added += 1

    if sources_added > 0:
        scheduler.start()
        logger.info("Scheduler started (%d source(s))", sources_added)
    else:
        logger.info("Scheduler: no sources enabled — not started")


def teardown_scheduler() -> None:
    """Oprește schedulerul la shutdown FastAPI."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
