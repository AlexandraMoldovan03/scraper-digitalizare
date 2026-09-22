"""
Script one-shot: creează organizație + user admin în Neon.
Rulează din directorul backend/:
    python create_admin.py
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import sqlalchemy as sa

DATABASE_URL = os.environ["DATABASE_URL"]
engine = sa.create_engine(DATABASE_URL)

EMAIL     = "admin@agentie.ro"
PASSWORD  = "Admin1234!"
FULL_NAME = "Admin"
ORG_NAME  = "AgencyIntel"
ORG_SLUG  = "agencyintel"

# --- hash parola cu aceeași librărie folosită în app ---
from pwdlib import PasswordHash
hasher = PasswordHash.recommended()
password_hash = hasher.hash(PASSWORD)

with engine.begin() as conn:
    # 1. Creează organizația dacă nu există
    existing_org = conn.execute(
        sa.text("SELECT id FROM organizations WHERE slug = :slug"),
        {"slug": ORG_SLUG}
    ).fetchone()

    if existing_org:
        org_id = existing_org[0]
        print(f"Organizație existentă: id={org_id}")
    else:
        org_id = conn.execute(
            sa.text("""
                INSERT INTO organizations (name, slug, subscription_plan, is_active, created_at)
                VALUES (:name, :slug, 'pro', TRUE, NOW())
                RETURNING id
            """),
            {"name": ORG_NAME, "slug": ORG_SLUG}
        ).scalar()
        print(f"Organizație creată: id={org_id}")

    # 2. Creează userul dacă nu există
    existing_user = conn.execute(
        sa.text("SELECT id FROM users WHERE email = :email"),
        {"email": EMAIL}
    ).fetchone()

    if existing_user:
        # Resetează parola
        conn.execute(
            sa.text("UPDATE users SET password_hash = :ph WHERE email = :email"),
            {"ph": password_hash, "email": EMAIL}
        )
        print(f"User existent — parolă resetată: {EMAIL}")
    else:
        conn.execute(
            sa.text("""
                INSERT INTO users (organization_id, email, password_hash, full_name, role, is_active, created_at)
                VALUES (:org_id, :email, :ph, :full_name, 'admin', TRUE, NOW())
            """),
            {"org_id": org_id, "email": EMAIL, "ph": password_hash, "full_name": FULL_NAME}
        )
        print(f"User creat: {EMAIL}")

print(f"\n✓ Gata. Loghează-te cu:")
print(f"  Email:  {EMAIL}")
print(f"  Parolă: {PASSWORD}")
