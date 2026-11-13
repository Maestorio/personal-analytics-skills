/* Фоновый скрипт вьюера портфеля (v3-B, вьюер 3.35.0): push-уведомления.
   С 2026-10-23 (1.1.0) — ещё и офлайн, общим ядром sw-offline.js (как /tools/sw.js остальных страниц):
   его scope уже, поэтому вьюером управляет он, и офлайн у вьюера должен быть тот же. Подписки push
   привязаны к этому файлу и scope — не переименовывать и не заменять на sw.js.
   Лежит в /tools/ (не в assets/): область действия фонового скрипта не может быть
   выше его папки, а вьюер — /tools/portfolio-integrated-viewer.html.
   Уведомление: {title, body, url, tag} от hub-notify (tools/hosting/notify/notifier.py);
   нажатие открывает вьюер на url (#card=ТИКЕР — карточка бумаги, #tab=… — раздел).
   1.4.0 (2026-10-26): уведомления других разделов (игры: /tools/games.html#sale) — на свою
   страницу; раньше открытый вьюер перехватывал любое нажатие и оставался на месте. */
const SW_VERSION = '1.4.6';
importScripts('sw-offline.js?v=1.6.1');

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (e) => {
  let m = {};
  try { m = e.data ? e.data.json() : {}; } catch (_) { m = { title: 'Портфель', body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(m.title || 'Портфель', {
    body: m.body || '',
    tag: m.tag || undefined,
    data: { url: m.url || '/tools/portfolio-integrated-viewer.html' },
    icon: '/tools/assets/icons/portfolio-192.png',
    badge: '/tools/assets/icons/portfolio-192.png',
    lang: 'ru',
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || '/tools/portfolio-integrated-viewer.html', self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const toViewer = url.includes('/portfolio-integrated-viewer.html');
    const w = toViewer && wins.find(c => c.url.includes('/portfolio-integrated-viewer.html'));
    if (!toViewer && wins.length) {
      // другая страница кабинета: окно приложения переходит на неё (navigate — только у окон под
      // этим скриптом; не вышло — новое окно)
      const c = wins.find(x => x.focused) || wins[0];
      try { await c.focus(); if (c.navigate && await c.navigate(url)) return; } catch (_) {}
    }
    if (w) {
      // вьюер уже открыт: перейти на нужное место без перезагрузки (страница слушает сообщение)
      await w.focus();
      w.postMessage({ type: 'piv-open', url });
      return;
    }
    await self.clients.openWindow(url);
  })());
});
