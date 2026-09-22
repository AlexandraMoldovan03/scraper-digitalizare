"""Zone normalization for Alba county listings."""
import re

# canonical zone -> aliases (all lowercase)
ZONE_ALIASES: dict[str, list[str]] = {
    "Cetate": ["cetate", "zona cetate", "cartier cetate"],
    "Centru": ["centru", "central", "zona centrala", "zona centrală", "centrul orasului"],
    "Ampoi 1": ["ampoi 1", "ampoi i", "ampoi1"],
    "Ampoi 2": ["ampoi 2", "ampoi ii", "ampoi2"],
    "Ampoi 3": ["ampoi 3", "ampoi iii", "ampoi3", "cartier ampoi iii", "ampoi iii"],
    "Tolstoi": ["tolstoi", "zona tolstoi"],
    "Micești": ["micesti", "micești", "zona micesti"],
    "Partoș": ["partos", "partoș", "zona partos"],
    "Bărăbanț": ["barabant", "bărăbanț", "bara bant"],
    "Orizont": ["orizont", "zona orizont"],
    "Stadion": ["stadion", "zona stadion"],
    "Mercur": ["mercur", "zona mercur"],
    "Carolina": ["carolina", "zona carolina"],
    "Dealul Furcilor": ["dealul furcilor", "deal furcilor", "furcilor"],
    "Arex": ["arex", "zona arex"],
    "Prestige": ["prestige", "zona prestige"],
}

# Build reverse lookup: normalized alias -> canonical
_ALIAS_TO_ZONE: dict[str, str] = {}
for _canonical, _aliases in ZONE_ALIASES.items():
    _ALIAS_TO_ZONE[_canonical.lower()] = _canonical
    for _alias in _aliases:
        _ALIAS_TO_ZONE[_alias.lower()] = _canonical

STRIP_PREFIXES = re.compile(
    r"^(zona|cartier|în zona|in zona|str\.|bd\.|bdul|strada|bulevardul)\s+",
    re.IGNORECASE
)


def _normalize_text(s: str) -> str:
    """Lowercase and strip diacritics for zone matching."""
    # Simple diacritic stripping for zone matching
    replacements = {
        'ă': 'a', 'â': 'a', 'î': 'i', 'ș': 's', 'ț': 't',
        'ş': 's', 'ţ': 't',
        'Ă': 'A', 'Â': 'A', 'Î': 'I', 'Ș': 'S', 'Ț': 'T',
        'Ş': 'S', 'Ţ': 'T',
    }
    for char, replacement in replacements.items():
        s = s.replace(char, replacement)
    return s.lower()


def normalize_zone(raw: str) -> tuple[str, str | None]:
    """Returns (zone_raw, zone_normalized). zone_normalized is None if unknown."""
    zone_raw = raw.strip()

    # Strip common prefixes before matching
    stripped = STRIP_PREFIXES.sub('', zone_raw).strip()

    # Try direct lookup with the stripped version
    for text_to_try in [stripped, zone_raw]:
        normalized_text = _normalize_text(text_to_try)
        if normalized_text in _ALIAS_TO_ZONE:
            return zone_raw, _ALIAS_TO_ZONE[normalized_text]

    # Try partial match: check if any alias is contained in the normalized text
    normalized_full = _normalize_text(zone_raw)
    for alias, canonical in _ALIAS_TO_ZONE.items():
        if alias in normalized_full:
            return zone_raw, canonical

    return zone_raw, None


def extract_zone_from_text(
    title: str,
    description: str | None,
    city_canonical: str | None,
) -> tuple[str | None, str | None]:
    """Returns (zone_raw, zone_normalized). Both None if not found.

    Only extracts zones when listing is in Alba Iulia (zones are Alba Iulia-specific).
    """
    # Zones are specific to Alba Iulia — only search if that's the city
    if city_canonical and city_canonical != "Alba Iulia":
        return None, None

    texts = [title, description or ""]

    for text in texts:
        normalized_text = _normalize_text(text)
        # Try each alias in order of specificity (longer aliases first)
        for alias in sorted(_ALIAS_TO_ZONE.keys(), key=len, reverse=True):
            if alias in normalized_text:
                # Find the raw excerpt around the match
                idx = normalized_text.find(alias)
                raw_excerpt = text[max(0, idx - 5): idx + len(alias) + 5].strip()
                canonical = _ALIAS_TO_ZONE[alias]
                return raw_excerpt, canonical

    return None, None
