"""
probe_romimo.py — diagnostic live Romimo.ro, fără scriere în DB.

ETAPA 1 + 2: validare structură reală înainte de implementarea adaptorului.

Testează:
  - pagina de rezultate apartamente + case/vile + terenuri în județul Alba
  - max 1 pagina de rezultate per categorie
  - max 3 pagini de detaliu (din prima categorie disponibilă)

Afișează:
  - status HTTP, URL final, Content-Type, dimensiune
  - titlul paginii, nr. carduri, nr. linkuri listing
  - JSON-LD types
  - scripturi JSON embedded
  - selector card, external_id, preț, localitate, seller_type
  - paginare
  - challenge/403/429 detection

NU afișează: cookies, token-uri, HTML complet, date personale.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).parent))

import httpx
from bs4 import BeautifulSoup, Tag

# ── Configurare ───────────────────────────────────────────────────────────────

BASE_URL = "https://www.romimo.ro"

# Candidate URL-uri de testat în ordine (prima care returnează 200 cu carduri câștigă)
SEARCH_URL_CANDIDATES = {
    "apartamente_vanzare": [
        # Confirmat live: ✓
        "https://www.romimo.ro/apartamente/vanzare/alba/",
    ],
    "case_vile_vanzare": [
        "https://www.romimo.ro/case/vanzare/alba/",
        "https://www.romimo.ro/case-vile/vanzare/alba/",
        "https://www.romimo.ro/vile/vanzare/alba/",
        "https://www.romimo.ro/case-si-vile/vanzare/alba/",
        "https://www.romimo.ro/imobiliare/case/de-vanzare/alba/",
    ],
    "terenuri": [
        # Confirmat live: ✓
        "https://www.romimo.ro/terenuri/vanzare/alba/",
    ],
    "spatii_comerciale": [
        "https://www.romimo.ro/spatii-comerciale/vanzare/alba/",
        "https://www.romimo.ro/birouri/vanzare/alba/",
        "https://www.romimo.ro/spatii/vanzare/alba/",
    ],
}

TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

REQUEST_DELAY = 1.5  # secunde între requesturi

CLIENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
}

# ── HTTP client ───────────────────────────────────────────────────────────────

def make_client() -> httpx.Client:
    return httpx.Client(
        headers=CLIENT_HEADERS,
        follow_redirects=True,
        timeout=30,
    )


def fetch(client: httpx.Client, url: str, label: str = "") -> httpx.Response | None:
    """Fetch cu detectare 403/429. Returnează None dacă blocat."""
    prefix = f"  [{label}] " if label else "  "
    try:
        resp = client.get(url)
    except Exception as exc:
        print(f"{prefix}✗ Eroare: {exc}")
        return None

    print(f"{prefix}Status:       {resp.status_code}")
    print(f"{prefix}URL final:    {resp.url}")
    print(f"{prefix}Content-Type: {resp.headers.get('content-type', '?')}")
    print(f"{prefix}Dimensiune:   {len(resp.text):,} chars")

    if resp.status_code == 403:
        print(f"{prefix}⛔ 403 Forbidden — WAF/IP block.")
        return None
    if resp.status_code == 429:
        retry = resp.headers.get("Retry-After", "?")
        print(f"{prefix}⛔ 429 Too Many Requests — Retry-After: {retry}")
        return None
    if resp.status_code not in (200, 301, 302):
        print(f"{prefix}⚠ Status neașteptat: {resp.status_code}")
        return None

    # Sanity check HTML
    if "<" not in resp.text[:300]:
        print(f"{prefix}⚠ Răspuns nu pare HTML valid.")
        return None

    return resp


# ── Challenge detection ───────────────────────────────────────────────────────

def detect_challenge(soup: BeautifulSoup, html: str) -> str | None:
    """
    Detectare reală de challenge/block. Evită false positive-uri:
    - paginile mari (>20KB) cu 200 care conțin 'captcha' în JS sunt normale
      (Google reCAPTCHA pentru formulare de contact, nu un challenge activ)
    - tratăm ca blocked doar paginile scurte sau cu redirect la URL de challenge
    """
    title = (soup.title.string or "").strip() if soup.title else ""

    # Titlu explicit de challenge (pagini scurte)
    if re.search(r"^(challenge|captcha|access denied|403|verificare robot)", title, re.I):
        return f"challenge_title: {title}"

    # Cloudflare WAF
    if "cf-challenge" in html or "cf_clearance" in html:
        return "cloudflare_challenge"

    # Cloudflare block page (tipic < 5KB)
    if len(html) < 8000 and "Ray ID" in html and "Cloudflare" in html:
        return "cloudflare_block"

    # CAPTCHA real = pagina scurta (<15KB) cu formular captcha vizibil
    # Paginile normale de 100KB+ cu reCAPTCHA în JS pentru formulare = OK
    if len(html) < 15_000:
        if re.search(r"captcha", html, re.I) and re.search(r"solve|complete|verify you", html, re.I):
            return "captcha"

    # 403/429 nu ajung aici (sunt prinse în fetch())
    return None


# ── JSON-LD ───────────────────────────────────────────────────────────────────

def extract_jsonld(soup: BeautifulSoup) -> list[dict]:
    nodes: list[dict] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = (script.string or "").strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  ⚠ JSON-LD invalid: {exc}")
            continue
        if isinstance(data, list):
            nodes.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            if "@graph" in data:
                nodes.extend(n for n in data["@graph"] if isinstance(n, dict))
            else:
                nodes.append(data)
    return nodes


# ── Scripturi JSON embedded ───────────────────────────────────────────────────

EMBEDDED_SCRIPT_IDS = ["__NEXT_DATA__", "__redux_state__", "state", "app-state"]
EMBEDDED_PATTERNS = [
    re.compile(r'window\.__(?:INITIAL|APP|STORE|STATE)__\s*=\s*(\{.{20,})', re.I),
    re.compile(r'"anunturi":\s*\[', re.I),
    re.compile(r'"listings":\s*\[', re.I),
    re.compile(r'"properties":\s*\[', re.I),
    re.compile(r'"items":\s*\[', re.I),
]

def extract_embedded_json(soup: BeautifulSoup) -> list[dict]:
    results: list[dict] = []
    for sid in EMBEDDED_SCRIPT_IDS:
        tag = soup.find("script", {"id": sid})
        if tag and tag.string:
            raw = tag.string.strip()
            try:
                data = json.loads(raw)
                results.append({"source": f"id={sid}", "data": data, "length": len(raw)})
            except Exception:
                results.append({"source": f"id={sid}_raw", "snippet": raw[:200], "length": len(raw)})

    for script in soup.find_all("script"):
        if script.get("src"):
            continue
        raw = script.string or ""
        for pat in EMBEDDED_PATTERNS:
            if pat.search(raw):
                results.append({"source": f"pattern:{pat.pattern[:35]}", "snippet": raw[:200], "length": len(raw)})
                break

    return results


# ── External ID ───────────────────────────────────────────────────────────────

EXT_ID_PATTERNS = [
    re.compile(r"[_-](\d{5,})(?:[_.-]|$|\.html?)"),      # -123456 sau _123456
    re.compile(r"/(\d{5,})(?:/|\.html?|$)"),               # /123456/
    re.compile(r"(?:id|anunt|listing)[=_-](\d+)", re.I),  # id=123456
]

def extract_external_id(url: str, el: Tag | None = None) -> str | None:
    """
    Extrage ID extern stabil din URL.
    Prioritate: segment numeric lung > data-id > slug final.
    """
    for pat in EXT_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)

    # data attributes din element
    if el is not None:
        for attr in ("data-id", "data-listing-id", "data-anunt-id", "id"):
            val = el.get(attr)
            if val and re.match(r"^\d{4,}$", str(val)):
                return str(val)

    # fallback: ultimul segment din path fără extensie
    path = urlparse(url).path.rstrip("/")
    seg = path.split("/")[-1].replace(".html", "").replace(".php", "")
    if seg and re.search(r"\d{4,}", seg):
        return seg

    return None


def canonicalize_url(url: str) -> str:
    """Elimina query string și fragment. Pastreaza path curat."""
    parsed = urlparse(url)
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return clean.rstrip("/")


# ── Carduri listing ───────────────────────────────────────────────────────────

# Selectori specifici Romimo (în ordinea probabilității — confirmat live)
CARD_SELECTORS = [
    ".article-item",           # ✓ confirmat live: 24 carduri/pagina
    ".anunt-list-item",
    ".listing-item",
    ".property-item",
    ".result-item",
    ".card-anunt",
    ".imobil-item",
    "article.listing",
    "div.anunt",
]

# Clasa B2B (companie) — confirmat live
B2B_CLASS = "article-item-b2b-phone"

PRICE_PATTERNS = [
    re.compile(r"([\d\s.,]+)\s*(?:EUR|€)", re.I),
    re.compile(r"([\d\s.,]+)\s*(?:lei|RON)", re.I),
]

MONTHS_RO = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8, "septembrie": 9,
    "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}

DIACRITICS_MAP = {
    "Sebes": "Sebeș", "Mures": "Mureș", "Campeni": "Câmpeni",
    "Teius": "Teiuș", "Aries": "Arieș", "Ocna Mures": "Ocna Mureș",
    "Baia de Aries": "Baia de Arieș", "Zlatna": "Zlatna",
    "Aiud": "Aiud", "Blaj": "Blaj", "Cugir": "Cugir",
}


def find_listing_cards(soup: BeautifulSoup, html: str) -> tuple[list[Tag], str]:
    """
    Returnează (carduri, selector_folosit).
    Încearcă selectori specifici, apoi fallback la detectare prin linkuri.
    """
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if len(cards) >= 2:
            return cards, sel

    # Fallback: găsim elemente care conțin linkuri + preț
    candidates: list[Tag] = []
    seen: set[int] = set()
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        # Linkul trebuie să pară un detaliu de anunț (conține număr în path)
        if not re.search(r"/\d{4,}", href) and not re.search(r"-\d{5,}", href):
            continue
        # Cauta elementul parinte cu text de pret
        parent = a.parent
        for _ in range(4):
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            if re.search(r"\d[\d.,]+\s*(?:EUR|€|lei|RON)", text, re.I):
                pid = id(parent)
                if pid not in seen:
                    seen.add(pid)
                    candidates.append(parent)
                break
            parent = parent.parent

    return candidates, "fallback_price_link"


def extract_card_url(card: Tag) -> str | None:
    """Extrage URL-ul listing-ului dintr-un card."""
    # Cauta primul <a> cu href relevant
    for a in card.find_all("a", href=True):
        href = str(a["href"])
        if re.search(r"/\d{4,}|anunt|\d{5,}-", href):
            return href if href.startswith("http") else urljoin(BASE_URL, href)
    # Fallback: primul <a>
    a = card.find("a", href=True)
    if a:
        href = str(a["href"])
        return href if href.startswith("http") else urljoin(BASE_URL, href)
    return None


# ── Parsare preț ─────────────────────────────────────────────────────────────

def parse_price(text: str) -> tuple[float | None, str | None]:
    """Returnează (valoare, moneda)."""
    for pat, cur in [(PRICE_PATTERNS[0], "EUR"), (PRICE_PATTERNS[1], "RON")]:
        m = pat.search(text)
        if m:
            val_str = re.sub(r"[\s.]", "", m.group(1)).replace(",", ".")
            try:
                return float(val_str), cur
            except ValueError:
                pass
    return None, None


# ── Parsare data ──────────────────────────────────────────────────────────────

def parse_date_ro(text: str) -> datetime | None:
    """Parsare flexibilă pentru formate românești și ISO."""
    text = text.strip()

    # ISO
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass

    now = datetime.now()
    tl = text.lower()

    # "acum X ore"
    m = re.search(r"acum\s+(\d+)\s+or[ae]", tl)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    # "acum X zile" sau "X zile în urmă"
    m = re.search(r"acum\s+(\d+)\s+zile?|(\d+)\s+zile?\s+[îi]n\s+urm[aă]", tl)
    if m:
        days = int(m.group(1) or m.group(2))
        return now - timedelta(days=days)

    # "azi" / "astăzi"
    if re.search(r"\bazi\b|\bastăzi\b|\bastazi\b", tl):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    # "ieri"
    if re.search(r"\bieri\b", tl):
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # DD.MM.YYYY
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # DD luna YYYY
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", tl)
    if m:
        month = MONTHS_RO.get(m.group(2))
        if month:
            try:
                return datetime(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass

    return None


# ── Seller type ───────────────────────────────────────────────────────────────

def detect_seller_type_from_card(card: Tag) -> tuple[str | None, str | None]:
    """
    Detectare seller_type din cardul de pe pagina de rezultate.
    Romimo: clasa 'article-item-b2b-phone' → Companie/B2B.
    Fără această clasă → Persoană fizică.
    Returnează (seller_type, seller_type_source).
    """
    classes = card.get("class") or []
    if B2B_CLASS in classes:
        return "agency", "css_class_b2b"
    return "private", "css_class_absence"


def detect_seller_type(soup: BeautifulSoup, text: str) -> tuple[str | None, str | None, str | None]:
    """
    Detectare seller_type din pagina de detaliu.
    Returnează (seller_type, seller_name, seller_type_source).
    """
    # Badge explicit în detaliu
    badges = [
        (r"\bPersoan[aă]\b|\bPrivat\b", "private"),
        (r"\bCompanie\b|\bFirm[aă]\b|\bAgen[tț]ie\b", "agency"),
    ]
    for pattern, stype in badges:
        el = soup.find(string=re.compile(pattern, re.I))
        if el:
            return stype, None, "explicit_label"

    # Fallback text
    tl = text.lower()
    if re.search(r"\bpersoan[aă]\b|\bprivat\b", tl):
        return "private", None, "text_inference"
    if re.search(r"\bcompanie\b|\bagenție\b|\bagentie\b|\bfirm[aă]\b", tl):
        return "agency", None, "text_inference"

    return "unknown", None, None


# ── Paginare ──────────────────────────────────────────────────────────────────

def find_next_page_url(soup: BeautifulSoup, current_url: str) -> str | None:
    """Detectează URL-ul paginii următoare."""
    # rel=next
    el = soup.find("link", {"rel": "next"})
    if el and el.get("href"):
        return el["href"]

    # <a> cu text "Urmatoarea" / "Next" / "›" / "»" sau aria-label
    nav_patterns = re.compile(r"^(urmatoarea|next|înainte|[›»>]|\d+\s*›)$", re.I)
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        aria = a.get("aria-label", "")
        if nav_patterns.match(text) or re.search(r"urm[aă]toarea|next page", aria, re.I):
            href = str(a["href"])
            return href if href.startswith("http") else urljoin(BASE_URL, href)

    # Link cu class de paginare care conține "next" / "urm"
    for a in soup.find_all("a", href=True):
        cls = " ".join(a.get("class", []))
        if re.search(r"next|urm[aă]t", cls, re.I):
            href = str(a["href"])
            return href if href.startswith("http") else urljoin(BASE_URL, href)

    # Pattern URL: ?page=N+1 sau /pagina-N+1/
    m_page = re.search(r"[?&]page=(\d+)", current_url)
    if not m_page:
        m_page = re.search(r"/pagina[_-]?(\d+)/", current_url)

    # Cauta linkuri care cresc cu 1
    if m_page:
        current_page = int(m_page.group(1))
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            m = re.search(r"[?&]page=(\d+)|/pagina[_-]?(\d+)/", href)
            if m:
                pg = int(m.group(1) or m.group(2))
                if pg == current_page + 1:
                    return href if href.startswith("http") else urljoin(BASE_URL, href)

    return None


# ── Parsare pagina detaliu ────────────────────────────────────────────────────

def parse_detail_page(html: str, url: str) -> dict:
    """Extrage datele cheie dintr-o pagina de detaliu Romimo."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "url": url,
        "external_id": extract_external_id(url),
        "canonical_url": canonicalize_url(url),
    }

    # Titlu
    h1 = soup.find("h1")
    result["title"] = h1.get_text(strip=True) if h1 else None

    # Description
    desc_selectors = [
        "[class*='description']", "[class*='descriere']",
        "[itemprop='description']", ".desc", "#descriere",
    ]
    for sel in desc_selectors:
        el = soup.select_one(sel)
        if el:
            result["description_snippet"] = el.get_text(" ", strip=True)[:300]
            break

    # JSON-LD
    jsonld_nodes = extract_jsonld(soup)
    result["jsonld_types"] = [n.get("@type", "?") for n in jsonld_nodes]

    # Date JSON-LD (product, realestate, etc.)
    for node in jsonld_nodes:
        t = node.get("@type", "")
        if t in ("Product", "RealEstateListing", "House", "Apartment", "Offer", "ItemPage"):
            result["jsonld_main"] = {
                "type": t,
                "name": node.get("name"),
                "price": (node.get("offers") or {}).get("price") if isinstance(node.get("offers"), dict) else None,
                "currency": (node.get("offers") or {}).get("priceCurrency") if isinstance(node.get("offers"), dict) else None,
                "published": node.get("datePublished"),
                "modified": node.get("dateModified"),
            }
            break

    # Scripturi embedded
    embedded = extract_embedded_json(soup)
    result["embedded_scripts_count"] = len(embedded)
    if embedded:
        for emb in embedded[:2]:
            if "data" in emb and isinstance(emb["data"], dict):
                result.setdefault("embedded_keys", []).append({
                    "source": emb["source"],
                    "keys": list(emb["data"].keys())[:10],
                })

    # Preț
    price_selectors = [
        "[class*='price']", "[class*='pret']", "[itemprop='price']",
        ".pret", "#pret", "strong[class*='price']",
    ]
    for sel in price_selectors:
        el = soup.select_one(sel)
        if el:
            pt = el.get_text(strip=True)
            val, cur = parse_price(pt)
            if val:
                result["price_raw"] = pt
                result["price_eur"] = val if cur == "EUR" else None
                result["original_price"] = val
                result["original_currency"] = cur
                break

    # Seller type
    body_text = soup.get_text(" ", strip=True)
    stype, sname, ssrc = detect_seller_type(soup, body_text)
    result["seller_type"] = stype
    result["seller_name"] = sname
    result["seller_type_source"] = ssrc

    # Seller name explicit
    for sel in ["[class*='contact-name']", "[class*='agent-name']", "[class*='seller']", ".autor", ".vanzator"]:
        el = soup.select_one(sel)
        if el:
            result["seller_name"] = el.get_text(strip=True)
            break

    # Data publicare/reactualizare
    date_selectors = [
        "[class*='date']", "[class*='data']", "[class*='time']",
        "time", "[itemprop='datePublished']", "[itemprop='dateModified']",
        ".data-publicare", ".publicat",
    ]
    for el in soup.select(", ".join(date_selectors)):
        text = el.get_text(strip=True) or el.get("datetime", "")
        if not text:
            continue
        is_update = bool(re.search(r"reactualiz|modificat|updated?", text, re.I))
        parsed = parse_date_ro(text)
        if is_update:
            result.setdefault("updated_at_source_raw", text)
            result.setdefault("updated_at_source", parsed.isoformat() if parsed else None)
        else:
            result.setdefault("published_at_raw", text)
            result.setdefault("published_at", parsed.isoformat() if parsed else None)

    # Localitate din breadcrumb
    for node in jsonld_nodes:
        if node.get("@type") == "BreadcrumbList":
            crumbs = [item.get("name", "") for item in (node.get("itemListElement") or []) if isinstance(item, dict)]
            result["breadcrumbs"] = crumbs
            if len(crumbs) >= 2:
                result["locality_from_breadcrumb"] = crumbs[-2] if crumbs[-1].lower() in ("vanzare", "de vânzare", "cumpara") else crumbs[-1]
            break

    # Localitate din text / meta
    loc_selectors = [
        "[class*='location']", "[class*='localitate']", "[class*='oras']",
        "[class*='adresa']", "[itemprop='addressLocality']",
    ]
    for sel in loc_selectors:
        el = soup.select_one(sel)
        if el:
            result["location_raw"] = el.get_text(strip=True)
            break

    # Caracteristici (camere, suprafata, etaj)
    details_text = body_text
    m = re.search(r"(\d+)\s*cam(?:ere|era|\.)", details_text, re.I)
    if m:
        result["rooms"] = int(m.group(1))

    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m[²2p]", details_text, re.I)
    if m:
        result["surface_m2"] = float(m.group(1).replace(",", "."))

    m = re.search(r"etaj\s+(\d+|parter)", details_text, re.I)
    if m:
        val = m.group(1)
        result["floor"] = 0 if val.lower() == "parter" else int(val)

    # Imagini
    imgs = []
    for img in soup.find_all("img", src=True):
        src = str(img["src"])
        if re.search(r"\.(jpg|jpeg|webp|png)", src, re.I) and len(src) > 20:
            if not re.search(r"logo|icon|avatar|placeholder", src, re.I):
                imgs.append(src)
    result["image_count"] = len(imgs)
    result["main_image_url"] = imgs[0] if imgs else None

    return result


# ── Analiza pagina de rezultate ───────────────────────────────────────────────

def analyze_result_page(html: str, url: str, category: str) -> dict:
    """Extrage tot ce ne trebuie din pagina de rezultate."""
    soup = BeautifulSoup(html, "html.parser")

    result: dict[str, Any] = {
        "category": category,
        "url": url,
        "challenge": detect_challenge(soup, html),
    }

    if result["challenge"]:
        return result

    # Titlu
    result["page_title"] = soup.title.string.strip() if soup.title else "—"

    # Număr total linkuri
    result["total_links"] = len(soup.find_all("a", href=True))

    # JSON-LD
    jsonld_nodes = extract_jsonld(soup)
    result["jsonld_count"] = len(jsonld_nodes)
    result["jsonld_types"] = list({n.get("@type", "?") for n in jsonld_nodes})

    # Scripturi embedded
    embedded = extract_embedded_json(soup)
    result["embedded_scripts"] = [
        {"source": e.get("source"), "length": e.get("length", 0),
         "keys": list(e["data"].keys())[:8] if "data" in e and isinstance(e["data"], dict) else []}
        for e in embedded[:5]
    ]

    # Carduri
    cards, selector = find_listing_cards(soup, html)
    result["card_selector"] = selector
    result["card_count"] = len(cards)

    # URL-uri listing
    listing_urls: list[str] = []
    seen: set[str] = set()

    for card in cards:
        url_card = extract_card_url(card)
        if url_card:
            canon = canonicalize_url(url_card)
            if canon not in seen:
                seen.add(canon)
                listing_urls.append(url_card)

    # Fallback: cauta linkuri cu pattern numeric in href
    if not listing_urls:
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if re.search(r"/\d{5,}|anunt.*\d{4,}|\d{5,}.*\.html", href, re.I):
                full = href if href.startswith("http") else urljoin(BASE_URL, href)
                canon = canonicalize_url(full)
                if canon not in seen:
                    seen.add(canon)
                    listing_urls.append(full)

    result["listing_urls"] = listing_urls
    result["listing_count"] = len(listing_urls)

    # Sample external IDs
    result["sample_external_ids"] = [
        {"url": u, "external_id": extract_external_id(u)}
        for u in listing_urls[:5]
    ]

    # Paginare
    result["next_page_url"] = find_next_page_url(soup, url)

    # Anunțuri totale (dacă e afișat pe pagina)
    total_text = soup.get_text(" ", strip=True)
    m = re.search(r"(\d+)\s+anun[țt]uri?", total_text, re.I)
    result["total_announced"] = int(m.group(1)) if m else None

    # Promovate vs organice
    # Romimo: textul "Promovat" apare în carduri promovate
    promoted_count = 0
    b2b_count = 0
    private_count = 0
    for card in cards:
        text_card = card.get_text(" ", strip=True)
        if re.search(r"\bPromovat\b", text_card):
            promoted_count += 1
        card_classes = card.get("class") or []
        if B2B_CLASS in card_classes:
            b2b_count += 1
        else:
            private_count += 1
    result["promoted_count"] = promoted_count
    result["b2b_cards"] = b2b_count
    result["private_cards"] = private_count

    # Clase CSS cheie (primele 30 unice)
    all_classes = set()
    for el in soup.find_all(class_=True):
        for cls in el.get("class", []):
            if any(term in cls.lower() for term in ["anunt", "listing", "card", "property", "result", "item", "imobil"]):
                all_classes.add(cls)
    result["relevant_classes"] = sorted(all_classes)[:30]

    return result


# ── Main probe ────────────────────────────────────────────────────────────────

def run_probe() -> None:
    print("=" * 65)
    print("=== Romimo.ro — Diagnostic Probe Live (fără DB) ===")
    print("=" * 65)

    found_category_url: str | None = None
    found_listing_urls: list[str] = []
    found_category: str | None = None

    with make_client() as client:
        # ── A. Pagini de rezultate ────────────────────────────────────────
        for category, candidates in SEARCH_URL_CANDIDATES.items():
            print(f"\n{'─'*65}")
            print(f"[A] CATEGORIE: {category}")
            print(f"{'─'*65}")

            success_url: str | None = None
            success_html: str | None = None

            for url in candidates:
                print(f"\n  Încerc: {url}")
                time.sleep(0.5)
                resp = fetch(client, url, label="result")
                if resp is None:
                    continue

                # Verifica daca are listing-uri
                soup = BeautifulSoup(resp.text, "html.parser")
                cards, _ = find_listing_cards(soup, resp.text)
                if len(cards) >= 1:
                    print(f"  ✓ Carduri găsite: {len(cards)}")
                    success_url = str(resp.url)
                    success_html = resp.text
                    break
                else:
                    print(f"  ⚠ Niciun card listing (HTML: {len(resp.text):,} chars)")

            if success_url is None or success_html is None:
                print(f"\n  ✗ Niciun URL valabil găsit pentru {category}")
                continue

            # Analizeaza pagina
            analysis = analyze_result_page(success_html, success_url, category)

            print(f"\n  URL valid:         {success_url}")
            print(f"  Titlu pagina:      {analysis.get('page_title')}")
            print(f"  Total linkuri:     {analysis.get('total_links')}")
            print(f"  Total anunțuri:    {analysis.get('total_announced')}")
            print(f"  Card selector:     {analysis.get('card_selector')}")
            print(f"  Carduri găsite:    {analysis.get('card_count')}")
            print(f"  URL-uri listing:   {analysis.get('listing_count')}")
            print(f"  Promovate:         {analysis.get('promoted_count')}")
            print(f"  B2B (Companie):    {analysis.get('b2b_cards')}")
            print(f"  Private:           {analysis.get('private_cards')}")
            print(f"  Pagina urmatoare:  {analysis.get('next_page_url')}")
            print(f"  JSON-LD tipuri:    {analysis.get('jsonld_types')}")
            print(f"  Embedded scripts:  {len(analysis.get('embedded_scripts', []))}")
            print(f"  Clase relevante:   {analysis.get('relevant_classes', [])[:15]}")

            print(f"\n  Sample URL-uri + external_id:")
            for s in analysis.get("sample_external_ids", []):
                print(f"    [{s['external_id']:>12}]  {s['url']}")

            if analysis.get("embedded_scripts"):
                print(f"\n  Scripturi embedded:")
                for emb in analysis["embedded_scripts"]:
                    print(f"    [{emb['source']}] {emb['length']:,} chars keys={emb['keys']}")

            # Salvam HTML
            safe_name = category.replace("/", "_")
            html_path = TMP_DIR / f"romimo_result_{safe_name}.html"
            html_path.write_text(success_html, encoding="utf-8")
            print(f"\n  HTML salvat: {html_path}")

            # Retinem pentru pagini de detaliu
            if not found_category_url and analysis.get("listing_urls"):
                found_category_url = success_url
                found_listing_urls = analysis["listing_urls"]
                found_category = category

        # ── B. Pagini de detaliu ──────────────────────────────────────────
        print(f"\n{'─'*65}")
        print(f"[B] PAGINI DE DETALIU (max 3, din: {found_category})")
        print(f"{'─'*65}")

        if not found_listing_urls:
            print("\n  ⚠ Niciun URL de listing găsit. Probe oprit.")
            print("  Posibile cauze:")
            print("  - Romimo folosește alte URL-uri (verificați manual browserul)")
            print("  - Pagina e redată client-side (JS)")
            print("  - Site indisponibil")
        else:
            for i, detail_url in enumerate(found_listing_urls[:3], 1):
                print(f"\n  [{i}] {detail_url}")
                time.sleep(REQUEST_DELAY)

                resp = fetch(client, detail_url, label=f"detail-{i}")
                if resp is None:
                    continue

                detail_html = resp.text
                detail_soup = BeautifulSoup(detail_html, "html.parser")

                ch = detect_challenge(detail_soup, detail_html)
                if ch:
                    print(f"      ⛔ Challenge: {ch}")
                    continue

                data = parse_detail_page(detail_html, detail_url)

                print(f"      external_id:     {data.get('external_id')}")
                print(f"      canonical_url:   {data.get('canonical_url')}")
                print(f"      titlu:           {data.get('title')}")
                print(f"      descriere:       {(data.get('description_snippet') or '')[:120]}")
                print(f"      price_raw:       {data.get('price_raw')}")
                print(f"      price_eur:       {data.get('price_eur')}")
                print(f"      currency:        {data.get('original_currency')}")
                print(f"      rooms:           {data.get('rooms')}")
                print(f"      surface_m2:      {data.get('surface_m2')}")
                print(f"      floor:           {data.get('floor')}")
                print(f"      seller_type:     {data.get('seller_type')}")
                print(f"      seller_name:     {data.get('seller_name')}")
                print(f"      seller_src:      {data.get('seller_type_source')}")
                print(f"      published_raw:   {data.get('published_at_raw')}")
                print(f"      published_at:    {data.get('published_at')}")
                print(f"      updated_raw:     {data.get('updated_at_source_raw')}")
                print(f"      updated_at:      {data.get('updated_at_source')}")
                print(f"      location_raw:    {data.get('location_raw')}")
                print(f"      breadcrumbs:     {data.get('breadcrumbs')}")
                print(f"      imagini:         {data.get('image_count')}")
                print(f"      jsonld_types:    {data.get('jsonld_types')}")
                print(f"      embedded:        {data.get('embedded_scripts_count')} scripturi")

                detail_path = TMP_DIR / f"romimo_detail_{i}.html"
                detail_path.write_text(detail_html, encoding="utf-8")
                print(f"      HTML salvat: {detail_path}")

    print(f"\n{'='*65}")
    print("=== Probe complet ===")
    print(f"Fișiere salvate în: {TMP_DIR}")
    print()
    print("NEXT STEPS:")
    print("  1. Verificați manual URL-urile de listing în browser")
    print("  2. Confirmați external_id stabil (nu se schimbă la refresh)")
    print("  3. Confirmați seller_type (Persoană / Companie) din pagina de detaliu")
    print("  4. Confirmați card selector corect")
    print("  5. Raportați output-ul pentru implementarea adaptorului")


if __name__ == "__main__":
    run_probe()
