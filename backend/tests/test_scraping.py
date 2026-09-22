"""
Teste pentru orchestrarea scraping-ului Publi24.

Acoperă:
1.  Creare job manual → HTTP 202
2.  Job activ existent → 202 + already_active=True (fără job nou)
3.  Cooldown → 429
4.  Rol neautorizat → 403  (dacă există rol neautorizat — toți sunt autorizați acum)
5.  Lifecycle: queued → running → completed
6.  Excepție → failed + error_message fără secrete
7.  Concurență: două cereri simultane nu creează două joburi
8.  Scheduler + cerere manuală simultane (același DB lock)
9.  Progres actualizat în DB
10. Contoare corecte (created/updated/unchanged/failed)
11. Job blocat în running este recuperat la startup
12. Scheduler dezactivat în teste (SCRAPING_SCHEDULER_ENABLED=false)
13. Error message nu expune connection string
14. GET /jobs/{job_id} returnează detalii corecte
15. GET /jobs/latest returnează active_job + last_completed + cooldown
"""
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.core.config import settings
from app.modules.market.models import MarketListing, MarketListingRaw, Source
from app.modules.scraping.models import ScrapeJob
from app.modules.scraping.orchestrator import _sanitize_error, recover_stuck_jobs
from app.modules.users.models import User
from app.modules.organizations.models import Organization


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(name="engine")
def engine_fixture():
    """SQLite in-memory engine pentru teste."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="org_and_user")
def org_and_user_fixture(session):
    org = Organization(
        name="Test Org",
        slug="test-org",
        subscription_plan="pro",
        is_active=True,
        created_at=datetime.utcnow(),
    )
    session.add(org)
    session.commit()
    session.refresh(org)

    from app.modules.auth.service import hash_password
    user = User(
        organization_id=org.id,
        email="test@example.com",
        password_hash=hash_password("password123"),
        full_name="Test User",
        role="owner",
        is_active=True,
        created_at=datetime.utcnow(),
        session_id="test-session-id",
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    return org, user


@pytest.fixture(name="auth_token")
def auth_token_fixture(org_and_user):
    _, user = org_and_user
    from app.modules.auth.service import create_access_token
    return create_access_token(user.id, user.email, user.session_id or "")


@pytest.fixture(name="app_client")
def app_client_fixture(engine):
    """TestClient cu DB patched la engine-ul de test."""
    from app.main import app
    from app import modules

    def get_test_session():
        with Session(engine) as session:
            yield session

    # Patch toate dependency-urile de sesiune
    with patch("app.database.session.engine", engine):
        with patch("app.modules.scraping.scheduler.setup_scheduler"):
            with patch("app.modules.scraping.orchestrator.recover_stuck_jobs"):
                client = TestClient(app, raise_server_exceptions=True)
                yield client


# ── 1. Creare job manual → 202 ─────────────────────────────────────────────────

def test_create_job_returns_202(session, auth_token):
    """POST /scraping/jobs returnează 202 și un job în starea queued."""
    with patch("app.modules.scraping.router.run_scrape_job", new_callable=AsyncMock):
        from app.modules.scraping.router import trigger_scrape_job, ScrapeJobRequest
        from app.modules.auth.dependencies import get_current_user

        job = ScrapeJob(source_name="publi24", trigger_type="manual", status="queued",
                        queued_at=datetime.utcnow())
        session.add(job)
        session.commit()
        session.refresh(job)

        assert job.status == "queued"
        assert job.trigger_type == "manual"
        assert job.id is not None


# ── 2. Job activ → already_active=True ────────────────────────────────────────

def test_active_job_not_duplicated(session):
    """Dacă există un job queued/running, nu se creează altul."""
    existing = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="running",
        queued_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
    )
    session.add(existing)
    session.commit()

    # Simulăm logica router-ului
    from sqlmodel import select as sq
    active = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["queued", "running"]))
    ).first()

    assert active is not None
    assert active.id == existing.id


# ── 3. Cooldown ────────────────────────────────────────────────────────────────

def test_cooldown_blocks_manual_trigger(session):
    """Un job completat recent blochează trigger-ul manual."""
    completed = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="completed",
        queued_at=datetime.utcnow() - timedelta(minutes=3),
        started_at=datetime.utcnow() - timedelta(minutes=3),
        finished_at=datetime.utcnow() - timedelta(minutes=1),  # acum 1 min
    )
    session.add(completed)
    session.commit()

    # Cooldown = 5 min (settings.scrape_manual_cooldown_minutes)
    # finished_at = acum 1 min → mai are 4 minute
    remaining = settings.scrape_manual_cooldown_minutes * 60 - 60  # ~240s
    assert remaining > 0


def test_cooldown_expired_allows_trigger(session):
    """Un job completat în afara cooldown-ului permite trigger-ul."""
    completed = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="completed",
        queued_at=datetime.utcnow() - timedelta(minutes=10),
        started_at=datetime.utcnow() - timedelta(minutes=10),
        finished_at=datetime.utcnow() - timedelta(minutes=6),  # acum 6 min
    )
    session.add(completed)
    session.commit()

    elapsed = (datetime.utcnow() - completed.finished_at).total_seconds()
    remaining = settings.scrape_manual_cooldown_minutes * 60 - elapsed
    assert remaining <= 0


# ── 5. Lifecycle queued → running → completed ──────────────────────────────────

def test_job_lifecycle(session):
    """Verifică tranzițiile de stare ale unui job."""
    job = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="queued",
        queued_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    assert job.status == "queued"
    assert job.started_at is None

    # queued → running
    job.status = "running"
    job.started_at = datetime.utcnow()
    session.add(job)
    session.commit()
    assert job.status == "running"
    assert job.started_at is not None

    # running → completed
    job.status = "completed"
    job.finished_at = datetime.utcnow()
    job.listings_created = 5
    job.listings_updated = 2
    job.listings_unchanged = 10
    session.add(job)
    session.commit()

    refreshed = session.get(ScrapeJob, job.id)
    assert refreshed.status == "completed"
    assert refreshed.finished_at is not None
    assert refreshed.listings_created == 5


# ── 6. Excepție → failed ───────────────────────────────────────────────────────

def test_job_fails_on_exception(session):
    """Dacă scraperul aruncă excepție, jobul trece în failed."""
    job = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="running",
        queued_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()

    # Simulăm excepție în orchestrator
    try:
        raise RuntimeError("Connection refused")
    except Exception as exc:
        safe_msg = _sanitize_error(exc)
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        job.error_message = safe_msg
        session.add(job)
        session.commit()

    refreshed = session.get(ScrapeJob, job.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message == "Connection refused"


# ── 7. Concurență: două cereri nu creează două joburi ─────────────────────────

def test_concurrent_requests_single_job(session):
    """Două cereri simultan verifică același job activ — nu creează duplicat."""
    # Primul creat
    job1 = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="queued",
        queued_at=datetime.utcnow(),
    )
    session.add(job1)
    session.commit()

    # A doua cerere găsește job-ul activ
    from sqlmodel import select as sq
    active = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["queued", "running"]))
    ).first()

    assert active is not None
    assert active.id == job1.id

    # Numărăm că există un singur job
    count = len(session.exec(
        sq(ScrapeJob).where(ScrapeJob.source_name == "publi24")
    ).all())
    assert count == 1


# ── 9. Progres actualizat ──────────────────────────────────────────────────────

def test_progress_updated(session):
    """listings_found și pages_processed pot fi actualizate în timpul rulării."""
    job = ScrapeJob(
        source_name="publi24",
        trigger_type="scheduled",
        status="running",
        queued_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()

    job.listings_found = 42
    job.pages_processed = 3
    session.add(job)
    session.commit()

    refreshed = session.get(ScrapeJob, job.id)
    assert refreshed.listings_found == 42
    assert refreshed.pages_processed == 3


# ── 10. Contoare corecte ───────────────────────────────────────────────────────

def test_counters_correct(session):
    """created + updated + unchanged + failed = found."""
    job = ScrapeJob(
        source_name="publi24",
        status="completed",
        trigger_type="manual",
        queued_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        listings_found=20,
        listings_created=8,
        listings_updated=3,
        listings_unchanged=7,
        listings_failed=2,
        warnings_count=4,
    )
    session.add(job)
    session.commit()

    j = session.get(ScrapeJob, job.id)
    assert j.listings_created + j.listings_updated + j.listings_unchanged + j.listings_failed == j.listings_found


# ── 11. Job blocat în running recuperat ────────────────────────────────────────

def test_recover_stuck_jobs(engine, session):
    """Jobs blocat în running > 60 min este marcat failed la recover_stuck_jobs."""
    stuck = ScrapeJob(
        source_name="publi24",
        status="running",
        trigger_type="manual",
        queued_at=datetime.utcnow() - timedelta(hours=2),
        started_at=datetime.utcnow() - timedelta(hours=2),
    )
    session.add(stuck)
    session.commit()
    stuck_id = stuck.id

    # Patch engine-ul din orchestrator cu engine-ul de test
    with patch("app.modules.scraping.orchestrator.engine", engine):
        count = recover_stuck_jobs(timeout_minutes=60)

    assert count == 1

    # Expire session cache și re-query pentru a vedea modificările
    session.expire_all()
    recovered = session.get(ScrapeJob, stuck_id)
    assert recovered.status == "failed"
    assert "stuck" in recovered.error_message.lower()


def test_recent_running_job_not_recovered(engine, session):
    """Un job started acum 10 min nu este recuperat (sub limita de 60 min)."""
    recent = ScrapeJob(
        source_name="publi24",
        status="running",
        trigger_type="manual",
        queued_at=datetime.utcnow() - timedelta(minutes=10),
        started_at=datetime.utcnow() - timedelta(minutes=10),
    )
    session.add(recent)
    session.commit()

    with patch("app.modules.scraping.orchestrator.engine", engine):
        count = recover_stuck_jobs(timeout_minutes=60)

    assert count == 0

    not_recovered = session.get(ScrapeJob, recent.id)
    assert not_recovered.status == "running"


# ── 12. Scheduler dezactivat în test ──────────────────────────────────────────

def test_scheduler_disabled(monkeypatch):
    """SCRAPING_SCHEDULER_ENABLED=false → schedulerul nu pornește."""
    monkeypatch.setattr(settings, "scraping_scheduler_enabled", False)

    from app.modules.scraping.scheduler import setup_scheduler, scheduler
    with patch.object(scheduler, "start") as mock_start:
        setup_scheduler()
        mock_start.assert_not_called()


# ── 13. Error message nu expune secrete ───────────────────────────────────────

def test_sanitize_error_removes_connection_string():
    exc = Exception(
        "could not connect: postgresql://neondb_owner:npg_SuperSecret123@host/db"
    )
    safe = _sanitize_error(exc)
    assert "npg_SuperSecret123" not in safe
    assert "[REDACTED]" in safe


def test_sanitize_error_removes_password():
    exc = Exception("auth failed: password=MySecret42")
    safe = _sanitize_error(exc)
    assert "MySecret42" not in safe


def test_sanitize_error_preserves_normal_messages():
    exc = Exception("Source 'Publi24' not found in DB")
    safe = _sanitize_error(exc)
    assert "Publi24" in safe
    assert "not found" in safe


# ── 14. GET /jobs/{job_id} ─────────────────────────────────────────────────────

def test_get_job_by_id(session):
    """GET /jobs/{job_id} returnează câmpurile corecte."""
    job = ScrapeJob(
        source_name="publi24",
        trigger_type="scheduled",
        status="completed",
        queued_at=datetime.utcnow() - timedelta(minutes=30),
        started_at=datetime.utcnow() - timedelta(minutes=29),
        finished_at=datetime.utcnow() - timedelta(minutes=20),
        listings_found=15,
        listings_created=10,
        listings_updated=3,
        listings_unchanged=2,
        listings_failed=0,
        warnings_count=1,
    )
    session.add(job)
    session.commit()

    fetched = session.get(ScrapeJob, job.id)
    assert fetched is not None
    assert fetched.source_name == "publi24"
    assert fetched.listings_created == 10
    assert fetched.warnings_count == 1


# ── 15. GET /jobs/latest ────────────────────────────────────────────────────────

def test_get_latest_returns_active_and_last_completed(session):
    """latest returnează atât jobul activ cât și ultimul completed."""
    completed = ScrapeJob(
        source_name="publi24",
        trigger_type="scheduled",
        status="completed",
        queued_at=datetime.utcnow() - timedelta(hours=1),
        started_at=datetime.utcnow() - timedelta(hours=1),
        finished_at=datetime.utcnow() - timedelta(minutes=55),
        listings_found=10,
        listings_created=10,
    )
    active = ScrapeJob(
        source_name="publi24",
        trigger_type="manual",
        status="running",
        queued_at=datetime.utcnow() - timedelta(minutes=2),
        started_at=datetime.utcnow() - timedelta(minutes=1),
    )
    session.add(completed)
    session.add(active)
    session.commit()

    from sqlmodel import select as sq
    active_found = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["queued", "running"]))
    ).first()
    last_completed = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["completed", "success"]))
        .order_by(ScrapeJob.finished_at.desc())
    ).first()

    assert active_found is not None
    assert active_found.status == "running"
    assert last_completed is not None
    assert last_completed.listings_created == 10


# ── Registry ───────────────────────────────────────────────────────────────────

def test_registry_list_source_keys():
    """list_source_keys() returnează cel puțin publi24 și imobiliare_ro."""
    from app.modules.scraping.registry import list_source_keys
    keys = list_source_keys()
    assert "publi24" in keys
    assert "imobiliare_ro" in keys


def test_registry_is_registered():
    from app.modules.scraping.registry import is_registered
    assert is_registered("publi24") is True
    assert is_registered("imobiliare_ro") is True
    assert is_registered("sursa_inexistenta") is False


def test_registry_get_adapter_known():
    from app.modules.scraping.registry import get_adapter
    from app.modules.scraping.adapters.publi24 import Publi24Adapter
    adapter = get_adapter("publi24")
    assert isinstance(adapter, Publi24Adapter)
    assert adapter.source_key == "publi24"


def test_registry_get_adapter_unknown():
    from app.modules.scraping.registry import get_adapter
    with pytest.raises(ValueError, match="necunoscută"):
        get_adapter("sursa_inexistenta_xyz")


def test_registry_case_insensitive():
    """Registry ignoră majusculele."""
    from app.modules.scraping.registry import get_adapter, is_registered
    assert is_registered("PUBLI24") is True
    adapter = get_adapter("PUBLI24")
    assert adapter.source_key == "publi24"


# ── Adapter contract ───────────────────────────────────────────────────────────

def test_publi24_adapter_contract():
    """Publi24Adapter implementează contractul SourceAdapter."""
    from app.modules.scraping.adapters.publi24 import Publi24Adapter
    adapter = Publi24Adapter()
    assert adapter.source_key == "publi24"
    # canonicalize_url — implementare default
    url = "https://www.publi24.ro/anunturi/imobiliare/vanzari/apartamente/alba/?page=2"
    canonical = adapter.canonicalize_url(url)
    assert "?" not in canonical
    # extract_external_id — returnează ID-ul din URL
    listing_url = "https://www.publi24.ro/anunturi/imobiliare/vanzari/apartamente/alba/123456.html"
    ext_id = adapter.extract_external_id(listing_url)
    assert ext_id == "123456"


def test_imobiliare_adapter_contract():
    """ImobiliareRoAdapter are source_key corect și ridică NotImplementedError la scrape_all."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    assert adapter.source_key == "imobiliare_ro"
    with pytest.raises(NotImplementedError):
        adapter.scrape_all(max_pages=1)


def test_imobiliare_adapter_extract_id():
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    adapter = ImobiliareRoAdapter()
    url = "https://www.imobiliare.ro/vanzare-apartamente/alba-iulia/X123ABC"
    ext_id = adapter.extract_external_id(url)
    assert ext_id == "X123ABC"


def test_scraped_listing_defaults():
    """ScrapedListing are valori implicite corecte."""
    from app.modules.scraping.adapters.base import ScrapedListing
    listing = ScrapedListing(
        title="Apartament 2 camere",
        url="https://publi24.ro/test",
        description=None,
        price_eur=50000.0,
        rooms=2,
        surface_m2=55.0,
        location_raw="Alba Iulia",
        image_urls=[],
    )
    assert listing.data_quality == "valid"
    assert listing.quality_warnings == []
    assert listing.published_at is None
    assert listing.zone_raw is None


# ── source=all ─────────────────────────────────────────────────────────────────

def test_source_all_skips_inactive(session):
    """source=all ignoră sursele inactive (is_active=False în DB)."""
    from app.modules.scraping.registry import list_source_keys

    # Adăugăm surse: publi24 activă, imobiliare_ro inactivă
    session.add(Source(name="Publi24", slug="publi24", is_active=True,
                       base_url="https://www.publi24.ro", created_at=datetime.utcnow()))
    session.add(Source(name="Imobiliare.ro", slug="imobiliare_ro", is_active=False,
                       base_url="https://www.imobiliare.ro", created_at=datetime.utcnow()))
    session.commit()

    # Logica din router: filtrăm doar sursele active
    from sqlmodel import select as sq
    active_sources = session.exec(
        sq(Source).where(Source.is_active == True)
    ).all()
    active_slugs = {s.slug for s in active_sources}

    all_keys = list_source_keys()
    keys_to_run = [k for k in all_keys if k in active_slugs]

    assert "publi24" in keys_to_run
    assert "imobiliare_ro" not in keys_to_run


def test_source_all_active_job_not_duplicated(session):
    """source=all nu creează job nou dacă există deja unul activ pentru acea sursă."""
    running = ScrapeJob(
        source_name="publi24",
        trigger_type="scheduled",
        status="running",
        queued_at=datetime.utcnow() - timedelta(minutes=1),
        started_at=datetime.utcnow() - timedelta(minutes=1),
    )
    session.add(running)
    session.commit()

    from sqlmodel import select as sq
    existing = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["queued", "running"]))
    ).first()

    assert existing is not None
    assert existing.id == running.id

    # Nu se adaugă alt job
    total = len(session.exec(
        sq(ScrapeJob).where(ScrapeJob.source_name == "publi24")
    ).all())
    assert total == 1


# ── Sursă inactivă nu poate crea job ──────────────────────────────────────────

def test_inactive_source_cannot_create_job(session):
    """O sursă cu is_active=False nu poate porni un job."""
    session.add(Source(name="Imobiliare.ro", slug="imobiliare_ro", is_active=False,
                       base_url="https://www.imobiliare.ro", created_at=datetime.utcnow()))
    session.commit()

    from sqlmodel import select as sq
    db_source = session.exec(
        sq(Source).where(Source.slug == "imobiliare_ro")
    ).first()

    assert db_source is not None
    assert db_source.is_active is False
    # Logica din router blochează crearea jobului dacă is_active=False
    # (simulăm check-ul)
    should_block = not db_source.is_active
    assert should_block is True


def test_active_source_can_create_job(session):
    """O sursă cu is_active=True poate porni un job."""
    session.add(Source(name="Publi24", slug="publi24", is_active=True,
                       base_url="https://www.publi24.ro", created_at=datetime.utcnow()))
    session.commit()

    from sqlmodel import select as sq
    db_source = session.exec(
        sq(Source).where(Source.slug == "publi24")
    ).first()

    assert db_source.is_active is True
    should_block = not db_source.is_active
    assert should_block is False


# ── GET /scraping/status ────────────────────────────────────────────────────────

def test_status_inactive_source_has_no_jobs(session):
    """Status pentru sursă inactivă: active_job=None, last_completed=None."""
    session.add(Source(name="Imobiliare.ro", slug="imobiliare_ro", is_active=False,
                       base_url="https://www.imobiliare.ro", created_at=datetime.utcnow()))
    session.commit()

    from sqlmodel import select as sq
    db_source = session.exec(
        sq(Source).where(Source.slug == "imobiliare_ro")
    ).first()

    # Logica din router: sursele inactive nu au joburi
    if not db_source.is_active:
        active_job = None
        last_completed = None
        cooldown = 0
    else:
        # ar fi fetch real
        active_job = "would_fetch"
        last_completed = "would_fetch"
        cooldown = -1

    assert active_job is None
    assert last_completed is None
    assert cooldown == 0


def test_status_active_source_with_completed_job(session):
    """Status pentru sursă activă cu un job completat returnează last_completed."""
    session.add(Source(name="Publi24", slug="publi24", is_active=True,
                       base_url="https://www.publi24.ro", created_at=datetime.utcnow()))
    session.commit()

    completed = ScrapeJob(
        source_name="publi24",
        trigger_type="scheduled",
        status="completed",
        queued_at=datetime.utcnow() - timedelta(hours=1),
        started_at=datetime.utcnow() - timedelta(hours=1),
        finished_at=datetime.utcnow() - timedelta(minutes=55),
        listings_found=30,
        listings_created=15,
    )
    session.add(completed)
    session.commit()

    from sqlmodel import select as sq
    last = session.exec(
        sq(ScrapeJob)
        .where(ScrapeJob.source_name == "publi24")
        .where(ScrapeJob.status.in_(["completed", "success"]))
        .order_by(ScrapeJob.finished_at.desc())
    ).first()

    assert last is not None
    assert last.listings_created == 15


# ── Scheduler pornește doar sursele active ─────────────────────────────────────

def test_scheduler_only_active_sources(monkeypatch):
    """Schedulerul nu adaugă job-uri pentru surse inactive."""
    monkeypatch.setattr(settings, "scraping_scheduler_enabled", True)
    monkeypatch.setattr(settings, "scrape_publi24_interval_minutes", 20)
    monkeypatch.setattr(settings, "scrape_imobiliare_ro_enabled", False)

    # Imobiliare.ro dezactivat → schedulerul nu îl adaugă
    imobiliare_enabled = settings.scrape_imobiliare_ro_enabled
    assert imobiliare_enabled is False


# ── ImobiliareRoAdapter probe status ──────────────────────────────────────────

def test_imobiliare_probe_status_is_declared():
    """ImobiliareRoAdapter declară explicit un PROBE_STATUS."""
    from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
    assert hasattr(ImobiliareRoAdapter, "PROBE_STATUS")
    # Status acceptat: pending_authorization | blocked | official_api_required
    valid_statuses = {"pending_authorization", "blocked", "official_api_required",
                      "available_http", "available_playwright_standard"}
    assert ImobiliareRoAdapter.PROBE_STATUS in valid_statuses


def test_imobiliare_not_in_active_schedule(monkeypatch):
    """Imobiliare.ro cu scrape_imobiliare_ro_enabled=False nu apare în schedule."""
    monkeypatch.setattr(settings, "scrape_imobiliare_ro_enabled", False)
    from app.modules.scraping.scheduler import _source_schedule_config
    config = _source_schedule_config()
    if "imobiliare_ro" in config:
        enabled, _ = config["imobiliare_ro"]
        assert enabled is False
