// Zero service worker: caches the shell assets so the app installs and opens fast; pages stay network-first.
const CACHE = 'zero-v2';
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(['/manifest.json'])).catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.startsWith('/static/') || url.hostname.includes('jsdelivr')) {
    e.respondWith(caches.open(CACHE).then(async (c) => { const hit = await c.match(e.request); if (hit) return hit; const res = await fetch(e.request); if (res.ok) c.put(e.request, res.clone()); return res; }));
  }
});
