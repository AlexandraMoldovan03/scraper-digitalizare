"""
probe_imobiliare.py — diagnostic HTML live Imobiliare.ro.

Pasul 1: Inspecteaza structura HTML reala.
Pasul 2: Salveaza HTML + raport diagnostic.
Pasul 3: Detecteaza carduri de anunt.
Pasul 4-5: Extrage URL real si external_id.
Pasul 6: Afiseaza max 3 rezultate reale.

Fara DB, fara import, fara Playwright.
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("DATABASE_URL", "sqlite:///./probe.db")
os.environ.setdefault("SECRET_KEY", "probe-secret")

import httpx
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://www.imobiliare.ro"
BASE_SEARCH = "https://www.imobiliare.ro/vanzare-apartamente/judet-alba"
TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

CLIENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    # Nu includem "br" — necesita pachetul brotli; gzip e suficient si mereu disponibil.
    "Accept-Encoding": "gzip, deflate",
}

# ── Termeni relevanti pentru detectie ────────────────────────────────────────

CLASS_TERMS = [
    "listing", "property", "result", "card", "offer", "anunt", "estate",
    "item", "apartament", "imobil", "proprietate", "announce", "product",
]

PRICE_PATTERNS = [
    re.compile(r"\b\d[\d\s.,]{1,10}(?:EUR|€|euro|lei|RON)\b", re.I),
    re.compile(r"(?:EUR|€|lei|RON)\s*\d[\d\s.,]{1,10}", re.I),
]

SURFACE_PATTERNS = [
    re.compile(r"\b\d+(?:[,.]\d+)?\s*m[²2p]", re.I),
    re.compile(r"\b\d+(?:[,.]\d+)?\s*mp\b", re.I),
]

ROOMS_PATTERNS = [
    re.compile(r"\b([1-9])\s*cam(?:ere|era|\.)\b", re.I),
    re.compile(r"\b([1-9])\s*room", re.I),
]

PROPERTY_TERMS = re.compile(
    r"\b(apartament|casa|vila|teren|spatiu|garsoniera|penthouse|duplex|birou)\b", re.I
)

SKIP_HREFS = re.compile(
    r"(javascript:|#|/cont/|/login|/register|/agentii|/agentie|/promotii"
    r"|/despre|/contact|/publicare|/stiri|/blog|mailto:|tel:)", re.I
)

DATA_ATTRS = [
    "data-id", "data-listing-id", "data-offer-id", "data-property-id",
    "data-testid", "data-cy", "data-url", "data-href", "data-anunt-id",
    "data-item-id", "data-pid", "data-oid",
]

SCRIPT_KEYWORDS = [
    "price", "listing", "property", "offer", "searchResults", "results",
    "itemList", "275791517", "listings", "anunturi", "oferte",
]


# ══════════════════════════════════════════════════════════════════════════════
# PASUL 1 — Diagnostic HTML
# ══════════════════════════════════════════════════════════════════════════════

def analyse_html(soup: BeautifulSoup, html: str) -> dict:
    diag: dict[str, Any] = {}

    # 1a. Numar taguri
    diag["tag_counts"] = {
        "article": len(soup.find_all("article")),
        "section": len(soup.find_all("section")),
        "li": len(soup.find_all("li")),
        "div": len(soup.find_all("div")),
        "a_href": len(soup.find_all("a", href=True)),
    }

    # 1b. Clase unice cu termeni relevanti
    relevant_classes: set[str] = set()
    for tag in soup.find_all(True):
        for cls in (tag.get("class") or []):
            cls_lower = cls.lower()
            if any(term in cls_lower for term in CLASS_TERMS):
                relevant_classes.add(cls)
    diag["relevant_classes"] = sorted(relevant_classes)

    # 1c. href-uri care par pagini de detaliu (segmente > 3, nu navigatie)
    detail_hrefs: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href_full = BASE_URL + href
        elif href.startswith("http"):
            href_full = href
        else:
            continue
        if "imobiliare.ro" not in href_full:
            continue
        if SKIP_HREFS.search(href_full):
            continue
        path = href_full.split("?")[0].split("#")[0]
        segments = [s for s in path.split("/") if s]
        if len(segments) < 4:
            continue
        if href_full not in detail_hrefs:
            detail_hrefs.append(href_full)
        if len(detail_hrefs) >= 30:
            break
    diag["detail_hrefs_sample"] = detail_hrefs[:30]

    # 1d. href-uri cu pattern-uri specifice
    specific_hrefs: dict[str, list[str]] = {
        "vanzare_apartamente": [],
        "vanzare_case": [],
        "vanzare_terenuri": [],
        "item_dash": [],
        "numeric_id_long": [],
        "alphanumeric_long": [],
    }
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = BASE_URL + href
        if "imobiliare.ro" not in href:
            continue
        if "vanzare-apartamente" in href and len(specific_hrefs["vanzare_apartamente"]) < 10:
            specific_hrefs["vanzare_apartamente"].append(href)
        if "vanzare-case" in href and len(specific_hrefs["vanzare_case"]) < 5:
            specific_hrefs["vanzare_case"].append(href)
        if "vanzare-terenuri" in href and len(specific_hrefs["vanzare_terenuri"]) < 5:
            specific_hrefs["vanzare_terenuri"].append(href)
        if re.search(r"item-\d+", href) and len(specific_hrefs["item_dash"]) < 10:
            specific_hrefs["item_dash"].append(href)
        if re.search(r"/\d{7,}", href) and len(specific_hrefs["numeric_id_long"]) < 10:
            specific_hrefs["numeric_id_long"].append(href)
        if re.search(r"/[A-Z0-9]{8,}", href) and len(specific_hrefs["alphanumeric_long"]) < 10:
            specific_hrefs["alphanumeric_long"].append(href)
    diag["specific_hrefs"] = specific_hrefs

    # 1e. Data attributes
    found_data_attrs: dict[str, list[str]] = {}
    for attr in DATA_ATTRS:
        vals = []
        for tag in soup.find_all(attrs={attr: True}):
            val = tag.get(attr, "")
            if val and val not in vals:
                vals.append(val)
            if len(vals) >= 5:
                break
        if vals:
            found_data_attrs[attr] = vals
    diag["data_attributes"] = found_data_attrs

    # 1f. Scripturi inline relevante
    script_info: list[dict] = []
    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        text = (script.string or "").strip()
        if not text:
            continue
        text_lower = text.lower()
        if not any(kw.lower() in text_lower for kw in SCRIPT_KEYWORDS):
            continue
        info: dict[str, Any] = {"length": len(text), "snippet": text[:300]}
        # Cauta JSON
        try:
            # Incearca sa gaseasca JSON in script (window.__DATA__ = {...} pattern)
            m = re.search(r"(?:=\s*|:\s*)(\{[\s\S]{20,})", text)
            if m:
                candidate = m.group(1)
                # Ia doar pana la primul ; de la un nivel de acolada 0
                depth = 0
                end = 0
                for i, ch in enumerate(candidate):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > 0:
                    parsed = json.loads(candidate[:end])
                    info["json_keys"] = list(parsed.keys())[:20]
        except Exception:
            pass
        script_info.append(info)
    diag["relevant_scripts"] = script_info[:10]

    return diag


# ══════════════════════════════════════════════════════════════════════════════
# PASUL 3 — Detectare carduri
# ══════════════════════════════════════════════════════════════════════════════

def score_element(el: Tag) -> int:
    """Scor candidat listing: +2 link, +2 pret, +1 suprafata, +1 camere, +1 imagine, +1 localitate, +1 termen."""
    score = 0
    text = el.get_text(" ", strip=True)
    text_lower = text.lower()

    # Link intern
    links = [a["href"] for a in el.find_all("a", href=True) if a["href"].startswith("/") or "imobiliare.ro" in a.get("href", "")]
    if links:
        score += 2

    # Pret
    if any(p.search(text) for p in PRICE_PATTERNS):
        score += 2

    # Suprafata
    if any(p.search(text) for p in SURFACE_PATTERNS):
        score += 1

    # Camere
    if any(p.search(text) for p in ROOMS_PATTERNS):
        score += 1

    # Imagine
    if el.find("img"):
        score += 1

    # Localitate — termeni simpli (orasele din Alba)
    if re.search(r"\b(alba\s*iulia|blaj|sebes|aiud|campeni|zlatna|cugir|ocna\s*mures)\b", text_lower):
        score += 1

    # Termen proprietate
    if PROPERTY_TERMS.search(text):
        score += 1

    return score


def find_listing_card_candidates(soup: BeautifulSoup) -> list[Tag]:
    """Returneaza elementele HTML care par carduri de listing (scor >= 4)."""
    candidates: list[tuple[int, Tag]] = []

    # Incercam articole, li, div cu clase relevante
    for tag_name in ("article", "li", "div", "section"):
        for el in soup.find_all(tag_name):
            # Sarim elementele mici
            text = el.get_text(" ", strip=True)
            if len(text) < 30 or len(text) > 5000:
                continue
            s = score_element(el)
            if s >= 4:
                candidates.append((s, el))

    # Deduplicare: eliminam parintii daca copilul e deja candidat
    # Pastram elementele cu scor maxim si cei mai specifici (mai adanci in DOM)
    seen_texts: set[str] = set()
    unique: list[tuple[int, Tag]] = []
    for score, el in sorted(candidates, key=lambda x: -x[0]):
        snippet = el.get_text(" ", strip=True)[:100]
        if snippet not in seen_texts:
            seen_texts.add(snippet)
            unique.append((score, el))
        if len(unique) >= 30:
            break

    return [el for _, el in unique]


# ══════════════════════════════════════════════════════════════════════════════
# PASUL 4 — URL real din card
# ══════════════════════════════════════════════════════════════════════════════

def extract_listing_url_from_card(card: Tag, base_url: str = BASE_URL) -> str | None:
    """Extrage URL-ul de detaliu din cardul unui listing."""
    hrefs: list[str] = []
    for a in card.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = base_url + href
        if "imobiliare.ro" not in href:
            continue
        if SKIP_HREFS.search(href):
            continue
        # Preferam linkuri cu segmente lungi
        path = href.split("?")[0].split("#")[0]
        segs = [s for s in path.split("/") if s]
        if len(segs) >= 3:
            hrefs.append(href)

    if not hrefs:
        return None

    # Preferam linkul cu cel mai lung path (mai specific)
    hrefs.sort(key=lambda h: len(h.split("?")[0]), reverse=True)
    url = hrefs[0].split("?")[0].split("#")[0].rstrip("/")
    return url


# ══════════════════════════════════════════════════════════════════════════════
# PASUL 5 — External ID
# ══════════════════════════════════════════════════════════════════════════════

def extract_external_id(url: str, card: Tag | None = None) -> str | None:
    """Extrage ID-ul extern din URL sau data attributes ale cardului."""
    clean = url.split("?")[0].split("#")[0].rstrip("/")

    # Pattern item-{digits}
    m = re.search(r"item-(\d+)", clean)
    if m:
        return m.group(1)

    # Segment numeric lung (>= 6 cifre) la finalul path-ului
    m = re.search(r"/(\d{6,})(?:[^/]*)$", clean)
    if m:
        return m.group(1)

    # Data attributes pe card
    if card is not None:
        for attr in DATA_ATTRS:
            val = card.get(attr, "")
            if not val:
                for el in card.find_all(attrs={attr: True}):
                    val = el.get(attr, "")
                    if val:
                        break
            if val and (str(val).isdigit() or re.match(r"^[A-Z0-9]{4,}$", str(val))):
                return str(val)

    # Alfanumeric la finalul path-ului
    last_seg = clean.split("/")[-1]
    m = re.search(r"([A-Z0-9]{6,})$", last_seg)
    if m:
        return m.group(1)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# PROBE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run_probe() -> None:
    print("=== ImobiliareRo HTML Diagnostic Probe ===")
    print(f"Target: {BASE_SEARCH}\n")

    with httpx.Client(headers=CLIENT_HEADERS, follow_redirects=True, timeout=30) as client:
        try:
            resp = client.get(BASE_SEARCH)
        except Exception as e:
            print(f"Conexiune eșuata: {e}")
            return

        print(f"Status: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type', '?')}")
        print(f"Lungime raspuns: {len(resp.text):,} chars")

        if resp.status_code != 200:
            return

        html = resp.text
        # Sanity check: daca primele 200 caractere nu contin '<', raspunsul e
        # probabil comprimat binar (brotli/gzip nedecriptat). Semnalizam si iesim.
        if "<" not in html[:200]:
            print("\n⚠ ATENTIE: Raspunsul nu pare HTML (lipseste '<' in primele 200 chars).")
            print("  Posibila cauza: Accept-Encoding nesuportat (ex. brotli fara pachetul brotli).")
            print(f"  Content-Encoding: {resp.headers.get('content-encoding', 'none')}")
            print(f"  Primii 80 bytes (repr): {repr(resp.content[:80])}")
            return

        soup = BeautifulSoup(html, "html.parser")

        # ── PASUL 2: Salveaza HTML si diagnostic ──────────────────────────
        html_path = TMP_DIR / "imobiliare_result_page.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"\nHTML salvat: {html_path}")

        # ── PASUL 1: Diagnostic ───────────────────────────────────────────
        print("\n=== PASUL 1: Diagnostic HTML ===")
        diag = analyse_html(soup, html)

        print("\n[Numar taguri]")
        for k, v in diag["tag_counts"].items():
            print(f"  {k}: {v}")

        print(f"\n[Clase relevante ({len(diag['relevant_classes'])} gasite)]")
        for cls in diag["relevant_classes"][:40]:
            print(f"  {cls}")

        print(f"\n[href-uri detail (primele 20)]")
        for h in diag["detail_hrefs_sample"][:20]:
            print(f"  {h}")

        print(f"\n[href-uri cu pattern specific]")
        for pattern, hrefs in diag["specific_hrefs"].items():
            if hrefs:
                print(f"  {pattern}:")
                for h in hrefs[:5]:
                    print(f"    {h}")

        print(f"\n[Data attributes gasite]")
        if diag["data_attributes"]:
            for attr, vals in diag["data_attributes"].items():
                print(f"  {attr}: {vals[:3]}")
        else:
            print("  Niciun data attribute relevant gasit")

        print(f"\n[Scripturi inline relevante ({len(diag['relevant_scripts'])} gasite)]")
        for i, sc in enumerate(diag["relevant_scripts"][:5]):
            print(f"\n  Script {i+1}: {sc['length']:,} chars")
            print(f"  Snippet: {sc['snippet'][:200]}")
            if "json_keys" in sc:
                print(f"  JSON keys: {sc['json_keys']}")

        # Salveaza diagnostic
        diag_path = TMP_DIR / "imobiliare_html_diagnostic.json"
        diag_path.write_text(
            json.dumps(diag, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nDiagnostic salvat: {diag_path}")

        # ── PASUL 3: Detectare carduri ────────────────────────────────────
        print("\n=== PASUL 3: Candidati carduri ===")
        candidates = find_listing_card_candidates(soup)
        print(f"Candidati cu scor >= 4: {len(candidates)}")

        results: list[dict] = []

        for i, card in enumerate(candidates[:10]):
            text_snippet = card.get_text(" ", strip=True)[:200]
            score = score_element(card)
            classes = " ".join(card.get("class") or [])
            data_attrs_found = {a: card.get(a) for a in DATA_ATTRS if card.get(a)}

            # Pret detectat
            price_match = None
            for p in PRICE_PATTERNS:
                m = p.search(card.get_text(" ", strip=True))
                if m:
                    price_match = m.group(0)
                    break

            # Suprafata detectata
            surf_match = None
            for p in SURFACE_PATTERNS:
                m = p.search(card.get_text(" ", strip=True))
                if m:
                    surf_match = m.group(0)
                    break

            # Camere detectate
            rooms_match = None
            for p in ROOMS_PATTERNS:
                m = p.search(card.get_text(" ", strip=True))
                if m:
                    rooms_match = m.group(0)
                    break

            # URL si external_id
            url = extract_listing_url_from_card(card)
            ext_id = extract_external_id(url, card) if url else None

            # Imagine
            img = card.find("img")
            img_src = None
            if img:
                img_src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

            print(f"\n  [Card {i+1}] scor={score} tag={card.name} cls='{classes[:60]}'")
            print(f"    data_attrs: {data_attrs_found}")
            print(f"    URL:        {url}")
            print(f"    ext_id:     {ext_id}")
            print(f"    pret:       {price_match}")
            print(f"    suprafata:  {surf_match}")
            print(f"    camere:     {rooms_match}")
            print(f"    img:        {img_src}")
            print(f"    text:       {text_snippet[:150]}")

            if url and ext_id:
                results.append({
                    "url": url,
                    "external_id": ext_id,
                    "price_raw": price_match,
                    "surface_raw": surf_match,
                    "rooms_raw": rooms_match,
                    "image_url": img_src,
                    "tag": card.name,
                    "classes": classes[:100],
                    "score": score,
                })

        # ── PASUL 6: Rezultate finale ─────────────────────────────────────
        print(f"\n=== PASUL 6: Rezultate reale (max 3) ===")
        if not results:
            print("⚠ ZERO URL-uri reale extrase din carduri.")
            print("  → Listing-urile sunt probabil generate client-side (JS).")
            print("  → Urmator pas: Playwright standard sau cautare in scripturi inline.")
        else:
            for j, r in enumerate(results[:3]):
                print(f"\n  [{j+1}]")
                for k, v in r.items():
                    print(f"    {k}: {v}")

        print(f"\n=== SUMAR ===")
        print(f"Candidati carduri: {len(candidates)}")
        print(f"URL-uri valide extrase: {len([r for r in results if r.get('url')])}")
        print(f"Probe status: {'✓ URL-uri gasite' if results else '⚠ Nimic extras — pagina probabil CSR'}")


if __name__ == "__main__":
    run_probe()
