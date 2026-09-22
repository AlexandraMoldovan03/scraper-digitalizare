"""Descopera structura __NEXT_DATA__ de pe Storia + verifica robots.txt."""
import json
import httpx
from bs4 import BeautifulSoup

H = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}

print("=" * 70)
print("0. ROBOTS.TXT — ce permite Storia")
print("=" * 70)
try:
    r = httpx.get("https://www.storia.ro/robots.txt", headers=H, timeout=20)
    lines = r.text.splitlines()
    # Afisam blocul User-agent: *
    show, shown = False, 0
    for ln in lines:
        low = ln.strip().lower()
        if low.startswith("user-agent:"):
            show = "*" in low
        if show and shown < 40:
            print("  " + ln)
            shown += 1
    print(f"  ... ({len(lines)} linii total)")
except Exception as e:
    print(f"  ERR: {e}")

print()
print("=" * 70)
print("1. STRUCTURA __NEXT_DATA__")
print("=" * 70)

r = httpx.get(
    "https://www.storia.ro/ro/rezultate/vanzare/apartament/alba",
    headers=H, timeout=30, follow_redirects=True,
)
soup = BeautifulSoup(r.text, "html.parser")
nd = soup.find("script", id="__NEXT_DATA__")
data = json.loads(nd.string)

# Salvam pentru inspectie ulterioara
with open("/tmp/storia_next_data.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("  (JSON complet salvat in /tmp/storia_next_data.json)")


def walk(node, path=""):
    """Cauta liste de dict-uri care arata ca listinguri."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            found += walk(v, f"{path}.{k}")
    elif isinstance(node, list) and node:
        if isinstance(node[0], dict):
            keys = set(node[0].keys())
            score = len(keys & {"id", "title", "price", "totalPrice", "areaInSquareMeters",
                                "roomsNumber", "slug", "location", "estate", "transaction"})
            if score >= 3:
                found.append((path, len(node), node[0]))
        for i, v in enumerate(node[:1]):
            found += walk(v, f"{path}[{i}]")
    return found


hits = walk(data)
print(f"\n  Candidati (liste care par listinguri): {len(hits)}")
for path, n, sample in hits:
    print(f"\n  --- {path}  ({n} elemente) ---")
    print(f"  chei: {sorted(sample.keys())}")
    print("  exemplu:")
    print(json.dumps(sample, ensure_ascii=False, indent=4)[:2500])
    print()

if not hits:
    print("  Niciun candidat. Structura de nivel inalt:")
    def outline(n, p="", d=0):
        if d > 4:
            return
        if isinstance(n, dict):
            for k, v in list(n.items())[:12]:
                t = type(v).__name__
                extra = f" [{len(v)}]" if isinstance(v, (list, dict)) else ""
                print("   " * d + f"{k}: {t}{extra}")
                outline(v, f"{p}.{k}", d + 1)
    outline(data)
