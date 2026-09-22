"""
Incarca localitatile din Alba + judetele invecinate in tabela cities.

Sursa: nomenclatorul SIRUTA (Institutul National de Statistica), nivel 3
= localitati reale (sate + localitati urbane).

De ce si judetele vecine: cautarile pe Alba de pe Storia returneaza si
anunturi din Cluj, Mures, Sibiu etc. (proximitate de granita sau etichetare
gresita la sursa). Le incarcam cu judetul corect, ca sa apara etichetate,
nu ca "Localitate necunoscuta".

Fisier: localities_alba_region.json  (Alba + Cluj, Mures, Sibiu, Hunedoara,
Arad, Bihor, Valcea — 3538 localitati)

Re-rulabil: adauga doar ce lipseste, comparand nume+judet.

Ruleaza: PYTHONPATH=. python load_localities.py
"""
import json
import unicodedata
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from sqlmodel import Session, select

from app.database.session import engine
from app.modules.market.models import City

HERE = Path(__file__).parent
DATA = HERE / "localities_alba_region.json"
LEGACY = HERE / "alba_localities.json"


def norm(text: str) -> str:
    """Aceeasi normalizare ca in service._strip_diacritics."""
    unified = (text or "").replace("î", "â").replace("Î", "Â")
    decomposed = unicodedata.normalize("NFKD", unified)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = plain.replace("ș", "s").replace("Ș", "S").replace("ț", "t").replace("Ț", "T")
    return " ".join(plain.lower().split())


if DATA.exists():
    entries = json.loads(DATA.read_text(encoding="utf-8"))
elif LEGACY.exists():
    print("localities_alba_region.json lipseste — folosesc alba_localities.json")
    entries = [
        {**e, "county": "Alba", "county_code": "AB"}
        for e in json.loads(LEGACY.read_text(encoding="utf-8"))
    ]
else:
    raise SystemExit("Lipseste fisierul cu localitati.")

print(f"Localitati in fisier: {len(entries)}")
for county, n in Counter(e["county"] for e in entries).most_common():
    print(f"  {county:12} {n}")

with Session(engine) as session:
    existing = session.exec(select(City)).all()
    before = len(existing)

    # Index pe (nume normalizat, judet normalizat) si pe nume simplu,
    # ca sa nu duplicam intrarile vechi care nu aveau judet setat.
    have_pairs = {(norm(c.name), norm(c.county or "")) for c in existing}
    have_names_no_county = {norm(c.name) for c in existing if not (c.county or "").strip()}

    added = skipped = 0
    for e in entries:
        key = (norm(e["name"]), norm(e["county"]))
        if key in have_pairs:
            skipped += 1
            continue
        if e["county"] == "Alba" and norm(e["name"]) in have_names_no_county:
            skipped += 1
            continue

        session.add(City(
            name=e["name"],
            county=e["county"],
            county_code=e.get("county_code"),
            locality_type=e.get("locality_type", "village"),
            is_active=True,
        ))
        have_pairs.add(key)
        added += 1

        if added % 200 == 0:
            session.commit()

    session.commit()
    after = len(session.exec(select(City)).all())

print(f"\nAdaugate : {added}")
print(f"Existau  : {skipped}")
print(f"Total cities: {before} -> {after}")
