import unittest

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database.session import get_session
from app.main import app
from app.modules.auth.service import create_access_token, hash_password
from app.modules.clients.models import Client
from app.modules.market.models import MarketListing
from app.modules.opportunities.models import Opportunity
from app.modules.organizations.models import Organization
from app.modules.users.models import User


class MultiTenancyTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        def override_get_session():
            yield self.session

        app.dependency_overrides[get_session] = override_get_session
        self.client = TestClient(app)
        self.data = self.seed_base_data()

    def tearDown(self):
        self.client.close()
        self.session.close()
        app.dependency_overrides.clear()

    def create_organization(self, org_id: int, name: str, slug: str) -> Organization:
        organization = Organization(
            id=org_id,
            name=name,
            slug=slug,
            subscription_plan="free",
            is_active=True,
        )
        self.session.add(organization)
        self.session.commit()
        self.session.refresh(organization)
        return organization

    def create_user(
        self,
        user_id: int,
        organization_id: int,
        email: str,
        role: str = "agent",
        session_id: str | None = None,
    ) -> User:
        user = User(
            id=user_id,
            organization_id=organization_id,
            email=email,
            password_hash=hash_password("password123"),
            full_name=email.split("@")[0].title(),
            role=role,
            is_active=True,
            session_id=session_id or f"session-{user_id}",
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    def auth_headers_for(self, user: User) -> dict[str, str]:
        token = create_access_token(user.id, user.email, user.session_id or "")
        return {"Authorization": f"Bearer {token}"}

    def seed_base_data(self):
        self.create_organization(1, "Agency A", "agency-a")
        self.create_organization(2, "Agency B", "agency-b")

        user_a = self.create_user(1, 1, "a@example.com")
        user_b = self.create_user(2, 2, "b@example.com")

        client_a = Client(organization_id=1, full_name="Client A", client_type="buyer")
        client_b = Client(organization_id=2, full_name="Client B", client_type="buyer")
        self.session.add(client_a)
        self.session.add(client_b)
        self.session.commit()
        self.session.refresh(client_a)
        self.session.refresh(client_b)

        listing = MarketListing(
            raw_listing_id=1,
            source_id=1,
            city_id=None,
            url="https://example.com/listing-1",
            title="Listing 1",
            description="Listing",
            price_eur=100000,
            currency="EUR",
            rooms=2,
            surface_m2=50,
            price_per_m2=2000,
            property_type="apartment",
            transaction_type="sale",
            is_active=True,
        )
        self.session.add(listing)
        self.session.commit()
        self.session.refresh(listing)

        opp_a = Opportunity(
            organization_id=1,
            property_id=1,
            market_listing_id=listing.id,
            client_id=client_a.id,
            score=90,
            reason="A only",
            status="new",
        )
        opp_b = Opportunity(
            organization_id=2,
            property_id=2,
            market_listing_id=listing.id,
            client_id=client_b.id,
            score=75,
            reason="B only",
            status="new",
        )
        self.session.add(opp_a)
        self.session.add(opp_b)
        self.session.commit()

        return {
            "user_a": user_a,
            "user_b": user_b,
            "client_a": client_a,
            "client_b": client_b,
        }

    def test_organization_a_sees_only_own_clients(self):
        response = self.client.get(
            "/api/v1/clients/",
            headers=self.auth_headers_for(self.data["user_a"]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["full_name"], "Client A")
        self.assertEqual(payload[0]["organization_id"], 1)

    def test_organization_a_cannot_see_clients_of_organization_b_even_with_manual_query_param(self):
        response = self.client.get(
            "/api/v1/clients/?organization_id=2",
            headers=self.auth_headers_for(self.data["user_a"]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["full_name"], "Client A")
        self.assertTrue(all(item["organization_id"] == 1 for item in payload))

    def test_organization_a_cannot_create_client_for_organization_b(self):
        response = self.client.post(
            "/api/v1/clients/?organization_id=2",
            headers=self.auth_headers_for(self.data["user_a"]),
            json={"full_name": "Injected Client", "client_type": "buyer"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["organization_id"], 1)

        created = self.session.exec(
            select(Client).where(Client.full_name == "Injected Client")
        ).one()
        self.assertEqual(created.organization_id, 1)

    def test_organization_a_cannot_see_opportunities_of_organization_b(self):
        response = self.client.get(
            "/api/v1/opportunities/feed?organization_id=2",
            headers=self.auth_headers_for(self.data["user_a"]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["reason"], "A only")
        self.assertEqual(payload[0]["client"]["full_name"], "Client A")

    def test_manual_request_cannot_switch_tenant_for_generate_endpoint(self):
        response = self.client.post(
            "/api/v1/opportunities/generate?organization_id=2",
            headers=self.auth_headers_for(self.data["user_a"]),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["clients_checked"], 1)

    def test_private_requests_without_authentication_are_rejected(self):
        endpoints = [
            ("get", "/api/v1/clients/", None),
            ("post", "/api/v1/clients/", {"full_name": "No Auth", "client_type": "buyer"}),
            ("get", "/api/v1/opportunities/", None),
            ("get", "/api/v1/opportunities/feed", None),
            ("post", "/api/v1/opportunities/generate", None),
        ]

        for method, url, body in endpoints:
            kwargs = {"json": body} if body is not None else {}
            response = getattr(self.client, method)(url, **kwargs)
            self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
