"""
Orchestrator generic pentru joburi de scraping.

Flux:
  queued → running → completed
                  → failed

Selectează adaptorul sursei din registry, rulează în thread pool,
importă listing-urile direct în DB, generează oportunități.

Nu conține logică specifică niciunei surse — tot ce e source-specific
stă în adapters/.
"""
import asyncio
import logging
import re
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.database.session import engine
from app.modules.market.models import Source
from app.modules.market.service import get_city_id_by_name, save_listing, mark_inactive_listings
from app.modules.organizations.models import Organization
from app.modules.opportunities.service import generate_opportunities_for_org
from app.modules.scraping.adapters.base import ScrapedListing
from app.modules.scraping.models import ScrapeJob
from app.modules.scraping.registry import get_adapter

logger = logging.getLogger(__name__)

# Stări care indică un job activ (în lucru sau în așteptare)
ACTIVE_STATUSES = ("queued", "running")

# Pattern pentru a detecta secrete în mesaje de eroare
_SECRET_PATTERN = re.compile(
    r"(password|passwd|pwd|secret|token|key|npg_|postgresql://)[^\s\"']{4,}",
    re.IGNORECASE,
)

# Numărul maxim de pagini per sursă (fallback dacă sursa nu are config propriu)
_DEFAULT_MAX_PAGES = 20


def _sanitize_error(exc: Exception) -> str:
    """Elimină potențiale secrete din mesajele de eroare."""
    msg = str(exc)
    msg = _SECRET_PATTERN.sub("[REDACTED]", msg)
    return msg[:500]


def _get_max_pages(source_key: str) -> int:
    """Returnează numărul maxim de pagini configurat pentru sursa dată."""
    mapping = {
        "publi24": settings.scrape_publi24_max_pages,
        "imobiliare_ro": settings.scrape_imobiliare_ro_max_pages,
        "romimo": settings.scrape_romimo_max_pages,
        "storia": settings.scrape_storia_max_pages,
    }
    return mapping.get(source_key, _DEFAULT_MAX_PAGES)


def _import_listings(
    session: Session,
    listings: list[ScrapedListing],
    source_id: int,
    adapter_key: str,
    job_id: int | None = None,
) -> dict:
    """
    Importă listing-urile în DB și returnează contoarele.
    Fiecare listing e salvat individual; excepțiile per-listing nu opresc importul.
    """
    created = updated = unchanged = failed = warnings = 0
    seen_external_ids: set[str] = set()
    seen_urls: set[str] = set()

    # Obținem adaptorul pentru extract_external_id
    try:
        adapter = get_adapter(adapter_key)
    except ValueError:
        adapter = None

    for scraped in listings:
        try:
            city_id = get_city_id_by_name(
                session,
                scraped.location_raw or "",
                county=getattr(scraped, "county_raw", None),
            )

            # External ID: preferăm scraped.external_id, altfel calculăm din URL
            if scraped.external_id:
                external_id = scraped.external_id
            elif adapter:
                external_id = adapter.extract_external_id(scraped.url)
            else:
                external_id = scraped.url.rstrip("/").split("/")[-1].replace(".html", "")

            if external_id:
                seen_external_ids.add(external_id)
            seen_urls.add(scraped.url)

            result, _ = save_listing(
                session,
                source_id=source_id,
                city_id=city_id,
                external_id=external_id,
                url=scraped.url,
                title=scraped.title,
                description=scraped.description,
                price_eur=scraped.price_eur,
                currency="EUR",
                rooms=scraped.rooms,
                surface_m2=scraped.surface_m2,
                property_type=scraped.property_type,
                transaction_type=scraped.transaction_type,
                location_raw=scraped.location_raw,
                published_at=scraped.published_at,
                zone_raw=scraped.zone_raw,
                zone_normalized=scraped.zone_normalized,
                data_quality=scraped.data_quality,
                quality_warnings=scraped.quality_warnings,
                image_urls=scraped.image_urls,
                seller_type=scraped.seller_type,
                job_id=job_id,
            )

            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            else:
                unchanged += 1

            if scraped.data_quality == "warning":
                warnings += 1

        except Exception as exc:
            logger.error("Failed to import listing %s: %s", scraped.url[:80], exc)
            failed += 1

    return {
        "listings_created": created,
        "listings_updated": updated,
        "listings_unchanged": unchanged,
        "listings_failed": failed,
        "warnings_count": warnings,
        "seen_external_ids": seen_external_ids,
        "seen_urls": seen_urls,
    }


def _run_scrape_job_sync(job_id: int) -> None:
    """
    Funcție sincronă — rulează în thread pool.
    Creează propria sa sesiune DB (nu poate folosi DI FastAPI).
    """
    with Session(engine) as session:
        job = session.get(ScrapeJob, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        source_key = job.source_name or ""

        # ── 1. Tranziție queued → running ─────────────────────────────────────
        job.status = "running"
        job.started_at = datetime.utcnow()
        session.add(job)
        session.commit()

        try:
            # ── 2. Guard specific per sursă ───────────────────────────────────
            if source_key == "imobiliare_ro":
                from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoNotAuthorizedError
                if not settings.scrape_imobiliare_ro_enabled:
                    raise ImobiliareRoNotAuthorizedError(
                        "SCRAPE_IMOBILIARE_RO_ENABLED=false în config"
                    )
                if not settings.scrape_imobiliare_ro_authorized:
                    raise ImobiliareRoNotAuthorizedError(
                        "SCRAPE_IMOBILIARE_RO_AUTHORIZED=false în config"
                    )

            # ── 3. Selectare adaptor din registry ─────────────────────────────
            adapter = get_adapter(source_key)

            # ── 4. Resolve source_id din DB (prin slug) ───────────────────────
            source = session.exec(
                select(Source).where(Source.slug == source_key)
            ).first()
            if not source:
                # Fallback: lookup by name (case-insensitive) pentru compatibilitate
                source = session.exec(
                    select(Source).where(Source.name.ilike(source_key))
                ).first()
            if not source:
                raise RuntimeError(
                    f"Source '{source_key}' not found in DB. Run migrations."
                )
            if not source.is_active:
                raise RuntimeError(
                    f"Source '{source_key}' is disabled (is_active=false). "
                    "Activate it before running jobs."
                )

            # ── 5. Scraping ───────────────────────────────────────────────────
            max_pages = _get_max_pages(source_key)
            logger.info("Job %s: starting %s scrape (max_pages=%d)", job_id, source_key, max_pages)
            listings = adapter.scrape_all(max_pages=max_pages)

            job.listings_found = len(listings)
            job.pages_processed = 1  # adaptorii simpli nu raportează pagini separat
            session.add(job)
            session.commit()

            # ── 6. Import în DB ───────────────────────────────────────────────
            counters = _import_listings(session, listings, source.id, source_key, job_id=job.id)

            job.listings_created = counters["listings_created"]
            job.listings_updated = counters["listings_updated"]
            job.listings_unchanged = counters["listings_unchanged"]
            job.listings_failed = counters["listings_failed"]
            job.warnings_count = counters["warnings_count"]
            job.listings_inserted = counters["listings_created"]  # legacy

            # ── 7. Mark inactive ──────────────────────────────────────────────
            try:
                inactive_result = mark_inactive_listings(
                    session,
                    source_id=source.id,
                    seen_external_ids=counters.get("seen_external_ids", set()),
                    seen_urls=counters.get("seen_urls", set()),
                    threshold=settings.scrape_imobiliare_ro_inactive_threshold,
                )
                logger.info("Job %s: inactive update: %s", job_id, inactive_result)
            except Exception as exc:
                logger.error("Job %s: mark_inactive_listings failed: %s", job_id, exc)

            # ── 8. Opportunity engine ─────────────────────────────────────────
            opp_error: str | None = None
            try:
                orgs = session.exec(
                    select(Organization).where(Organization.is_active == True)  # noqa: E712
                ).all()
                for org in orgs:
                    generate_opportunities_for_org(session, org.id)
                logger.info("Job %s: opportunities generated for %d orgs", job_id, len(orgs))
            except Exception as exc:
                opp_error = _sanitize_error(exc)
                logger.error("Job %s: opportunity generation failed: %s", job_id, exc)

            # ── 9. Completat ──────────────────────────────────────────────────
            job.status = "completed"
            job.finished_at = datetime.utcnow()
            if opp_error:
                job.error_message = f"[opportunity_engine] {opp_error}"
            session.add(job)
            session.commit()

            logger.info(
                "Job %s (%s) completed: created=%d updated=%d unchanged=%d failed=%d warnings=%d",
                job_id,
                source_key,
                counters["listings_created"],
                counters["listings_updated"],
                counters["listings_unchanged"],
                counters["listings_failed"],
                counters["warnings_count"],
            )

        except Exception as exc:
            safe_msg = _sanitize_error(exc)
            logger.error("Job %s (%s) failed: %s", job_id, source_key, exc)

            try:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                job.error_message = safe_msg
                session.add(job)
                session.commit()
            except Exception as commit_exc:
                logger.error("Job %s: could not save failed status: %s", job_id, commit_exc)


async def run_scrape_job(job_id: int) -> None:
    """
    Async wrapper — rulează job-ul sincron într-un thread pool
    fără a bloca event loop-ul FastAPI.
    """
    await asyncio.to_thread(_run_scrape_job_sync, job_id)


def recover_stuck_jobs(timeout_minutes: int = 60) -> int:
    """
    La startup: orice job rămas în starea 'running' mai mult de timeout_minutes
    este marcat ca failed (procesul a murit fără să termine).
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

    with Session(engine) as session:
        stuck = session.exec(
            select(ScrapeJob)
            .where(ScrapeJob.status == "running")
            .where(ScrapeJob.started_at <= cutoff)
        ).all()

        for job in stuck:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = (
                f"Job recovered at startup — was stuck in 'running' for >{timeout_minutes}min."
            )
            session.add(job)

        if stuck:
            session.commit()
            logger.warning("Recovered %d stuck jobs at startup", len(stuck))

        return len(stuck)
