async function handle(r) {
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.blob();
}

export const api = {
  get: (url) => fetch(url).then(handle),
  post: (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) }).then(handle),
  put: (url, body) => fetch(url, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) }).then(handle),
  del: (url) => fetch(url, { method: 'DELETE' }).then(handle),
  form: (url, fields) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) {
      if (v == null) continue;
      if (v instanceof Blob) fd.append(k, v, 'speech.wav'); else fd.append(k, v);
    }
    return fetch(url, { method: 'POST', body: fd }).then(handle);
  },
};

export function toast(msg, error = false, ms = 4000) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.toggle('error', error);
  el.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add('hidden'), ms);
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export const scoreClass = (s) => (s >= 80 ? 'good' : s >= 60 ? 'mid' : 'low');

export const state = { settings: null };
