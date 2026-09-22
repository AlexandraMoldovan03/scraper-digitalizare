import httpx

from app.modules.scraping.publi24.scraper import (
    scrape_publi24_all_pages,
    scrape_publi24_list_page,
)


API_BASE_URL = "http://127.0.0.1:8000/api/v1"


def get_source_id(client: httpx.Client, source_name: str) -> int:
    response = client.get(f"{API_BASE_URL}/market/sources")
    response.raise_for_status()

    for source in response.json():
        if source["name"].lower() == source_name.lower():
            return source["id"]

    raise RuntimeError(f"Sursa nu a fost găsită: {source_name}")


def get_city_id_by_name(cities: list[dict], city_name: str) -> int | None:
    """Find city_id by name (case-insensitive). Does NOT create unknown cities."""
    if not city_name:
        return None
    city_name_lower = city_name.lower()
    for city in cities:
        if city["name"].lower() == city_name_lower:
            return city["id"]
    return None


def import_publi24_listings(
    limit_per_page: int | None = None,
    max_pages: int = 20,
    all_pages: bool = True,
) -> int:
    """
    Importă anunțuri de pe Publi24.
    - all_pages=True (implicit): parcurge toate paginile din județ
    - all_pages=False: o singură pagină, limit_per_page anunțuri
    """
    if all_pages:
        scraped_listings = scrape_publi24_all_pages(
            max_pages=max_pages,
            max_listings=limit_per_page,
        )
    else:
        scraped_listings = scrape_publi24_list_page(
            limit=limit_per_page or 10
        )

    print(f"\nScraped: {len(scraped_listings)} anunțuri")

    valid_count = sum(1 for l in scraped_listings if l.data_quality == "valid")
    warning_count = sum(1 for l in scraped_listings if l.data_quality == "warning")
    print(f"  valid={valid_count}  warning={warning_count}")

    with httpx.Client(timeout=30) as client:
        source_id = get_source_id(client, "Publi24")

        # Load city list once — avoid per-listing API calls
        cities_response = client.get(f"{API_BASE_URL}/market/cities")
        cities_response.raise_for_status()
        cities_list = cities_response.json()

        # Cache pentru city lookups
        city_cache: dict[str, int | None] = {}

        saved = 0

        for listing in scraped_listings:
            city_name = listing.location_raw or "Alba Iulia"
            if city_name not in city_cache:
                city_cache[city_name] = get_city_id_by_name(cities_list, city_name)

            city_id = city_cache[city_name]

            payload = {
                "source_id": source_id,
                "city_id": city_id,
                "external_id": listing.url.split("/")[-1].replace(".html", ""),
                "url": listing.url,
                "title": listing.title,
                "description": listing.description,
                "price_eur": listing.price_eur,
                "currency": "EUR",
                "rooms": listing.rooms,
                "surface_m2": listing.surface_m2,
                "property_type": "apartment",
                "transaction_type": "sale",
                "location_raw": listing.location_raw,
                "published_at": listing.published_at.isoformat() if listing.published_at else None,
                # Zone fields
                "zone_raw": listing.zone_raw,
                "zone_normalized": listing.zone_normalized,
                # Câmpuri de calitate și imagini
                "data_quality": listing.data_quality,
                "quality_warnings": listing.quality_warnings,
                "image_urls": listing.image_urls,
            }

            response = client.post(f"{API_BASE_URL}/market/listings", json=payload)

            if response.status_code not in (200, 201):
                print(f"  [FAIL] {listing.title[:60]}")
                print(f"         {response.status_code}: {response.text[:200]}")
                continue

            data = response.json()
            quality_tag = (
                "⚠️  WARNING" if data.get("data_quality") == "warning" else "✓"
            )

            zone_display = f" | zona: {data.get('zone_normalized')}" if data.get("zone_normalized") else ""

            print(
                f"  {quality_tag} {data.get('title', '')[:50]:<50} "
                f"| {data.get('price_eur')} EUR "
                f"| {data.get('surface_m2')} mp "
                f"| {data.get('rooms') or '?'} cam."
                f"| {city_name}"
                f"{zone_display}"
            )

            if data.get("quality_warnings"):
                for w in data["quality_warnings"]:
                    print(f"         → {w}")

            saved += 1

        # Generăm oportunități automat după import
        print("\nGenerez oportunități...")
        opp_response = client.post(
            f"{API_BASE_URL}/opportunities/generate?organization_id=1"
        )
        opp_response.raise_for_status()
        print(opp_response.json())

    return saved


if __name__ == "__main__":
    import_publi24_listings()
