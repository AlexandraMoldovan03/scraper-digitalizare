const form = document.getElementById('f');
const statusEl = document.getElementById('status');
const results = document.getElementById('results');

document.getElementById('opts').onclick = (e) => { e.preventDefault(); chrome.runtime.openOptionsPage(); };

// ultima căutare rămâne completată
chrome.storage.local.get({ lastSearch: null }, ({ lastSearch }) => {
  if (!lastSearch) return;
  for (const [k, v] of Object.entries(lastSearch)) if (form.elements[k]) form.elements[k].value = v;
});

chrome.runtime.sendMessage({ type: 'ping' }, (res) => {
  statusEl.textContent = res?.ok ? `Conectat · ${res.data.listings.toLocaleString('ro-RO')} anunțuri în baza ta` : (res?.error || 'Neconectat');
});

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const raw = Object.fromEntries(new FormData(form).entries());
  chrome.storage.local.set({ lastSearch: raw });
  const params = Object.fromEntries(Object.entries(raw).filter(([, v]) => v !== ''));
  params.limit = 40;
  statusEl.textContent = 'Caut…';
  results.innerHTML = '';
  chrome.runtime.sendMessage({ type: 'search', params }, (res) => {
    if (!res?.ok) { statusEl.textContent = res?.error || 'Eroare'; return; }
    statusEl.textContent = res.data.length ? `${res.data.length} rezultate` : 'Niciun anunț pentru aceste filtre.';
    results.innerHTML = res.data.map((l) => {
      const seller = l.seller_type === 'private' ? '<span class="pill own">Proprietar</span>'
        : l.seller_type === 'agency' ? '<span class="pill ag">Agenție</span>' : '';
      const specs = [l.surface_m2 ? `${Math.round(l.surface_m2)} m²` : null, l.rooms ? `${l.rooms} cam.` : null,
        l.price_per_m2 ? `${aiEur(l.price_per_m2)}/m²` : null].filter(Boolean).join(' · ');
      return `<a class="item" href="${aiEsc(l.url)}" target="_blank" rel="noopener">
        ${l.image ? `<img src="${aiEsc(l.image)}" referrerpolicy="no-referrer">` : '<img>'}
        <div><div class="t">${aiEsc(l.title || '')}</div>
        <div><b>${aiEur(l.price_eur)}</b> <span class="muted">${aiEsc(specs)}</span></div>
        <div class="muted">${seller}${aiEsc([l.city, l.zone].filter(Boolean).join(', '))} · ${aiEsc(l.source)}</div></div></a>`;
    }).join('');
  });
});
