"""Diagnostic: ultimele joburi + test direct pe adaptoare."""
import sys
from dotenv import load_dotenv
load_dotenv('/Users/alexandramoldovan/scraper-digitalizare/backend/.env')

from sqlmodel import Session, select
from app.database.session import engine
from app.modules.scraping.models import ScrapeJob
from app.core.config import settings

print("=" * 70)
print("1. CONFIG FLAGS")
print("=" * 70)
print(f"  imobiliare_ro_enabled    = {settings.scrape_imobiliare_ro_enabled}")
print(f"  imobiliare_ro_authorized = {settings.scrape_imobiliare_ro_authorized}")
print(f"  romimo_enabled           = {settings.scrape_romimo_enabled}")

print()
print("=" * 70)
print("2. ULTIMELE 10 JOBURI")
print("=" * 70)
with Session(engine) as s:
    jobs = s.exec(
        select(ScrapeJob).order_by(ScrapeJob.id.desc()).limit(10)
    ).all()
    if not jobs:
        print("  (niciun job în DB)")
    for j in jobs:
        print(f"  #{j.id} | {j.source_name:15} | {j.status:10} | found={j.listings_found:4} created={j.listings_created:4}")
        if j.error_message:
            print(f"       ERROR: {j.error_message[:200]}")

print()
print("=" * 70)
print("3. TEST DIRECT ADAPTOARE (1 pagina)")
print("=" * 70)

for key in ("imobiliare_ro", "romimo"):
    print(f"\n--- {key} ---")
    try:
        from app.modules.scraping.registry import get_adapter
        adapter = get_adapter(key)
        listings = adapter.scrape_all(max_pages=1)
        print(f"  OK: {len(listings)} listings")
        for l in listings[:3]:
            print(f"    - {l.title[:50]} | {l.price_eur} | {l.location_raw}")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc(limit=3)
