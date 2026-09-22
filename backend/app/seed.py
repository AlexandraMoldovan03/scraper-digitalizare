from sqlmodel import Session, select

from app.database.session import engine
from app.modules.organizations.models import Organization
from app.modules.market.models import Source, City


def get_or_create(session, model, where_field, where_value, **data):
    statement = select(model).where(where_field == where_value)
    existing = session.exec(statement).first()

    if existing:
        return existing, False

    obj = model(**data)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj, True


def seed_organizations(session: Session):
    organization, created = get_or_create(
        session,
        Organization,
        Organization.slug,
        "demo-agency",
        name="Demo Agency",
        slug="demo-agency",
        subscription_plan="free",
        is_active=True,
    )

    print(f"Organization: {organization.name} | created={created}")


def seed_sources(session: Session):
    sources = [
        {
            "name": "OLX",
            "base_url": "https://www.olx.ro",
        },
        {
            "name": "Publi24",
            "base_url": "https://www.publi24.ro",
        },
        {
            "name": "Storia",
            "base_url": "https://www.storia.ro",
        },
        {
            "name": "Imobiliare.ro",
            "base_url": "https://www.imobiliare.ro",
        },
    ]

    for source in sources:
        obj, created = get_or_create(
            session,
            Source,
            Source.name,
            source["name"],
            name=source["name"],
            base_url=source["base_url"],
            is_active=True,
        )

        print(f"Source: {obj.name} | created={created}")


def seed_cities(session: Session):
    cities = [
        {
            "name": "Alba Iulia",
            "county": "Alba",
            "latitude": 46.0667,
            "longitude": 23.5833,
        },
        {
            "name": "Sebeș",
            "county": "Alba",
            "latitude": 45.9565,
            "longitude": 23.5710,
        },
        {
            "name": "Aiud",
            "county": "Alba",
            "latitude": 46.3101,
            "longitude": 23.7213,
        },
        {
            "name": "Blaj",
            "county": "Alba",
            "latitude": 46.1751,
            "longitude": 23.9140,
        },
        {
            "name": "Cugir",
            "county": "Alba",
            "latitude": 45.8365,
            "longitude": 23.3690,
        },
        {
            "name": "Ocna Mureș",
            "county": "Alba",
            "latitude": 46.3833,
            "longitude": 23.8500,
        },
    ]

    for city in cities:
        obj, created = get_or_create(
            session,
            City,
            City.name,
            city["name"],
            name=city["name"],
            county=city["county"],
            latitude=city["latitude"],
            longitude=city["longitude"],
            is_active=True,
        )

        print(f"City: {obj.name} | created={created}")


def main():
    with Session(engine) as session:
        seed_organizations(session)
        seed_sources(session)
        seed_cities(session)

    print("Seed completed.")


if __name__ == "__main__":
    main()
