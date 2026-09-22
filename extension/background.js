// Service worker: face cererile către backend-ul AgencyIntel (localhost),
// ca pagina site-ului (OLX, Storia...) să nu aibă acces la cheie.

const DEFAULTS = { apiUrl: 'http://127.0.0.1:8000', apiKey: '' };

async function settings() {
  const s = await chrome.storage.sync.get(DEFAULTS);
  return { apiUrl: (s.apiUrl || DEFAULTS.apiUrl).replace(/\/+$/, ''), apiKey: s.apiKey || '' };
}

async function call(path, options = {}) {
  const { apiUrl, apiKey } = await settings();
  if (!apiKey) throw new Error('Setează cheia extensiei: click dreapta pe iconiță → Opțiuni.');
  let res;
  try {
    res = await fetch(apiUrl + path, {
      ...options,
      headers: { 'Content-Type': 'application/json', 'X-Extension-Key': apiKey, ...(options.headers || {}) },
    });
  } catch (e) {
    throw new Error(`Backend-ul nu răspunde la ${apiUrl}. Pornește-l cu: uvicorn app.main:app --port 8000`);
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* nu e JSON */ }
  if (!res.ok) throw new Error((data && data.detail) || `Eroare ${res.status}`);
  return data;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg.type === 'analyze') return call('/api/v1/extension/analyze', { method: 'POST', body: JSON.stringify(msg.payload) });
    if (msg.type === 'search') return call('/api/v1/extension/search?' + new URLSearchParams(msg.params).toString());
    if (msg.type === 'ping') return call('/api/v1/extension/ping');
    throw new Error('mesaj necunoscut');
  })()
    .then((data) => sendResponse({ ok: true, data }))
    .catch((e) => sendResponse({ ok: false, error: e.message || String(e) }));
  return true; // răspuns asincron
});
