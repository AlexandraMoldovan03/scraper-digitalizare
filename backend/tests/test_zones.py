from app.modules.scraping.publi24.zones import normalize_zone, extract_zone_from_text


def test_cetate():
    zone_raw, zone_normalized = normalize_zone("cetate")
    assert zone_normalized == "Cetate"


def test_ampoi_iii_alias():
    # "cartier Ampoi III" should map to "Ampoi 3"
    zone_raw, zone_normalized = normalize_zone("cartier Ampoi III")
    assert zone_normalized == "Ampoi 3"


def test_strip_prefix_zona():
    # "zona Centru" should strip "zona " prefix and map to "Centru"
    zone_raw, zone_normalized = normalize_zone("zona Centru")
    assert zone_normalized == "Centru"


def test_unknown_zone_returns_none():
    zone_raw, zone_normalized = normalize_zone("Marginea de Sus")
    assert zone_normalized is None
    assert zone_raw == "Marginea de Sus"


def test_zone_extraction_from_title():
    zone_raw, zone_normalized = extract_zone_from_text(
        title="Apartament 2 camere zona Cetate Alba Iulia",
        description=None,
        city_canonical="Alba Iulia",
    )
    assert zone_normalized == "Cetate"


def test_listing_valid_without_zone():
    # Zone None doesn't break anything
    zone_raw, zone_normalized = extract_zone_from_text(
        title="Apartament 3 camere",
        description="Apartament frumos de vanzare",
        city_canonical="Alba Iulia",
    )
    # Either None or some zone — no exception should be raised
    assert isinstance(zone_normalized, (str, type(None)))


def test_zone_not_extracted_for_other_city():
    # Zones are only for Alba Iulia — should return None for Sebes
    zone_raw, zone_normalized = extract_zone_from_text(
        title="Apartament 2 camere zona Cetate",
        description=None,
        city_canonical="Sebeș",
    )
    assert zone_raw is None
    assert zone_normalized is None


def test_ampoi_2_alias():
    zone_raw, zone_normalized = normalize_zone("Ampoi II")
    assert zone_normalized == "Ampoi 2"
