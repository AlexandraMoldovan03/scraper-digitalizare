"""
Fix surse în DB:
1. Setează slug-urile lipsă pentru Publi24 și Imobiliare.ro
2. Adaugă Romimo dacă lipsește
"""
from dotenv import load_dotenv
load_dotenv('/Users/alexandramoldovan/scraper-digitalizare/backend/.env')

import sqlalchemy as sa

DATABASE_URL = __import__('os').environ["DATABASE_URL"]
engine = sa.create_engine(DATABASE_URL)

SOURCES = [
    {"name": "Publi24",       "slug": "publi24",        "base_url": "https://www.publi24.ro"},
    {"name": "Imobiliare.ro", "slug": "imobiliare_ro",  "base_url": "https://www.imobiliare.ro"},
    {"name": "Romimo",        "slug": "romimo",          "base_url": "https://www.romimo.ro"},
    {"name": "OLX",           "slug": "olx",             "base_url": "https://www.olx.ro"},
    {"name": "Storia",        "slug": "storia",          "base_url": "https://www.storia.ro"},
]

with engine.begin() as conn:
    for src in SOURCES:
        existing = conn.execute(
            sa.text("SELECT id, slug FROM sources WHERE name = :name"),
            {"name": src["name"]}
        ).fetchone()

        if existing:
            src_id, current_slug = existing
            if current_slug != src["slug"]:
                conn.execute(
                    sa.text("UPDATE sources SET slug = :slug WHERE id = :id"),
                    {"slug": src["slug"], "id": src_id}
                )
                print(f"✓ Updated slug for {src['name']}: {current_slug!r} → {src['slug']!r}")
            else:
                print(f"  OK {src['name']} (slug={current_slug})")
        else:
            conn.execute(
                sa.text("""
                    INSERT INTO sources (name, slug, base_url, is_active, created_at)
                    VALUES (:name, :slug, :base_url, TRUE, NOW())
                """),
                src
            )
            print(f"✓ Created source: {src['name']} (slug={src['slug']})")

print("\nGata. Surse în DB:")
with engine.connect() as conn:
    rows = conn.execute(sa.text("SELECT id, name, slug, is_active FROM sources ORDER BY id")).fetchall()
    for row in rows:
        print(f"  id={row[0]} | {row[1]} | slug={row[2]} | active={row[3]}")
