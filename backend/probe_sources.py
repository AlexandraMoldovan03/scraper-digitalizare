"""
Probe: ce surse imobiliare raspund de pe masina ta?
Ruleaza: PYTHONPATH=. python probe_sources.py
"""
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}

CANDIDATES = [
    ("storia",       "https://www.storia.ro/ro/rezultate/vanzare/apartament/alba"),
    ("imobiliare.ro","https://www.imobiliare.ro/vanzare-apartamente/judet-alba"),
    ("olx",          "https://www.olx.ro/imobiliare/apartamente-garsoniere-de-vanzare/alba-iulia/"),
    ("lajumate",     "https://www.lajumate.ro/imobiliare/apartamente-de-vanzare/alba"),
    ("anuntul",      "https://www.anuntul.ro/anunturi-imobiliare/vanzari-apartamente/alba/"),
    ("imopedia",     "https://www.imopedia.ro/vanzare-apartamente/alba"),
    ("homezz",       "https://www.homezz.ro/anunturi-imobiliare/alba"),
    ("titirez",      "https://www.titirez.ro/vanzare-apartamente-alba"),
]

BLOCK_WORDS = ("captcha", "just a moment", "cf-browser", "access denied",
               "enable javascript", "ray id", "ddos-guard")

print(f"{'sursa':<15} {'status':<8} {'bytes':<10} nota")
print("-" * 60)

for name, url in CANDIDATES:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True)
        body = r.text.lower()
        note = ""
        if r.status_code == 200:
            hits = [w for w in BLOCK_WORDS if w in body]
            if hits:
                note = f"bot-check: {hits[0]}"
            elif len(r.text) < 5000:
                note = "raspuns foarte scurt (posibil blocat)"
            else:
                note = "OK - pare continut real"
        else:
            note = "blocat / eroare"
        print(f"{name:<15} {r.status_code:<8} {len(r.text):<10} {note}")
    except Exception as exc:
        print(f"{name:<15} {'ERR':<8} {'-':<10} {type(exc).__name__}: {str(exc)[:40]}")

print()
print("Sursele cu 'OK - pare continut real' sunt candidate pentru adaptor.")
