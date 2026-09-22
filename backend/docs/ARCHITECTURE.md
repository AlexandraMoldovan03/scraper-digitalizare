# Platform Architecture

## Produs

Platformă SaaS internă pentru agenții imobiliare.

Utilizatori:
- owner de agenție
- manager
- agent

Nu există:
- conturi pentru proprietari
- portal public
- listare manuală publică de către proprietari
- marketplace pentru cumpărători finali

---

## Model de business

Platforma este vândută agențiilor imobiliare.

Fiecare agenție are:
- cont propriu
- utilizatori proprii
- clienți proprii
- task-uri proprii
- oportunități proprii
- proprietăți urmărite proprii

Datele colectate din piață sunt globale.

Datele interne ale agenției sunt private.

---

## Multi-tenancy

Tabelul principal este:

organizations

Fiecare utilizator aparține unei organizații.

Tabele care trebuie izolate pe agenție:
- users
- clients
- organization_properties
- opportunities
- tasks
- showings, mai târziu
- notes, mai târziu

Aceste tabele au organization_id.

Regulă critică:
Frontend-ul nu are voie să trimită organization_id pentru operații normale.

Backend-ul ia organization_id din utilizatorul autentificat.

Asta previne accesul unei agenții la datele altei agenții.

---

## Date globale

Aceste date nu aparțin unei singure agenții:

- sources
- cities
- market_listings_raw
- market_listings
- properties
- property_market_listings
- price_history
- scrape_jobs

Motiv:
Dacă același anunț apare pe OLX, nu vrem să îl salvăm separat pentru fiecare agenție.

Îl colectăm o singură dată.

Apoi generăm oportunități diferite pentru fiecare agenție, în funcție de clienții și filtrele ei.

---

## Flux de date

1. Scheduler pornește scraperul.
2. Scraperul colectează anunțuri externe.
3. Datele brute intră în market_listings_raw.
4. Normalizer transformă datele brute în date curate.
5. Datele curate intră în market_listings.
6. Deduplicatorul decide dacă anunțul aparține unei proprietăți existente.
7. Dacă nu există, creează o proprietate nouă în properties.
8. Se salvează legătura în property_market_listings.
9. Se actualizează price_history.
10. Opportunity Engine compară proprietățile cu criteriile agențiilor.
11. Pentru fiecare agenție relevantă se creează opportunity.

---

## Servicii

### API Service

Responsabilități:
- autentificare
- utilizatori
- clienți
- task-uri
- oportunități
- proprietăți urmărite
- dashboard
- căutare

Nu face scraping.

---

### Scraper Service

Responsabilități:
- colectare OLX
- colectare Publi24
- mai târziu Storia și Imobiliare.ro
- salvare date brute
- raportare scrape_jobs

Nu conține logică de dashboard.

---

### Normalization Service

Responsabilități:
- transformă prețuri în numere
- transformă mp în surface_m2
- extrage camere
- normalizează orașe
- calculează price_per_m2
- curăță titluri și descrieri

---

### Deduplication Service

Responsabilități:
- compară anunțuri similare
- decide dacă un anunț aparține unei proprietăți existente
- folosește reguli la început
- folosește embeddings AI mai târziu

Reguli MVP:
- același oraș
- același număr de camere
- suprafață apropiată
- preț apropiat
- titlu asemănător

---

### Opportunity Service

Responsabilități:
- detectează anunțuri sub media pieței
- compară proprietățile cu clienții agenției
- creează oportunități pentru agenți
- explică motivul oportunității

Exemplu:
"Apartament 2 camere în Alba Iulia, 18% sub media zonei. Se potrivește cu clientul Maria Popescu."

---

## Tehnologii

Backend:
- Python
- FastAPI
- SQLModel
- Alembic
- Pydantic Settings

Database:
- Neon PostgreSQL

Scraping:
- Playwright
- BeautifulSoup
- httpx

Queue / cache, mai târziu:
- Redis / Upstash

Frontend, mai târziu:
- Next.js
- Tailwind
- Leaflet pentru hartă

---

## Structură backend

app/

- core/
  - config
  - security

- database/
  - session
  - base

- modules/
  - organizations
  - users
  - clients
  - properties
  - market
  - opportunities
  - tasks
  - scraping

- shared/
  - utils
  - enums
  - exceptions

---

## Module MVP

### organizations

Gestionează agențiile.

### users

Gestionează agenții, managerii și ownerii.

### market

Gestionează datele externe:
- sources
- cities
- market_listings_raw
- market_listings

### properties

Gestionează proprietăți deduplicate:
- properties
- property_market_listings
- price_history

### clients

Gestionează clienții agenției.

### opportunities

Gestionează oportunitățile generate pentru agenție.

### tasks

Gestionează task-urile interne ale agenților.

### scraping

Gestionează rulările scraperelor.

---

## Ce NU implementăm în MVP

- billing
- abonamente plătite
- audit logs
- GraphQL
- aplicație mobilă
- AI embeddings
- portal proprietari
- portal public
- contracte/documente
- calendar avansat

---

## Ordinea de implementare

1. Configurare proiect backend.
2. Configurare Neon PostgreSQL.
3. Configurare SQLModel.
4. Configurare Alembic.
5. Modele MVP.
6. Prima migrație.
7. Seed data: organizație demo, user demo, orașe, surse.
8. Endpoint health check.
9. Endpoint listare market listings.
10. Primul scraper Publi24 sau OLX.
11. Normalizare date.
12. Salvare în baza de date.
13. Dashboard simplu.
