// Rulează pe paginile de anunț. Extrage datele anunțului, cere analiza de la
// backend și afișează un panou în colțul paginii (ca Phia, dar pentru imobiliare).
(() => {
  if (window.__agencyIntelLoaded) return;
  window.__agencyIntelLoaded = true;

  const host = location.hostname.replace(/^www\./, '');

  // Doar paginile de anunț (nu listele de rezultate)
  const isAdPage =
    (host === 'olx.ro' && /\/(d\/)?oferta\//.test(location.pathname)) ||
    (host === 'storia.ro' && location.pathname.includes('/oferta/')) ||
    (host === 'imobiliare.ro' && location.pathname.startsWith('/oferta/')) ||
    (host === 'publi24.ro' && location.pathname.includes('/anunt/')) ||
    (host === 'romimo.ro' && /anunt/.test(location.pathname));
  if (!isAdPage) return;

  const ALBA = ['Alba Iulia', 'Sebeș', 'Aiud', 'Blaj', 'Cugir', 'Ocna Mureș', 'Teiuș', 'Zlatna', 'Abrud', 'Câmpeni',
    'Baia de Arieș', 'Ciugud', 'Micești', 'Oarda', 'Bărăbanț', 'Pâclișa', 'Sântimbru', 'Galda de Jos', 'Ighiu',
    'Vințu de Jos', 'Cricău', 'Unirea', 'Lancrăm', 'Petrești', 'Sâncel', 'Șard', 'Albac', 'Arieșeni', 'Horea'];

  const fold = (s) => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

  function num(text) {
    if (text == null) return null;
    if (typeof text === 'number') return text;
    const m = String(text).match(/\d{1,3}(?:[ ., ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?/);
    if (!m) return null;
    let t = m[0].replace(/[  ]/g, '');
    const last = Math.max(t.lastIndexOf('.'), t.lastIndexOf(','));
    if (last >= 0) {
      const after = t.slice(last + 1);
      t = after.length === 3 ? t.replace(/[.,]/g, '') : t.slice(0, last).replace(/[.,]/g, '') + '.' + after;
    }
    const n = parseFloat(t);
    return Number.isFinite(n) ? n : null;
  }

  function jsonLd() {
    const out = [];
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const d = JSON.parse(s.textContent);
        const items = Array.isArray(d) ? d : d['@graph'] ? d['@graph'] : [d];
        out.push(...items);
      } catch { /* ignor */ }
    }
    return out;
  }

  function nextData() {
    const el = document.getElementById('__NEXT_DATA__');
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch { return null; }
  }

  function extract() {
    const d = { url: location.href, title: document.querySelector('h1')?.innerText?.trim() || document.title };
    const bodyText = document.body.innerText.slice(0, 20000);

    // 1. Date structurate
    for (const item of jsonLd()) {
      const offers = Array.isArray(item.offers) ? item.offers[0] : item.offers;
      if (offers && offers.price && !d.price_eur && (!offers.priceCurrency || /EUR/i.test(offers.priceCurrency))) {
        d.price_eur = num(offers.price);
      }
      if (item.floorSize?.value && !d.surface_m2) d.surface_m2 = num(item.floorSize.value);
      if (item.numberOfRooms && !d.rooms) d.rooms = num(item.numberOfRooms);
      const loc = item.address?.addressLocality || offers?.availableAtOrFrom?.address?.addressLocality;
      if (loc && !d.locality) d.locality = loc;
    }

    // 2. Storia: JSON-ul paginii
    const nd = nextData();
    const ad = nd?.props?.pageProps?.ad;
    if (ad) {
      const ch = Object.fromEntries((ad.characteristics || []).map((c) => [c.key, c.value]));
      d.price_eur = d.price_eur || num(ch.price);
      d.surface_m2 = d.surface_m2 || num(ch.m);
      d.rooms = d.rooms || num(ch.rooms_num);
      d.locality = d.locality || ad.location?.address?.city?.name;
      const est = (ad.target?.ProperType || ad.estate || '').toString().toLowerCase();
      if (/flat|apartament/.test(est)) d.property_type = 'apartment';
      else if (/house|casa/.test(est)) d.property_type = 'house';
      else if (/terrain|teren/.test(est)) d.property_type = 'land';
      if (ad.advertiserType) d.seller_type = /private/i.test(ad.advertiserType) ? 'private' : 'agency';
    }

    // 3. Prețul din pagină
    if (!d.price_eur) {
      const priceEl = document.querySelector('[data-testid="ad-price-container"], [data-cy="adPageHeaderPrice"], .price, [class*="price"]');
      const m = (priceEl?.innerText || bodyText).match(/(\d{1,3}(?:[ ., ]\d{3})+|\d{4,})\s*(€|eur)/i);
      if (m) d.price_eur = num(m[1]);
    }

    // 4. Suprafața / camerele din text
    if (!d.surface_m2) {
      const m = bodyText.match(/suprafa[tț][aă]\s*(util[aă]|construit[aă])?\s*:?\s*(\d+(?:[.,]\d+)?)\s*(m²|m2|mp)/i)
        || bodyText.match(/(\d+(?:[.,]\d+)?)\s*(m²|m2|mp)\b/i);
      if (m) d.surface_m2 = num(m[2] && /\d/.test(m[2]) ? m[2] : m[1]);
    }
    if (!d.rooms) {
      const m = (d.title + ' ' + bodyText.slice(0, 3000)).match(/(\d)\s*(camere|camera|cam\.)/i);
      if (m) d.rooms = parseInt(m[1], 10);
      else if (/garsonier/i.test(d.title)) d.rooms = 1;
    }

    // 5. Localitatea (din Alba)
    if (!d.locality) {
      const hay = fold(document.querySelector('nav, [data-testid="breadcrumbs"], .breadcrumb')?.innerText + ' ' + location.pathname + ' ' + d.title);
      d.locality = ALBA.filter((c) => hay.includes(fold(c)) || hay.includes(fold(c).replace(/ /g, '-')))
        .sort((a, b) => b.length - a.length)[0];
    }

    // 6. Proprietar / agenție (OLX afișează „Persoană fizică” / „Firmă”)
    if (!d.seller_type) {
      if (/persoan[aă] fizic[aă]|proprietar/i.test(bodyText.slice(0, 8000))) d.seller_type = 'private';
      else if (/\bfirm[aă]\b|agen[tț]ie imobiliar/i.test(bodyText.slice(0, 8000))) d.seller_type = 'agency';
    }
    if (/inchiri|închiri|chirie/i.test(location.pathname + ' ' + d.title)) d.transaction_type = 'rent';
    return d;
  }

  // ── Panou ────────────────────────────────────────────────────────────────
  const hostEl = document.createElement('div');
  hostEl.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;';
  const root = hostEl.attachShadow({ mode: 'open' });
  document.documentElement.appendChild(hostEl);

  const css = `
    :host{all:initial}
    .card{font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#0f172a;background:#fff;
      width:340px;max-height:78vh;overflow:auto;border-radius:14px;box-shadow:0 10px 40px rgba(15,23,42,.25);border:1px solid #e2e8f0}
    .hd{display:flex;align-items:center;gap:8px;padding:10px 12px;background:#0f172a;color:#fff;border-radius:14px 14px 0 0;position:sticky;top:0}
    .hd b{flex:1;font-size:13px}.hd button{all:unset;cursor:pointer;color:#cbd5e1;font-size:16px;padding:0 4px}
    .bd{padding:12px}.muted{color:#64748b;font-size:12px}
    .verdict{border-radius:10px;padding:10px;margin-bottom:10px}
    .below{background:#ecfdf5;color:#065f46}.fair{background:#f1f5f9;color:#334155}.above{background:#fef2f2;color:#991b1b}.unknown{background:#f8fafc;color:#475569}
    .big{font-size:18px;font-weight:700}
    h4{margin:12px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#475569}
    a.item{display:flex;gap:8px;padding:6px;border-radius:8px;text-decoration:none;color:inherit;border:1px solid #f1f5f9;margin-bottom:6px}
    a.item:hover{background:#f8fafc;border-color:#e2e8f0}
    a.item img{width:54px;height:42px;object-fit:cover;border-radius:6px;background:#f1f5f9;flex:none}
    .t{font-weight:600;font-size:12px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
    .pill{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:99px;margin-right:4px}
    .own{background:#ccfbf1;color:#115e59}.ag{background:#dbeafe;color:#1e40af}
    .err{background:#fff7ed;color:#9a3412;padding:10px;border-radius:10px}
    .mini{all:unset;cursor:pointer;background:#0f172a;color:#fff;font:600 12px -apple-system,sans-serif;padding:8px 12px;border-radius:99px;box-shadow:0 6px 20px rgba(15,23,42,.3)}
  `;

  function itemHtml(l) {
    const seller = l.seller_type === 'private' ? '<span class="pill own">Proprietar</span>'
      : l.seller_type === 'agency' ? '<span class="pill ag">Agenție</span>' : '';
    const specs = [l.surface_m2 ? `${Math.round(l.surface_m2)} m²` : null, l.rooms ? `${l.rooms} cam.` : null,
      l.price_per_m2 ? `${aiEur(l.price_per_m2)}/m²` : null].filter(Boolean).join(' · ');
    return `<a class="item" href="${aiEsc(l.url)}" target="_blank" rel="noopener">
      ${l.image ? `<img src="${aiEsc(l.image)}" referrerpolicy="no-referrer">` : '<img>'}
      <div><div class="t">${aiEsc(l.title || '')}</div>
      <div><b>${aiEur(l.price_eur)}</b> <span class="muted">${aiEsc(specs)}</span></div>
      <div class="muted">${seller}${aiEsc([l.city, l.zone].filter(Boolean).join(', '))} · ${aiEsc(l.source)}</div></div></a>`;
  }

  function render(state) {
    let body = '';
    if (state.loading) body = '<div class="muted">Analizez anunțul…</div>';
    else if (state.error) body = `<div class="err">${aiEsc(state.error)}</div>`;
    else {
      const r = state.data, det = r.detected || {}, m = r.market;
      const label = { below: 'Sub prețul pieței', fair: 'Preț corect', above: 'Peste prețul pieței', unknown: 'Comparație indisponibilă' };
      if (m) {
        const diff = m.diff_percent;
        body += `<div class="verdict ${m.verdict}">
          <div class="big">${label[m.verdict]}${diff != null ? ` (${diff > 0 ? '+' : ''}${diff}%)` : ''}</div>
          <div>${det.price_per_m2 ? `Acest anunț: <b>${aiEur(det.price_per_m2)}/m²</b> · ` : ''}Mediana: <b>${aiEur(m.median_price_per_m2)}/m²</b></div>
          <div class="muted">${m.sample_size} anunțuri similare (${aiEsc(AI_TYPE[det.property_type] || '')}, ${aiEsc(det.city || m.scope)})</div>
        </div>`;
      } else {
        body += `<div class="verdict unknown">Prea puține anunțuri similare în baza ta pentru comparație.
          <div class="muted">Rulează actualizarea surselor în AgencyIntel.</div></div>`;
      }
      const facts = [
        det.property_type ? AI_TYPE[det.property_type] : null,
        det.price_eur ? aiEur(det.price_eur) : null,
        det.surface_m2 ? `${Math.round(det.surface_m2)} m²` : null,
        det.rooms ? `${det.rooms} camere` : null,
        det.city,
        det.seller_type ? AI_SELLER[det.seller_type] : null,
      ].filter(Boolean).join(' · ');
      body += `<div class="muted">${aiEsc(facts)}</div>`;
      if (r.known) {
        body += `<div class="muted">În baza ta de ${r.days_on_market} zile${r.price_history?.length > 1 ? ` · ${r.price_history.length} modificări de preț` : ''}.</div>`;
      }
      if (r.duplicates?.length) body += '<h4>Posibil același imobil (alt anunț / alt site)</h4>' + r.duplicates.map(itemHtml).join('');
      if (r.alternatives?.length) body += '<h4>Alternative mai ieftine</h4>' + r.alternatives.map(itemHtml).join('');
    }
    root.innerHTML = `<style>${css}</style>` + (state.collapsed
      ? `<button class="mini">🏠 AgencyIntel${state.data?.market?.diff_percent != null ? ` · ${state.data.market.diff_percent > 0 ? '+' : ''}${state.data.market.diff_percent}%` : ''}</button>`
      : `<div class="card"><div class="hd"><b>AgencyIntel · analiză anunț</b><button title="Micșorează">–</button></div><div class="bd">${body}</div></div>`);
    root.querySelector('.mini')?.addEventListener('click', () => { state.collapsed = false; render(state); });
    root.querySelector('.hd button')?.addEventListener('click', () => { state.collapsed = true; render(state); });
  }

  const state = { loading: true, collapsed: false };
  render(state);

  // Paginile moderne încarcă prețul după câteva sute de ms
  setTimeout(() => {
    const payload = extract();
    chrome.runtime.sendMessage({ type: 'analyze', payload }, (res) => {
      state.loading = false;
      if (chrome.runtime.lastError) state.error = chrome.runtime.lastError.message;
      else if (!res?.ok) state.error = res?.error || 'Eroare necunoscută';
      else state.data = res.data;
      render(state);
    });
  }, 1200);
})();
