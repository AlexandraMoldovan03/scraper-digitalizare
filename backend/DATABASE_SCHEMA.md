cat > backend/DATABASE_SCHEMA.md << 'EOF'
# PropLens Database Schema

## Tip produs

SaaS intern pentru agenții imobiliare.

Nu este portal public.
Nu este pentru proprietari.
Este folosit doar de agenți, manageri și owneri de agenții.

---

## Principiu principal

Platforma este multi-tenant.

Fiecare agenție este o organizație separată.

Aproape toate tabelele importante au:

- organization_id

Astfel, agenția A nu poate vedea datele agenției B.

---

## Tabele MVP

### organizations

Agențiile imobiliare.

Coloane:
- id
- name
- slug
- subscription_plan
- is_active
- created_at

---

### users

Agenții și managerii dintr-o agenție.

Coloane:
- id
- organization_id
- email
- password_hash
- full_name
- role
- is_active
- created_at

Roluri:
- owner
- manager
- agent

---

### sources

Sursele externe monitorizate.

Coloane:
- id
- name
- base_url
- is_active
- created_at

Exemple:
- OLX
- Publi24
- Storia
- Imobiliare.ro

---

### cities

Orașele urmărite.

Coloane:
- id
- name
- county
- latitude
- longitude
- is_active

---

### market_listings_raw

Date brute colectate de pe site-uri.

Nu se modifică după salvare.

Coloane:
- id
- source_id
- external_id
- url
- title_raw
- description_raw
- price_raw
- city_raw
- location_raw
- surface_raw
- rooms_raw
- raw_payload
- raw_data_hash
- first_seen_at
- last_seen_at
- is_active

---

### market_listings

Date normalizate din anunțurile externe.

Coloane:
- id
- raw_listing_id
- source_id
- city_id
- url
- title
- description
- price_eur
- currency
- rooms
- surface_m2
- price_per_m2
- property_type
- transaction_type
- latitude
- longitude
- published_at
- first_seen_at
- last_seen_at
- is_active

---

### properties

Proprietăți unice deduplicate.

O proprietate poate avea mai multe anunțuri externe.

Coloane:
- id
- city_id
- title
- description_summary
- property_type
- transaction_type
- rooms
- surface_m2
- land_surface_m2
- floor
- total_floors
- year_built
- latitude
- longitude
- address_text
- quality_score
- opportunity_score
- is_active
- created_at
- updated_at

---

### property_market_listings

Legătură many-to-many între proprietăți și anunțuri externe.

Coloane:
- id
- property_id
- market_listing_id
- similarity_score
- created_at

---

### organization_properties

Proprietățile urmărite de o agenție.

Aici apare organization_id.

Coloane:
- id
- organization_id
- property_id
- status
- assigned_user_id
- notes
- created_at
- updated_at

Statusuri:
- new
- contacted
- viewing_scheduled
- negotiating
- won
- lost
- ignored

---

### clients

Clienții agenției.

Coloane:
- id
- organization_id
- assigned_user_id
- full_name
- phone
- email
- client_type
- budget_min_eur
- budget_max_eur
- preferred_city_id
- min_rooms
- max_rooms
- min_surface_m2
- notes
- created_at
- updated_at

Client types:
- buyer
- renter
- investor

---

### opportunities

Oportunități detectate pentru agenție.

Coloane:
- id
- organization_id
- property_id
- market_listing_id
- client_id
- score
- reason
- status
- assigned_user_id
- created_at

Statusuri:
- new
- reviewed
- contacted
- dismissed

---

### tasks

Task-uri interne pentru agenți.

Coloane:
- id
- organization_id
- assigned_user_id
- related_client_id
- related_property_id
- title
- description
- due_at
- status
- created_at

Statusuri:
- todo
- in_progress
- done
- cancelled

---

### showings

Vizionări programate.

Coloane:
- id
- organization_id
- client_id
- property_id
- assigned_user_id
- scheduled_at
- status
- notes
- created_at

Statusuri:
- scheduled
- completed
- cancelled
- no_show

---

### price_history

Istoric prețuri pentru proprietăți.

Coloane:
- id
- property_id
- source_id
- price_eur
- price_per_m2
- detected_at

---

### scrape_jobs

Istoric rulări scraper.

Coloane:
- id
- source_id
- city_id
- status
- started_at
- finished_at
- listings_found
- listings_inserted
- listings_updated
- error_message

---

## Indexuri critice

### security / multi-tenant

- users.organization_id
- clients.organization_id
- opportunities.organization_id
- tasks.organization_id
- showings.organization_id
- organization_properties.organization_id

### listings

- unique(market_listings_raw.url)
- unique(market_listings.url)
- index(market_listings.city_id)
- index(market_listings.price_per_m2)
- index(market_listings.first_seen_at)
- index(market_listings.source_id)

### properties

- index(properties.city_id)
- index(properties.opportunity_score)
- index(properties.rooms)
- index(properties.surface_m2)

### opportunities

- index(opportunities.organization_id, status)
- index(opportunities.score)

---

## Decizie MVP

În prima versiune implementăm:

- organizations
- users
- sources
- cities
- market_listings_raw
- market_listings
- properties
- property_market_listings
- organization_properties
- clients
- opportunities
- tasks
- price_history
- scrape_jobs

Nu implementăm încă:
- showings
- billing
- audit logs
- AI embeddings
- documente
