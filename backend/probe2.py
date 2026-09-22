"""Probe 2: verifica daca storia e chiar blocat + analizeaza homezz + gaseste URL-uri corecte."""
import re
import httpx
from bs4 import BeautifulSoup

H = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


def get(url):
    return httpx.get(url, headers=H, timeout=30, follow_redirects=True)


print("=" * 70)
print("1. STORIA — e chiar blocat sau e continut real?")
print("=" * 70)
try:
    r = get("https://www.storia.ro/ro/rezultate/vanzare/apartament/alba")
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else "(fara title)"
    print(f"  status={r.status_code}  title={title[:80]!r}")

    # Unde apare cuvantul captcha?
    low = r.text.lower()
    for m in list(re.finditer(r"captcha", low))[:3]:
        s = max(0, m.start() - 70)
        print(f"  ...{r.text[s:m.start()+40]!r}")

    # __NEXT_DATA__ prezent?
    nd = soup.find("script", id="__NEXT_DATA__")
    print(f"  __NEXT_DATA__: {'DA (' + str(len(nd.string or '')) + ' bytes)' if nd else 'nu'}")

    # Link-uri catre oferte
    offers = {a["href"] for a in soup.find_all("a", href=True) if "/oferta/" in a["href"]}
    print(f"  link-uri /oferta/: {len(offers)}")
    for o in list(offers)[:5]:
        print(f"    {o[:95]}")
except Exception as e:
    print(f"  ERR {type(e).__name__}: {e}")

print()
print("=" * 70)
print("2. HOMEZZ — structura")
print("=" * 70)
try:
    r = get("https://www.homezz.ro/anunturi-imobiliare/alba")
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"  status={r.status_code}  title={soup.title.get_text(strip=True)[:80]!r}")
    links = [a["href"] for a in soup.find_all("a", href=True)]
    pat = {}
    for l in links:
        m = re.match(r"^(?:https?://[^/]+)?(/[a-z0-9\-]+)/", l)
        if m:
            pat[m.group(1)] = pat.get(m.group(1), 0) + 1
    print("  prefixe de link frecvente:")
    for k, v in sorted(pat.items(), key=lambda x: -x[1])[:8]:
        print(f"    {k:<40} x{v}")
    jl = soup.find_all("script", attrs={"type": "application/ld+json"})
    print(f"  blocuri JSON-LD: {len(jl)}")
except Exception as e:
    print(f"  ERR {type(e).__name__}: {e}")

print()
print("=" * 70)
print("3. URL-uri corecte pentru sursele cu 404")
print("=" * 70)
for name, home in [("lajumate", "https://www.lajumate.ro"),
                   ("anuntul", "https://www.anuntul.ro"),
                   ("imopedia", "https://www.imopedia.ro")]:
    try:
        r = get(home)
        soup = BeautifulSoup(r.text, "html.parser")
        hits = []
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if re.search(r"imobil|apartament|vanzare", h, re.I) and h not in hits:
                hits.append(h)
        print(f"  {name} (status={r.status_code}): {len(hits)} link-uri imobiliare")
        for h in hits[:6]:
            print(f"    {h[:95]}")
    except Exception as e:
        print(f"  {name}: ERR {type(e).__name__}")
