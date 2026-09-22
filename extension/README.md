# Extensia AgencyIntel (Chrome) – analizor de anunțuri

Pe orice anunț de pe **OLX, Storia, imobiliare.ro, Publi24, Romimo** apare un panou în colțul paginii care arată:

- **dacă prețul e bun**: prețul/m² al anunțului față de mediana anunțurilor similare din aceeași localitate (verde = sub piață, roșu = peste);
- **posibil același imobil** publicat pe alt site sau de altă agenție (uneori mai ieftin);
- **alternative mai ieftine**, similare, **cu proprietarii primii**;
- de câte zile e anunțul în baza ta și dacă i s-a schimbat prețul.

Iconița extensiei deschide o **căutare rapidă** (tip, vânzare/închiriere, doar proprietari, localitate, preț, camere).

Datele vin din backend-ul tău AgencyIntel, deci backend-ul trebuie să ruleze.

## Instalare (o singură dată)

1. În `backend/.env` adaugă o cheie (orice text lung), de ex.:
   `EXTENSION_API_KEY=alba-2026-cheia-mea-secreta`
   și repornește backend-ul.
2. În Chrome: `chrome://extensions` → activează **Developer mode** (dreapta sus) → **Load unpacked** → alege folderul `extension`.
3. Click dreapta pe iconița extensiei → **Opțiuni** → pune adresa `http://127.0.0.1:8000` și aceeași cheie → **Salvează și testează**.

Apoi deschide orice anunț din Alba pe OLX / Storia / imobiliare.ro și uită-te în colțul din dreapta jos.
