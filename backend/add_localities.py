"""
Adauga localitati din Alba care lipsesc din tabela cities.

Sunt sate/localitati componente care apar in anunturi dar nu erau in
seed-ul initial de 73. Scriptul e re-rulabil: adauga doar ce lipseste.

Ruleaza: PYTHONPATH=. python add_localities.py
"""
from dotenv import load_dotenv
load_dotenv('/Users/alexandramoldovan/scraper-digitalizare/backend/.env')

from sqlmodel import Session, select

from app.database.session import engine
from app.modules.market.models import City
from app.modules.market.service import get_city_id_by_name

# Localitati din judetul Alba intalnite in anunturi si absente din seed.
# Adauga aici pe masura ce apar altele in backfill_cities.py.
MISSING = [
    "Gura Sohodol",
    "Sântimbru",
    "Războieni-Cetate",
    "Cocești",
    "Poșaga de Sus",
    "Micești",
    "Bărăbanț",
    "Pâclișa",
    "Oarda",
    "Partoș",
    "Miceşti",
    "Petrești",
    "Lancrăm",
    "Răhău",
    "Șard",
    "Bucerdea Vinoasă",
    "Telna",
    "Mesentea",
    "Benic",
    "Galda de Sus",
    "Oiejdea",
    "Totoi",
    "Drâmbar",
    "Hăpria",
    "Limba",
    "Șeușa",
    # Al doilea val, din backfill
    "Teleac",
    "Pianu de Sus",
    "Muncelu",
    "Laz",
    "Balomiru de Câmp",
    # "Iara" — aparent comuna din judetul Cluj, nu Alba. Nu o adaugam
    # ca sa nu poluam tabela; probabil anunt etichetat gresit la sursa.
]

with Session(engine) as session:
    added = skipped = 0

    for name in MISSING:
        # Folosim matcher-ul cu diacritice ca sa nu duplicam
        if get_city_id_by_name(session, name) is not None:
            skipped += 1
            continue

        session.add(City(
            name=name,
            county="Alba",
            county_code="AB",
            locality_type="village",
            is_active=True,
        ))
        added += 1
        print(f"  + {name}")

    session.commit()

    total = len(session.exec(select(City)).all())
    print(f"\nAdaugate: {added} | existau deja: {skipped}")
    print(f"Total localitati in DB: {total}")
