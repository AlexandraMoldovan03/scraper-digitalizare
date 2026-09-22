"""seed all communes of Alba county

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-23

Adaugă toate localitățile (comune) din județul Alba care lipsesc din seed-ul anterior.
Idempotent: ON CONFLICT DO NOTHING.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Toate localitățile județului Alba neacoperite de seed-ul anterior
# (municipiile și orașele + 5 comune din d4e5f6a7b8c9 sunt deja acolo)
COMMUNES = [
    # Comune rămase — ordine alfabetică
    "Albac",
    "Almașu Mare",
    "Arieșeni",
    "Avram Iancu",
    "Berghin",
    "Bistra",
    "Blandiana",
    "Bucerdea Grânoasă",
    "Bucium",
    "Câlnic",
    "Cenade",
    "Ceru-Băcăinți",
    "Cetatea de Baltă",
    "Ciuruleasa",
    "Crăciunelu de Jos",
    "Cut",
    "Daia Română",
    "Doștat",
    "Fărău",
    "Gârbova",
    "Gârda de Sus",
    "Hopârta",
    "Horea",
    "Întregalde",
    "Jidvei",
    "Livezile",
    "Lopadea Nouă",
    "Lunca Mureșului",
    "Lupșa",
    "Meteș",
    "Mihalț",
    "Mirăslău",
    "Mogoș",
    "Noslac",
    "Ocoliș",
    "Ohaba",
    "Pianu",
    "Ponor",
    "Poșaga",
    "Râmetea",
    "Roșia de Secaș",
    "Roșia Montană",
    "Sălciua",
    "Săliștea",
    "Scărișoara",
    "Silivaș",
    "Sohodol",
    "Stremț",
    "Șibot",
    "Șona",
    "Șpring",
    "Șugag",
    "Vadu Moților",
    "Valea Lungă",
    "Vidra",
    "Vințu de Jos",
]


def upgrade() -> None:
    for name in COMMUNES:
        op.execute(
            sa.text(
                "INSERT INTO cities (name, county, county_code, locality_type, is_active) "
                "SELECT :name, 'Alba', 'AB', 'comună', TRUE "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM cities WHERE name = :name AND county_code = 'AB'"
                ")"
            ).bindparams(name=name)
        )


def downgrade() -> None:
    for name in COMMUNES:
        op.execute(
            sa.text("DELETE FROM cities WHERE name = :name AND county_code = 'AB'").bindparams(
                name=name
            )
        )
