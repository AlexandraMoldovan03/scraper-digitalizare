"""Test adaptor Storia — 2 pagini per categorie."""
import logging
from dotenv import load_dotenv
load_dotenv('/Users/alexandramoldovan/scraper-digitalizare/backend/.env')

logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.modules.scraping.registry import get_adapter

adapter = get_adapter("storia")
listings = adapter.scrape_all(max_pages=2)

print()
print("=" * 70)
print(f"TOTAL: {len(listings)} anunturi")
print("=" * 70)

for l in listings[:8]:
    print(f"\n  {l.title[:62]}")
    print(f"    pret={l.price_eur} {l.original_currency or ''}  supraf={l.surface_m2}  camere={l.rooms}")
    print(f"    localitate={l.location_raw!r}  zona={l.zone_raw!r}")
    print(f"    vanzator={l.seller_type} {l.agency_name or ''}")
    print(f"    tip={l.property_type}/{l.transaction_type}  imagini={l.image_count}")
    print(f"    id={l.external_id}  publicat={l.published_at}")
    if l.quality_warnings:
        print(f"    ATENTIE: {l.quality_warnings}")

# Sumar calitate
print()
print("=" * 70)
print("SUMAR")
print("=" * 70)
from collections import Counter
print("  localitati:", Counter(l.location_raw for l in listings).most_common(12))
print("  vanzator  :", Counter(l.seller_type for l in listings).most_common())
print("  tip       :", Counter(l.property_type for l in listings).most_common())
missing = Counter(w for l in listings for w in l.quality_warnings)
print("  lipsuri   :", missing.most_common() or "niciuna")
print(f"  fara pret : {sum(1 for l in listings if l.price_eur is None)}/{len(listings)}")
print(f"  hpr sarite: verificat in adaptor (robots.txt Disallow /hpr/)")
