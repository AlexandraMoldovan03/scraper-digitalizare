import pytest
from app.modules.scraping.publi24.localities import normalize_locality, extract_locality_from_sources


def test_alba_iulia_with_diacritics():
    result = normalize_locality("Alba Iulia")
    assert result.canonical == "Alba Iulia"
    assert result.confidence in ("high", "medium")


def test_alba_iulia_without_diacritics():
    result = normalize_locality("alba iulia")
    assert result.canonical == "Alba Iulia"


def test_sebes_no_diacritics():
    result = normalize_locality("Sebes")
    assert result.canonical == "Sebeș"


def test_cugir():
    result = normalize_locality("Cugir")
    assert result.canonical == "Cugir"


def test_aiud():
    result = normalize_locality("Aiud")
    assert result.canonical == "Aiud"


def test_campeni_no_diacritics():
    result = normalize_locality("Campeni")
    assert result.canonical == "Câmpeni"


def test_unknown_locality():
    result = normalize_locality("Xyz")
    assert result.canonical is None
    assert result.confidence == "low"


def test_extract_from_url_alba_iulia():
    url = "https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/alba/alba-iulia/anunt-12345.html"
    result = extract_locality_from_sources(url, None, None, None, None, None)
    assert result.canonical == "Alba Iulia"
    assert result.source == "url"


def test_extract_from_url_sebes():
    url = "https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/alba/sebes/anunt-99999.html"
    result = extract_locality_from_sources(url, None, None, None, None, None)
    assert result.canonical == "Sebeș"
    assert result.source == "url"


def test_extract_locality_source_priority():
    # URL should override description
    url = "https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/alba/aiud/anunt-111.html"
    result = extract_locality_from_sources(
        url,
        json_ld_locality=None,
        breadcrumb_locality=None,
        page_title=None,
        title=None,
        description="Apartament de vânzare în Blaj",
    )
    assert result.canonical == "Aiud"
    assert result.source == "url"


def test_json_ld_locality_used_when_url_unknown():
    url = "https://www.publi24.ro/anunturi/imobiliare/de-vanzare/apartamente/alba/anunt-111.html"
    result = extract_locality_from_sources(
        url,
        json_ld_locality="Blaj",
        breadcrumb_locality=None,
        page_title=None,
        title=None,
        description=None,
    )
    assert result.canonical == "Blaj"
    assert result.source == "json_ld"
