# Phase 10.2 — NAS hosting (архивный план)

**Статус:** отложено. Активной работой не является. Этот документ сохраняет полный контекст обсуждения, чтобы вернуться к фазе без потери решений.

**Зависимость:** Phase 10.1 (`tools/portfolio-integrated-viewer.html`) должна быть готова — фаза 10.2 расширяет его HTTP loading-режимами и поднимает сервер на NAS.

---

## 1. Контекст и ограничения

### Зачем хостинг

Phase 10.1 даёт локальный дашборд, открываемый через `file://` в Safari со смонтированного NAS или Synology Drive sync. Этого достаточно для macOS desktop. **Чего не хватает:**
- iPhone в LAN: `file://` через mounted NAS на iOS Safari работает плохо/никак.
- Любое устройство без mount'а NAS — не открыть.
- Нет URL-доступа из любой точки сети («открой такую-то ссылку»).
- Глобальный доступ из интернета невозможен.

Phase 10.2 решает это: поднимает HTTP-сервер на NAS, через который viewer и данные доступны по URL.

### Почему Web Station «в лоб» не работает

Synology Web Station по дефолту обслуживает только `/volume1/web/` и пакетные document roots. Папка `/home/<user>/Ext_gDrive/Claude-Memory/` (где живут данные через Synology Drive sync) **недоступна Apache** по нескольким причинам:

1. **Permissions**: Apache работает под пользователем `http`, у которого нет прав на `/var/services/homes/<user>/`. Через ACL/`chmod` можно дать, но это ломает Synology security model.
2. **Symlinks**: Apache имеет `Options +FollowSymLinks`, но Synology DSM 7 включает `SymLinksIfOwnerMatch` или AppArmor-правила, которые блокируют симлинки на чужие тома.
3. **Перенос данных в `/volume1/web/Claude-Memory/`**: ломает Synology Drive sync (его клиент работает с конкретной папкой в `/home/`); требует переконфигурации sync-схемы и risk-managment'а консистентности.

Поэтому стандартное «сделать virtual host над Claude-Memory» не проходит без хирургии.

---

## 2. Три опции hosting'а

### Опция A — Container Manager + Caddy (рекомендация)

**Что:** docker-контейнер с Caddy 2.x в DSM Container Manager (DSM 7.2+). Bind-mount папки `Claude-Memory/` в контейнер. Caddy раздаёт статику + autoindex + Basic Auth + HTTPS.

**Преимущества:**
- 50 МБ образ, один файл конфигурации (`Caddyfile`).
- `file_server browse` даёт autoindex с предсказуемым HTML — JS парсит на ура.
- Basic Auth: `basicauth { user $2a$bcrypt }` — одна строка.
- HTTPS автоматически через Let's Encrypt (если глобальный доступ).
- Bind mount read-only — безопасно.
- Автоматический рестарт с NAS.
- **Не требует переноса данных и не ломает Synology Drive sync.**

**Минимальный Caddyfile (LAN, без auth):**
```
:8080 {
    root * /srv
    file_server browse
}
```

**С auth (для глобального доступа):**
```
:8080 {
    root * /srv
    file_server browse
    basicauth {
        user $2a$14$<bcrypt-hash>
    }
}
```

Bcrypt-хэш генерируется через `caddy hash-password` в самом контейнере или через любой online-генератор.

**Шаги установки:**
1. DSM Package Center → установить Container Manager (если ещё нет).
2. Container Manager → Project → Create:
   - Source: `compose.yaml` (внести руками)
   - Compose: см. ниже
3. Положить Caddyfile рядом.
4. Запустить project.

**docker-compose.yml пример:**
```yaml
version: "3"
services:
  caddy:
    image: caddy:2-alpine
    container_name: portfolio-viewer
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /var/services/homes/user/Ext_gDrive/Claude-Memory:/srv:ro
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
volumes:
  caddy_data:
```

Эффорт: ~5 минут после установки Container Manager.

---

### Опция B — Task Scheduler + python3 http.server

**Что:** DSM Task Scheduler запускает на boot простой `python3 -m http.server` под user account.

**Преимущества:**
- Нулевая зависимость (Python уже в DSM).
- Запуск под user → права на `/home/` есть.
- Конфигурация в одной задаче DSM.

**Недостатки:**
- Нет Basic Auth (без обёртки) → только LAN.
- Не поддерживает HTTPS из коробки.
- `python3 -m http.server` имеет autoindex, но формат HTML отличается от Apache/Caddy — нужен отдельный parser.

**Команда:**
```bash
cd /var/services/homes/user/Ext_gDrive/Claude-Memory && \
  python3 -m http.server 8080 --bind 0.0.0.0
```

В DSM Task Scheduler:
- Type: User-defined script
- User: user
- Schedule: Boot-up
- Run command: см. выше

Эффорт: ~2 минуты.

---

### Опция C — rsync mirror в /volume1/web/Claude-Memory-Mirror/ + Web Station

**Что:** cron-задача делает rsync из `/home/.../Claude-Memory/` в `/volume1/web/Claude-Memory-Mirror/`. Web Station обслуживает зеркало.

**Преимущества:**
- Использует штатный Web Station.
- Полная поддержка Apache (`.htaccess`, autoindex, Basic Auth).

**Недостатки:**
- **Дублирование данных** — занимает дисковое место дважды.
- Sync-логика: если rsync упал между save-to-library и просмотром — viewer покажет устаревшие данные.
- Cron-задача требует maintenance (что если расписание сменилось / файл-классификация добавилась).

**Cron (раз в 5 минут):**
```bash
*/5 * * * * rsync -a --delete /var/services/homes/user/Ext_gDrive/Claude-Memory/ /volume1/web/Claude-Memory-Mirror/
```

Эффорт: высокий из-за sync-семантики. **Не рекомендуется**, кроме случаев когда A и B недоступны.

---

## 3. Доступ — LAN и глобально

### LAN (по умолчанию)

`http://<nas-local-ip>:8080/portfolio-integrated-viewer.html` — доступно с любого устройства в той же Wi-Fi/Ethernet. Без auth — это домашняя сеть, риск низкий (но не нулевой; если в сети гости — auth обязателен).

### Глобально — QuickConnect

Synology QuickConnect → DDNS → доступ из интернета по `<id>.quickconnect.to`.

**Обязательно:**
- HTTPS (Synology Let's Encrypt бесплатно через Control Panel → Security → Certificate).
- Basic Auth (Caddyfile в опции A или `.htaccess` в опции C).
- IP allowlist если возможно.

### Глобально — Reverse Proxy

DSM Control Panel → Login Portal → Reverse Proxy → пробросить `https://portfolio.<your-domain>/` на `http://localhost:8080/`.

Преимущества: свой домен, нативный HTTPS через Synology, можно навешать DSM-уровневую аутентификацию.

---

## 4. HTTP loading modes для viewer'а

После поднятия HTTP-сервера в viewer'е активируются дополнительные режимы. Логика auto-detect в Phase 10.2:

```
1. file:// → Mode 4 (folder picker, как в 10.1)
2. http(s):// + autoindex детектится → Mode 1
3. http(s):// + manifest.json есть → Mode 2
4. http(s):// + ?view= в URL → Mode 3
5. Иначе → Mode 5 (drag-drop fallback)
```

### Mode 1 — autoindex parser (PRIMARY для опций A и C)

- Условие: `location.protocol === 'http(s):'`, HEAD-запрос на `..../` возвращает HTML с autoindex-сигнатурой Caddy или Apache.
- Поведение: viewer fetch'ит autoindex для `Portfolio/integrated-views/`, парсит regexp'ом по `<a href="...">`, выбирает latest по дате из имени, читает frontmatter `inputs:`, fetch'ит supplementary, параллельно сканит `weekly-reviews/`, `stress/`, `../macro-snapshots/` для history strips.
- **Ноль кликов от пользователя.**

Парсер autoindex (~20 строк JS):
```javascript
function parseAutoindex(html, baseUrl) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  return [...doc.querySelectorAll('a[href]')]
    .map(a => a.getAttribute('href'))
    .filter(href => href && !href.startsWith('?') && !href.startsWith('/') && href !== '../')
    .map(href => new URL(href, baseUrl).href);
}
```

Caddy и Apache HTMLTable autoindex оба работают через этот парсер.

### Mode 2 — manifest.json fallback

- Условие: HTTP, autoindex отключён или недоступен, но рядом с viewer лежит `manifest.json`.
- Поведение: viewer fetch'ит `manifest.json` со списком артефактов, дальше как Mode 1.

**Формат manifest.json:**
```json
{
  "generated_at": "2026-05-07T10:30:00Z",
  "integrated_views": ["integrated-view-2026-05-04.md"],
  "weekly_reviews": ["weekly-review-2026-05-04.yaml", "weekly-review-2026-04-27.yaml"],
  "stress": ["stress-2026-05-04-iron-curtain.yaml"],
  "portfolios": ["portfolio-2026-05-03.json"],
  "macro_snapshots": ["ru-2026-04-30.md", "ru-2026-05-01.md"]
}
```

**Генератор `tools/regen-manifest.sh`:**
```bash
#!/bin/bash
# Генерирует Claude-Memory/Tools/manifest.json
ROOT="${1:-/var/services/homes/user/Ext_gDrive/Claude-Memory}"
cd "$ROOT"

cat > Tools/manifest.json <<EOF
{
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "integrated_views": $(ls Portfolio/integrated-views/integrated-view-*.md 2>/dev/null | jq -R . | jq -s .),
  "weekly_reviews": $(ls Portfolio/weekly-reviews/weekly-review-*.yaml 2>/dev/null | jq -R . | jq -s .),
  "stress": $(ls Portfolio/stress/stress-*.yaml 2>/dev/null | jq -R . | jq -s .),
  "portfolios": $(ls Portfolio/snapshots/portfolio-*.json 2>/dev/null | jq -R . | jq -s .),
  "macro_snapshots": $(ls macro-snapshots/ru-*.md 2>/dev/null | jq -R . | jq -s .)
}
EOF
```

Запускать: cron каждые 15 минут, или hook на save-to-library.

### Mode 3 — URL query

- Условие: HTTP, нет autoindex, нет manifest, но в URL `?view=integrated-view-2026-05-04.md`.
- Поведение: viewer fetch'ит указанный integrated-view, читает frontmatter `inputs:`, fetch'ит supplementary по соглашению о путях. **History strips недоступны** (нечем сканировать папки).

Это минимальный fallback. Полезно, когда хочется передать ссылку «открой такой-то view» без полного listing'а.

---

## 5. Безопасность — обязательно если глобально

В файлах portfolio-* лежит структура личного портфеля, в integrated-view — рекомендации. Глобальный доступ без защиты = утечка financial data.

**Минимум для глобального доступа:**
- HTTPS (Let's Encrypt в DSM или Reverse Proxy).
- Basic Auth (Caddyfile в опции A; `.htaccess` + `htpasswd` в опции C).
- Rate limiting (опц., через Caddy plugins или Synology Firewall).
- IP allowlist (если есть статический IP — Synology Firewall).

**Privacy от viewer'а** (то, что viewer не отправляет данные третьим сторонам — spec06 §2.3) сохраняется. Защищать нужно HTTP-уровень доступа.

---

## 6. Объём Phase 10.2

| Этап | Что | Сессий |
|---|---|---|
| **F** | Mode 1 (autoindex parser для Caddy и Apache) + Mode 3 (URL query) в viewer'е | 0.5 |
| **G** | `tools/Caddyfile` + `tools/SYNOLOGY-SETUP.md` (опции A, B, C с пошаговыми инструкциями) | 0.5 |
| **H** (опц.) | Mode 2 (manifest.json) + `regen-manifest.sh` cron-script | 0.3 |

**Phase 10.2 = ~1–1.3 сессии.** Расширяет Phase 10.1 без переработки уже сделанного.

---

## 7. Ссылки

- `tools/portfolio-integrated-viewer.html` — артефакт Phase 10.1, который Phase 10.2 расширяет.
- `INTEGRATION-DOCS/06-portfolio-integrated-viewer-HTML-spec.md` — основная спецификация viewer'а.
- `docs/investment/_cross-cutting/plan.md` Phase 10 — активный roadmap.
