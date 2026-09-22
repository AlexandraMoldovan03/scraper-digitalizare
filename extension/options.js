const $ = (id) => document.getElementById(id);
chrome.storage.sync.get({ apiUrl: 'http://127.0.0.1:8000', apiKey: '' }, (s) => {
  $('apiUrl').value = s.apiUrl;
  $('apiKey').value = s.apiKey;
});
$('save').onclick = () => {
  chrome.storage.sync.set({ apiUrl: $('apiUrl').value.trim(), apiKey: $('apiKey').value.trim() }, () => {
    $('msg').textContent = 'Salvat. Testez conexiunea…';
    chrome.runtime.sendMessage({ type: 'ping' }, (res) => {
      $('msg').textContent = res?.ok
        ? `✅ Conectat — ${res.data.listings.toLocaleString('ro-RO')} anunțuri în baza ta.`
        : `❌ ${res?.error || 'Nu mă pot conecta.'}`;
    });
  });
};
