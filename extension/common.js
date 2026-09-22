// Etichete și formatare comune (popup + panou)
const AI_TYPE = { apartment: 'Apartament', house: 'Casă', land: 'Teren', commercial: 'Spațiu comercial' };
const AI_SELLER = { private: 'Proprietar', agency: 'Agenție', developer: 'Dezvoltator' };
function aiEur(n) { return n == null ? '—' : new Intl.NumberFormat('ro-RO').format(Math.round(n)) + ' €'; }
function aiEsc(s) { return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
