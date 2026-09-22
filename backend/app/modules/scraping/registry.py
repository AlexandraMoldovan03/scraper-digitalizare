"""
Source registry — punct central de înregistrare a adaptoarelor.

Orchestratorul și schedulerul folosesc registry-ul pentru a selecta
adaptorul corect fără if/elif răspândiți în cod.

Adăugarea unei surse noi = o singură linie în SOURCE_ADAPTERS.
"""
from app.modules.scraping.adapters.base import SourceAdapter
from app.modules.scraping.adapters.publi24 import Publi24Adapter
from app.modules.scraping.adapters.imobiliare_ro import ImobiliareRoAdapter
from app.modules.scraping.adapters.romimo import RomimoAdapter
from app.modules.scraping.adapters.storia import StoriaAdapter

# ── Registry ───────────────────────────────────────────────────────────────────

SOURCE_ADAPTERS: dict[str, type[SourceAdapter]] = {
    "publi24": Publi24Adapter,
    "imobiliare_ro": ImobiliareRoAdapter,
    "romimo": RomimoAdapter,
    "storia": StoriaAdapter,
}


# ── API ────────────────────────────────────────────────────────────────────────

def get_adapter(source_key: str) -> SourceAdapter:
    """
    Returnează o instanță a adaptorului pentru sursa dată.
    Aruncă ValueError cu mesaj clar dacă sursa nu există în registry.
    """
    cls = SOURCE_ADAPTERS.get(source_key.lower())
    if cls is None:
        available = list(SOURCE_ADAPTERS.keys())
        raise ValueError(
            f"Sursă necunoscută: '{source_key}'. "
            f"Surse înregistrate: {available}"
        )
    return cls()


def list_source_keys() -> list[str]:
    """Returnează lista tuturor cheilor de surse înregistrate."""
    return list(SOURCE_ADAPTERS.keys())


def is_registered(source_key: str) -> bool:
    """Verifică dacă o sursă este înregistrată în registry."""
    return source_key.lower() in SOURCE_ADAPTERS
