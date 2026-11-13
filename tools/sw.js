/* Фоновый скрипт кабинета (2026-10-23): офлайн для всех страниц /tools/ — оболочка и копия данных.
   Вся логика — sw-offline.js (общая с portfolio-sw.js вьюера). Регистрирует ui-kit (uiOfflineInit)
   на каждой странице. ?v= у ядра = CAB_OFF_VER: поменял ядро — подними версию здесь и в portfolio-sw.js,
   иначе браузер не заметит обновления. */
const SW_VERSION = '1.2.6';
importScripts('sw-offline.js?v=1.6.1');

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
