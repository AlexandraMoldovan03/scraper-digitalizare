"""
Canonical locality normalization for Alba county.
Single source of truth.
"""
import re
import unicodedata
from dataclasses import dataclass

# Build a translation table that strips diacritics
_nfd = unicodedata.normalize('NFD', 'àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ'
                              'ăâîșțĂÂÎȘȚ')
STRIP_DIACRITICS_TABLE = str.maketrans(
    ''.join(c for c in unicodedata.normalize('NFD', chr(i)) for i in range(0x110000)
            if unicodedata.category(c) == 'Mn'),
    '',
) if False else str.maketrans(
    {
        ord('ă'): 'a', ord('Ă'): 'A',
        ord('â'): 'a', ord('Â'): 'A',
        ord('î'): 'i', ord('Î'): 'I',
        ord('ș'): 's', ord('Ș'): 'S',
        ord('ț'): 't', ord('Ț'): 'T',
        ord('ş'): 's', ord('Ş'): 'S',
        ord('ţ'): 't', ord('Ţ'): 'T',
        ord('á'): 'a', ord('é'): 'e', ord('í'): 'i', ord('ó'): 'o', ord('ú'): 'u',
        ord('à'): 'a', ord('è'): 'e', ord('ì'): 'i', ord('ò'): 'o', ord('ù'): 'u',
    }
)


def strip_diacritics(s: str) -> str:
    """'Sebeș' -> 'Sebes', 'Câmpeni' -> 'Campeni'"""
    # First try unicode normalization (NFD) to handle composed chars
    nfd = unicodedata.normalize('NFD', s)
    result = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    # Then apply our table for remaining known chars
    return result.translate(STRIP_DIACRITICS_TABLE)


# Canonical name -> list of known aliases/variants (with and without diacritics)
ALBA_LOCALITIES: dict[str, list[str]] = {
    # ── Municipii ─────────────────────────────────────────────────────────────
    "Alba Iulia": ["alba iulia", "alba-iulia", "alba_iulia", "albaiulia"],
    "Aiud": ["aiud"],
    "Blaj": ["blaj"],
    # ── Orașe ─────────────────────────────────────────────────────────────────
    "Sebeș": ["sebes", "sebeș", "sebesh"],
    "Cugir": ["cugir"],
    "Ocna Mureș": ["ocna mures", "ocna-mures", "ocna mureș"],
    "Zlatna": ["zlatna"],
    "Abrud": ["abrud"],
    "Câmpeni": ["campeni", "câmpeni", "campenii"],
    "Baia de Arieș": ["baia de aries", "baia-de-aries", "baia de arieș"],
    "Teiuș": ["teius", "teiuș"],
    # ── Comune ────────────────────────────────────────────────────────────────
    "Albac": ["albac"],
    "Almașu Mare": ["almasu mare", "almasu-mare", "almașu mare", "almasul mare"],
    "Arieșeni": ["arieseni", "arieșeni", "ariesenii"],
    "Avram Iancu": ["avram iancu"],
    "Berghin": ["berghin"],
    "Bistra": ["bistra"],
    "Blandiana": ["blandiana"],
    "Bucerdea Grânoasă": ["bucerdea granoasa", "bucerdea-granoasa", "bucerdea grânoasă"],
    "Bucium": ["bucium"],
    "Câlnic": ["calnic", "câlnic"],
    "Cenade": ["cenade"],
    "Ceru-Băcăinți": ["ceru bacainti", "ceru-bacainti", "ceru băcăinți", "ceru-băcăinți"],
    "Cetatea de Baltă": ["cetatea de balta", "cetatea-de-balta", "cetatea de baltă"],
    "Ciugud": ["ciugud"],
    "Ciuruleasa": ["ciuruleasa"],
    "Crăciunelu de Jos": ["craciunelu de jos", "craciunel de jos", "crăciunelu de jos"],
    "Cricău": ["cricau", "cricău"],
    "Cut": ["cut"],
    "Daia Română": ["daia romana", "daia-romana", "daia română"],
    "Doștat": ["dostat", "doștat"],
    "Fărău": ["farau", "fărău"],
    "Galda de Jos": ["galda de jos", "galda"],
    "Gârbova": ["garbova", "gârbova"],
    "Gârda de Sus": ["garda de sus", "gârda de sus", "garda-de-sus"],
    "Hopârta": ["hoparta", "hopârta"],
    "Horea": ["horea"],
    "Ighiu": ["ighiu"],
    "Întregalde": ["intregalde", "întregalde"],
    "Jidvei": ["jidvei"],
    "Livezile": ["livezile"],
    "Lopadea Nouă": ["lopadea noua", "lopadea-noua", "lopadea nouă"],
    "Lunca Mureșului": ["lunca muresului", "lunca mureșului", "lunca-muresului"],
    "Lupșa": ["lupsa", "lupșa"],
    "Meteș": ["metes", "meteș"],
    "Mihalț": ["mihalt", "mihalț"],
    "Mirăslău": ["miraslau", "mirăslău"],
    "Mogoș": ["mogos", "mogoș"],
    "Noslac": ["noslac"],
    "Ocoliș": ["ocolis", "ocoliș"],
    "Ohaba": ["ohaba"],
    "Pianu": ["pianu", "pianu de jos", "pianu de sus"],
    "Ponor": ["ponor"],
    "Poșaga": ["posaga", "poșaga"],
    "Râmetea": ["rametea", "râmetea"],
    "Roșia de Secaș": ["rosia de secas", "roșia de secaș", "rosia-de-secas"],
    "Roșia Montană": ["rosia montana", "roșia montană", "rosia-montana"],
    "Sălciua": ["salciua", "sălciua", "salciua de jos"],
    "Săliștea": ["salistea", "săliștea"],
    "Scărișoara": ["scarisoara", "scărișoara"],
    "Silivaș": ["silivas", "silivaș"],
    "Sohodol": ["sohodol"],
    "Stremț": ["stremt", "stremț"],
    "Șibot": ["sibot", "șibot"],
    "Șona": ["sona", "șona"],
    "Șpring": ["spring", "șpring"],
    "Șugag": ["sugag", "șugag"],
    "Unirea": ["unirea", "mircea voda", "mircea vodă"],
    "Vadu Moților": ["vadu motilor", "vadu moților", "vadu-motilor"],
    "Valea Lungă": ["valea lunga", "valea lungă", "valea-lunga"],
    "Vidra": ["vidra"],
    "Vințu de Jos": ["vintu de jos", "vințu de jos", "vintu-de-jos", "vinți"],
}

# Build a reverse lookup: normalized alias -> canonical name
_ALIAS_TO_CANONICAL: dict[str, str] = {}
for _canonical, _aliases in ALBA_LOCALITIES.items():
    # Add the canonical name itself (stripped of diacritics, lowercased)
    _key_canonical = strip_diacritics(_canonical).lower()
    _ALIAS_TO_CANONICAL[_key_canonical] = _canonical
    # Add all aliases (stripped of diacritics, lowercased)
    for _alias in _aliases:
        _key = strip_diacritics(_alias).lower()
        _ALIAS_TO_CANONICAL[_key] = _canonical


@dataclass
class NormalizedLocality:
    canonical: str | None      # e.g. "Alba Iulia" or None if unknown
    raw: str | None            # original string found
    confidence: str            # "high" | "medium" | "low"
    source: str                # "url" | "json_ld" | "breadcrumb" | "page_field" | "text" | "unknown"


def normalize_locality(raw: str) -> NormalizedLocality:
    """Match raw string to a canonical locality. Returns None canonical if unknown."""
    if not raw or not raw.strip():
        return NormalizedLocality(canonical=None, raw=raw, confidence="low", source="unknown")

    normalized = strip_diacritics(raw.strip()).lower()

    # Direct lookup
    if normalized in _ALIAS_TO_CANONICAL:
        return NormalizedLocality(
            canonical=_ALIAS_TO_CANONICAL[normalized],
            raw=raw,
            confidence="high",
            source="unknown",
        )

    # Try partial matches (if the normalized alias is contained within the raw)
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        if alias in normalized or normalized in alias:
            return NormalizedLocality(
                canonical=canonical,
                raw=raw,
                confidence="medium",
                source="unknown",
            )

    return NormalizedLocality(canonical=None, raw=raw, confidence="low", source="unknown")


def extract_locality_from_url(url: str) -> str | None:
    """Extract slug from URL like .../apartamente/alba/{slug}/anunt-..."""
    match = re.search(r'/apartamente/alba/([^/]+)/', url)
    if match:
        return match.group(1)
    return None


def extract_locality_from_sources(
    url: str,
    json_ld_locality: str | None,
    breadcrumb_locality: str | None,
    page_title: str | None,
    title: str | None,
    description: str | None,
) -> NormalizedLocality:
    """Priority: url > json_ld > breadcrumb > page_title > title/description.
    Returns NormalizedLocality with canonical=None if unknown."""

    # 1. URL (highest priority)
    url_slug = extract_locality_from_url(url)
    if url_slug:
        # Convert slug to readable: alba-iulia -> alba iulia
        slug_readable = url_slug.replace('-', ' ').replace('_', ' ')
        result = normalize_locality(slug_readable)
        if result.canonical:
            return NormalizedLocality(
                canonical=result.canonical,
                raw=slug_readable,
                confidence="high",
                source="url",
            )

    # 2. JSON-LD
    if json_ld_locality:
        result = normalize_locality(json_ld_locality)
        if result.canonical:
            return NormalizedLocality(
                canonical=result.canonical,
                raw=json_ld_locality,
                confidence="high",
                source="json_ld",
            )

    # 3. Breadcrumb
    if breadcrumb_locality:
        result = normalize_locality(breadcrumb_locality)
        if result.canonical:
            return NormalizedLocality(
                canonical=result.canonical,
                raw=breadcrumb_locality,
                confidence="medium",
                source="breadcrumb",
            )

    # 4. Page title — raw = canonical (nu titlul complet) pentru city lookup corect
    if page_title:
        normalized_page_title = strip_diacritics(page_title).lower()
        for alias, canonical in _ALIAS_TO_CANONICAL.items():
            if alias in normalized_page_title:
                return NormalizedLocality(
                    canonical=canonical,
                    raw=canonical,
                    confidence="medium",
                    source="page_field",
                )

    # 5. Title and description
    # raw = canonical name (nu titlul complet) — altfel city lookup eșuează
    for text_source, text_val in [("text", title), ("text", description)]:
        if text_val:
            normalized_text = strip_diacritics(text_val).lower()
            for alias, canonical in _ALIAS_TO_CANONICAL.items():
                if alias in normalized_text:
                    return NormalizedLocality(
                        canonical=canonical,
                        raw=canonical,
                        confidence="low",
                        source=text_source,
                    )

    # Use URL slug as raw even if we couldn't normalize
    raw_from_url = url_slug.replace('-', ' ').replace('_', ' ') if url_slug else None

    return NormalizedLocality(
        canonical=None,
        raw=raw_from_url or json_ld_locality or breadcrumb_locality,
        confidence="low",
        source="unknown",
    )
