#!/bin/zsh
# Деплой веб-артефактов Personal Hub из репозитория на Synology (Claude-Memory/tools/).
# Правило: правим версию в РЕПОЗИТОРИИ, потом выкладываем этим скриптом.
# Caddy подхватывает файлы сразу (перезапуск не нужен); Caddyfile — отдельно, руками на NAS.
#
# Данные раздела «Здоровье» (labs.json, biomarkers-info.json, meds/
# vaccinations/vitals/studies.json) сюда НЕ входят — с 2026-08-05 скиллы
# health-labs и health-meds пишут напрямую в Claude-Memory/Health/ на
# Synology, без промежуточного Mac-этапа и без деплоя. Этот скрипт
# деплоит только HTML-страницы/ассеты. С миграции 2026-08-13 Claude-Memory —
# ЕДИНОЕ дерево (homes/hubuser/Claude-Memory, вне облачных синков).
set -euo pipefail

# --check — только проверка NAS (ничего не копирует): запускать ПОСЛЕ `docker restart` / `compose up -d` на NAS,
# чтобы сразу увидеть, поднялись ли hub-api и hub-notify и на том ли они коде (без флага 502 видно лишь на странице).
CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

REPO_TOOLS="${0:A:h}"
REPO_HOSTING="$REPO_TOOLS/hosting"      # Caddyfile, compose, api/ — то, что живёт на NAS
SYN="$HOME/Library/CloudStorage/SynologyDrive-home"
CM_TOOLS="$SYN/Claude-Memory/tools"
HEALTH_DST="$SYN/Claude-Memory/Health"

[[ -d "$CM_TOOLS" ]] || { echo "❌ Synology не смонтирован: $CM_TOOLS"; exit 1; }

# Страницы хаба и разделов.
# ⚠ Новую страницу ОБЯЗАТЕЛЬНО вписать сюда — иначе она просто не уедет на NAS
# (реальный случай: login.html забыли → 404 на боевом; старый Caddyfile это
# ещё и маскировал, отдавая 401 на любой приватный путь, даже несуществующий).
# Список сверяется с tools/*.html в test_pages_contracts.py — забыть больше нельзя.
# Справка вьюера — tools/assets/help/viewer/ (едет с assets/ ниже); старый Claude-Memory/tools/viewer-help.md
# на NAS удалить руками.
NAS_STAGE="$SYN/Claude-Memory/_nas"
if (( ! CHECK_ONLY )); then
FILES=(hub.html travel.html games.html health.html food.html money.html login.html portfolio-integrated-viewer.html portfolio-sw.js sw.js sw-offline.js)
for f in "${FILES[@]}"; do
  [[ -f "$REPO_TOOLS/$f" ]] || { echo "· пропуск (нет в репо): $f"; continue; }
  rsync -c "$REPO_TOOLS/$f" "$CM_TOOLS/$f" && echo "✓ $f"
done

# Ассеты вьюера и кабинета (css/js/шрифты + assets/help/*.md — справки страниц)
rsync -rc "$REPO_TOOLS/assets/" "$CM_TOOLS/assets/" && echo "✓ assets/"

# Живое состояние здоровья (аптечка/прививки/вес/исследования) — каркасы для
# ещё не заведённых файлов. labs.json/biomarkers-info.json сюда не входят —
# их пишет health-labs напрямую (см. шапку файла).
if [[ -d "$HEALTH_DST" ]]; then
  # Живое состояние: мастер ТОЛЬКО здесь, на Synology. Копий на Маке нет
  # намеренно — раньше сид лежал ещё и в проекте Health, и было неясно, какой
  # файл настоящий (страница и скилл правят этот, а сид тихо устаревал).
  # Пустой каркас создаём прямо в мастере, если файла ещё нет.
  for f in meds vaccinations vitals studies; do
    [[ -f "$HEALTH_DST/$f.json" ]] && continue
    case $f in
      vitals) body='"height_cm": null, "weight": []' ;;
      *)      body="\"$f\": []" ;;
    esac
    printf '{\n  "schema": "health-%s@1",\n  "updated": "%s",\n  %s\n}\n' \
      "$f" "$(date +%Y-%m-%d)" "$body" > "$HEALTH_DST/$f.json"
    echo "✓ health-data/$f.json (пустой каркас)"
  done
else
  echo "· Каталог здоровья не заведён ($HEALTH_DST) — данные не деплою."
  echo "  Создать: mkdir -p \"$HEALTH_DST\""
fi

# ── Раздел «Еда»: только каркасы, содержимое НЕ трогаем ─────────────────────
# Мастер — на Synology; правит страница через /api/fd/*. rsync затёр бы правки,
# поэтому здесь ровно та же логика, что у health: есть файл — не касаемся.
FOOD_DST="$SYN/Claude-Memory/Food"
# recipes/ — каталог, а не файл: с 2026-07-20 один рецепт = один файл.
# Пустой recipes.json здесь создавать НЕЛЬЗЯ — он стал бы вторым местом правды
# рядом с каталогом, а сайдкар его больше не принимает на запись.
mkdir -p "$FOOD_DST/inbox" "$FOOD_DST/recipes"
for f in products shopping; do
  [[ -f "$FOOD_DST/$f.json" ]] && continue
  # ключ массива у shopping не совпадает с именем файла — как и в валидаторе сайдкара
  case $f in
    shopping) key="items" ;;
    *)        key="$f" ;;
  esac
  printf '{\n  "schema": "food-%s@1",\n  "updated": "%s",\n  "%s": []\n}\n' \
    "$f" "$(date +%Y-%m-%d)" "$key" > "$FOOD_DST/$f.json"
  echo "✓ Food/$f.json (пустой каркас)"
done

# ── Файлы для NAS: кладём в синхронизируемую папку ──────────────────────────
# Caddyfile / docker-compose.yml / api/server.py — конфиги живого стека, и
# лежат они ровно здесь, в Claude-Memory/_nas/: docker-проект собран из этой
# папки (`com.docker.compose.project.working_dir`). То есть rsync ниже И ЕСТЬ
# деплой конфигов, копировать их на NAS больше никуда не надо — остаётся только
# перезапуск.
#
# Так было не всегда. Раньше документация требовала `sudo cp` в
# /volume1/docker/portfolio-viewer/, и этот шаг «забывался» — на деле он был
# лишним с самого начала: копии уезжали в папку, из которой стек не собирался
# (её api/server.py простоял устаревшим три недели, пока все считали его живым).
# Проверка 2026-09-03 это вскрыла; стек оставлен в _nas/ намеренно.
#
# Плата за автоматизм: конфиги лежат в синхронизируемой папке, и Synology Drive
# способен переписать их под работающим стеком. Это принято сознательно —
# альтернатива требует ручного шага, который систематически пропускается.
#
# В Caddyfile лежит bcrypt-хэш пароля; дерево вне облачных синков — наружу
# он не уезжает.
mkdir -p "$NAS_STAGE/api" "$NAS_STAGE/notify"
# Сторож (2026-10-23): рабочий Caddyfile живёт только на Маке (gitignored), и deploy им ПЕРЕЗАПИСЫВАЕТ
# копию на NAS. Без запрета _nas/ (.env с паролем DSM) он вернул бы дыру, закрытую на NAS руками, —
# поэтому такой Caddyfile не выкладывается вовсе.
if grep -q '^ *@internal path /_nas /_nas/\*' "$REPO_HOSTING/Caddyfile" && grep -q 'respond @internal 404' "$REPO_HOSTING/Caddyfile"; then
  rsync -c "$REPO_HOSTING/Caddyfile" "$NAS_STAGE/Caddyfile" && echo "✓ _nas/Caddyfile"
else
  echo "✗ _nas/Caddyfile НЕ выложен: в tools/hosting/Caddyfile нет запрета _nas/ (@internal + respond @internal 404)."
  echo "  Перенеси блок «Служебное» и строку «0)» в route из Caddyfile.example — иначе сайт отдаёт _nas/.env с паролем DSM."
fi
rsync -c "$REPO_HOSTING/docker-compose.yml" "$NAS_STAGE/docker-compose.yml" && echo "✓ _nas/docker-compose.yml"
rsync -c "$REPO_HOSTING/api/server.py" "$NAS_STAGE/api/server.py" && echo "✓ _nas/api/server.py"
for f in notifier.py jobs.py eshop.py eshop_lookup.py macro_job.py prices_job.py pf_build.py stress_job.py decision_job.py condition_job.py codehash.py zm_csv.py zm_checks.py zm_stmt.py; do
  rsync -c "$REPO_HOSTING/notify/$f" "$NAS_STAGE/notify/$f" && echo "✓ _nas/notify/$f"
done
# кодлисты (_shared-references/codelists.json, schema.md §3.4) — рядом с server.py (compose монтирует в /app hub-api);
# hub-notify берёт их из pdl/_shared-references (ниже, вместе с модулем условий); страница — assets/codelists.js
for d in api; do
  rsync -c "$REPO_TOOLS/../_shared-references/codelists.json" "$NAS_STAGE/$d/codelists.json" && echo "✓ _nas/$d/codelists.json"
done
# правила записи со страницы «Здоровье» (отчёт .md, справка маркера) — модули скилла health-labs, одна реализация;
# compose монтирует их в /app hub-api; hub_settings.py — их зависимость
for f in validate_report.py validate_labs_info.py labs_rules.py; do
  rsync -c "$REPO_TOOLS/../skills/health-labs/scripts/$f" "$NAS_STAGE/api/$f" && echo "✓ _nas/api/$f"
done
rsync -c "$REPO_TOOLS/../_shared-references/hub_settings.py" "$NAS_STAGE/api/hub_settings.py" && echo "✓ _nas/api/hub_settings.py"
# макросрез сайта — та же реализация, что у скилла macro-ru-watcher (одна копия кода)
mkdir -p "$NAS_STAGE/notify/macro"
for f in build_macro.py fetch_macro.py; do
  rsync -c "$REPO_TOOLS/../skills/macro-ru-watcher/scripts/$f" "$NAS_STAGE/notify/macro/$f" && echo "✓ _nas/notify/macro/$f"
done
# колёса зависимостей hub-notify (холодный старт без PyPI): версии — из строки command docker-compose.yml,
# платформа контейнера python:3.12-alpine — musllinux; архитектура NAS — WHEEL_PLATFORM (x86_64 по умолчанию,
# для ARM-NAS: WHEEL_PLATFORM=musllinux_1_2_aarch64). Нет pip3 или сети — шаг пропускается, контейнер возьмёт PyPI.
WHEEL_PLATFORM="${WHEEL_PLATFORM:-musllinux_1_2_x86_64}"
WHEEL_PKGS=$(grep -o 'cryptography==[^ ]* pyyaml==[^ ]* openpyxl==[^ ]* numbers-parser==[^ "]*' "$REPO_HOSTING/docker-compose.yml" | head -1)
if [[ -n "$WHEEL_PKGS" ]] && command -v pip3 >/dev/null 2>&1; then
  mkdir -p "$NAS_STAGE/wheels"
  if pip3 download -q -d "$NAS_STAGE/wheels" --only-binary=:all: --platform "$WHEEL_PLATFORM" --python-version 3.12 \
       --implementation cp ${=WHEEL_PKGS} >/dev/null 2>&1; then
    echo "✓ _nas/wheels/ ($WHEEL_PLATFORM): $WHEEL_PKGS"
  else
    echo "⚠ _nas/wheels/ не обновлены (pip3 download не прошёл) — контейнер поставит зависимости с PyPI"
  fi
fi
# сборка снапшота с вьюера (pf_build.py, пробный режим) — скрипты portfolio-data-loader с раскладкой
# репозитория: build_snapshot.py / iis_returns.py ищут _shared-references на 2–3 уровня выше себя
PDL_STAGE="$NAS_STAGE/notify/pdl"
mkdir -p "$PDL_STAGE/skills/portfolio-data-loader/scripts" "$PDL_STAGE/_shared-references"
# Списком, без фильтров rsync: openrsync на macOS отвергает `--delete` без `-r` («--delete does not
# work without --recursive»), шаг молча не выполнился и на NAS уехала пустая папка — «Собрать снапшот»
# падал с «can't open build_snapshot.py» (2026-10-21).
pdl_n=0
for f in "$REPO_TOOLS"/../skills/portfolio-data-loader/scripts/*.py; do
  rsync -c "$f" "$PDL_STAGE/skills/portfolio-data-loader/scripts/" && pdl_n=$((pdl_n + 1))
done
# справочник бумаг: pf_build.save добавляет новые ключи тем же писателем, что и скилл (security_attrs.add_missing);
# модуль берёт codelists/ds_schemas/time_msk из pdl/_shared-references (выше и ниже)
mkdir -p "$PDL_STAGE/skills/save-to-library/scripts"
rsync -c "$REPO_TOOLS/../skills/save-to-library/scripts/security_attrs.py" "$PDL_STAGE/skills/save-to-library/scripts/" \
  && echo "✓ _nas/notify/pdl/skills/save-to-library/scripts/security_attrs.py"
# известные расхождения паритета «без баланса ↔ с балансом» (build_snapshot.py читает references/ рядом со scripts/):
# без файла сверка в контейнере сочла бы расхождением каждое законное различие
mkdir -p "$PDL_STAGE/skills/portfolio-data-loader/references"
rsync -c "$REPO_TOOLS/../skills/portfolio-data-loader/references/parity-known-diffs-nobalance.yaml" \
  "$PDL_STAGE/skills/portfolio-data-loader/references/" && pdl_n=$((pdl_n + 1))
if [[ -f "$PDL_STAGE/skills/portfolio-data-loader/scripts/build_snapshot.py" ]]; then
  echo "✓ _nas/notify/pdl/ (скрипты portfolio-data-loader: $pdl_n)"
else
  echo "✗ _nas/notify/pdl/: build_snapshot.py не скопирован — «Собрать снапшот» на сайте не заработает"
fi
rsync -c "$REPO_TOOLS/../_shared-references/moex_quotes.py" "$PDL_STAGE/_shared-references/moex_quotes.py" \
  && echo "✓ _nas/notify/pdl/_shared-references/moex_quotes.py"
# журнал решений (decision_journal.py) читает кодлисты через загрузчик из _shared-references
for f in codelists.py codelists.json; do
  rsync -c "$REPO_TOOLS/../_shared-references/$f" "$PDL_STAGE/_shared-references/$f" \
    && echo "✓ _nas/notify/pdl/_shared-references/$f"
done
# assemble_snapshot / build_snapshot / security_types берут время МСК из time_msk.py
rsync -c "$REPO_TOOLS/../_shared-references/time_msk.py" "$PDL_STAGE/_shared-references/time_msk.py" \
  && echo "✓ _nas/notify/pdl/_shared-references/time_msk.py"
# уведомитель (notifier.py) читает условия только модулем (а) conditions_merge.py (+ валидаторы ds_schemas.py,
# кодлисты и время — выше); каталог ищет _shared_dir(): pdl/_shared-references, иначе _shared-references репозитория
for f in conditions_merge.py ds_schemas.py; do
  rsync -c "$REPO_TOOLS/../_shared-references/$f" "$PDL_STAGE/_shared-references/$f" \
    && echo "✓ _nas/notify/pdl/_shared-references/$f"
done
# флаг режима «с ИИ / без ИИ»: build_snapshot.py (сборка снапшота на сайте) импортирует hub_settings.py
rsync -c "$REPO_TOOLS/../_shared-references/hub_settings.py" "$PDL_STAGE/_shared-references/hub_settings.py" \
  && echo "✓ _nas/notify/pdl/_shared-references/hub_settings.py"
# пересчёт стресса с сайта (stress_job.py → stress_recalc.py): расчётные скрипты portfolio-scenario-stress с той же
# раскладкой репозитория (зависят только друг от друга и stdlib/PyYAML, из references/ читают sector-groups.yaml);
# веса сценариев по осям — _shared-references/scenario_axis_weights.py (stdlib)
mkdir -p "$PDL_STAGE/skills/portfolio-scenario-stress/scripts"
pss_n=0
for f in "$REPO_TOOLS"/../skills/portfolio-scenario-stress/scripts/*.py; do
  rsync -c "$f" "$PDL_STAGE/skills/portfolio-scenario-stress/scripts/" && pss_n=$((pss_n + 1))
done
# таблица секторных групп (compute_derived_fields.py читает references/ рядом со scripts/)
mkdir -p "$PDL_STAGE/skills/portfolio-scenario-stress/references"
rsync -c "$REPO_TOOLS/../skills/portfolio-scenario-stress/references/sector-groups.yaml" \
  "$PDL_STAGE/skills/portfolio-scenario-stress/references/" && pss_n=$((pss_n + 1))
if [[ -f "$PDL_STAGE/skills/portfolio-scenario-stress/scripts/stress_recalc.py" ]]; then
  echo "✓ _nas/notify/pdl/ (скрипты portfolio-scenario-stress: $pss_n)"
else
  echo "✗ _nas/notify/pdl/: stress_recalc.py не скопирован — пересчёт стресса на сайте не заработает"
fi
rsync -c "$REPO_TOOLS/../_shared-references/scenario_axis_weights.py" "$PDL_STAGE/_shared-references/scenario_axis_weights.py" \
  && echo "✓ _nas/notify/pdl/_shared-references/scenario_axis_weights.py" \
  || echo "✗ scenario_axis_weights.py не выложен — веса сценариев с сайта не заработают"
# compute_horizon_factors.py (его зовёт stress_build.py) проверяет макро-файл общим модулем macro_grid_check.py
rsync -c "$REPO_TOOLS/../_shared-references/macro_grid_check.py" "$PDL_STAGE/_shared-references/macro_grid_check.py" \
  && echo "✓ _nas/notify/pdl/_shared-references/macro_grid_check.py" \
  || echo "✗ macro_grid_check.py не выложен — пересчёт стресса с сайта не заработает"
# выгрузка CSV ZenMoney на сайте (notify/zm_csv.py): расчёт месяцев и поездок скриптами скилла zenmoney-analyst и разбором CSV
# с раскладкой репозитория (pdl/skills/zenmoney-analyst/scripts/, pdl/tools/). Отдельными строками: цикл conditions_merge/ds_schemas выше не трогаем
mkdir -p "$PDL_STAGE/skills/zenmoney-analyst/scripts" "$PDL_STAGE/tools"
zm_n=0
rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/audit_month.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/month_stats.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/trip_stats.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/audit_history.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/history_query.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
rsync -c "$REPO_TOOLS/zenmoney_payee_map.py" "$PDL_STAGE/tools/" && zm_n=$((zm_n + 1))
# разбор CSV → операции формата MCP (build, rates_for, diff_month): его импортирует zm_csv.py
rsync -c "$REPO_TOOLS/zenmoney_csv_backfill.py" "$PDL_STAGE/tools/" && zm_n=$((zm_n + 1))
# сверка выписки банка (notify/zm_stmt.py, задача 3.8): те же скрипты скилла, что в режимах E/F, — одна реализация без копий логики
# сайт разбирает только Райффайзенбанк (CSV) и BOG (XLSX): парсеры FF и Т-Банка (PDF) не выкладываем — stmt_import грузит парсер банка лениво
for f in stmt_import stmt_compare stmt_accounts parse_bog_statement parse_raif_statement bog_normalize raif_normalize; do
  rsync -c "$REPO_TOOLS/../skills/zenmoney-analyst/scripts/$f.py" "$PDL_STAGE/skills/zenmoney-analyst/scripts/" && zm_n=$((zm_n + 1))
done
if [[ $zm_n -eq 14 ]]; then
  echo "✓ _nas/notify/pdl/ (скрипты zenmoney-analyst, разбор CSV и выписок для «Денег» на сайте: $zm_n)"
else
  echo "✗ _nas/notify/pdl/: скрипты выгрузки CSV ZenMoney скопированы не все ($zm_n из 14) — «Деньги → Выгрузка» и «Выписка» на сайте не заработают"
fi
# журнал решений (decision_journal.py, шаг 13) читает решения модулем decisions_read.py, который тянет модуль (б)
# last_word.py (+ conditions_merge/ds_schemas/codelists/time_msk — выше)
for f in decisions_read.py last_word.py; do
  rsync -c "$REPO_TOOLS/../_shared-references/$f" "$PDL_STAGE/_shared-references/$f" \
    && echo "✓ _nas/notify/pdl/_shared-references/$f"
done
# решение владельца с сайта (notify/decision_job.py → POST /api/pf/decision): сборка записи — decision_write.build_owner
# (тот же код, что CLI `owner`); тянет hub_settings/decisions_read/ds_schemas/conditions_merge/time_msk/codelists — выше
rsync -c "$REPO_TOOLS/../skills/save-to-library/scripts/decision_write.py" "$PDL_STAGE/skills/save-to-library/scripts/" \
  && echo "✓ _nas/notify/pdl/skills/save-to-library/scripts/decision_write.py" \
  || echo "✗ decision_write.py не выложен — «Подтверждаю держать» / «Проверить качество» на сайте не заработают"
# условие владельца с сайта (notify/condition_job.py → POST /api/pf/condition): тот же писатель, что у скилла —
# apply_condition.py add|withdraw --emit; тянет conditions_merge/decisions_read/ds_schemas/codelists/time_msk/hub_settings — выше
rsync -c "$REPO_TOOLS/../skills/save-to-library/scripts/apply_condition.py" "$PDL_STAGE/skills/save-to-library/scripts/" \
  && echo "✓ _nas/notify/pdl/skills/save-to-library/scripts/apply_condition.py" \
  || echo "✗ apply_condition.py не выложен — «Новое условие» на сайте не заработает"

# ── Проверка NAS: файлы, которые этот скрипт НЕ выкладывает ─────────────────
else
  echo "· --check: копирование пропущено, проверяю NAS"
fi   # конец копирования (CHECK_ONLY)

# Caddyfile / docker-compose.yml / api/server.py живут на NAS и копируются
# руками. Забыть их — типовая ошибка с ОБМАНЧИВЫМИ симптомами, поэтому
# спрашиваем не «скопировал ли ты», а сам сервер:
#   старый Caddyfile     → login.html под паролем → нативный попап;
#   старый api/server.py → аптечка/прививки пустые (404 на /api/hd/*);
#   старый compose       → нет тома здоровья (404 на /health-data/*).
code(){ curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$1" 2>/dev/null || echo 000 }

# Адрес NAS зависит от того, ГДЕ сейчас Мак, поэтому прибивать один нельзя:
# дома идём в LAN напрямую, из поездки и по VPN — через DSM reverse proxy
# (443 → localhost:8080; порт 8080 наружу не проброшен). Прибитый LAN-адрес
# пережил переезд NAS в другую подсеть незамеченным: проверки ниже молча
# пропускались, а вместе с ними — вся защита от протухших конфигов на NAS.
# mDNS-имени (*.local) в списке нет намеренно: через маршрутизатор оно не ходит,
# а Мак бывает в соседней подсети.
NAS_CANDIDATES=(
  "http://192.168.1.10:8080"                # дома и в соседней подсети
  "https://hub.example.com"    # снаружи и по VPN (DSM 443 → :8080)
)
# Скрипт под `set -u`: незаданную NAS_URL читаем только через :- подстановку.
if [[ -n "${NAS_URL:-}" ]]; then
  NAS_CANDIDATES=("$NAS_URL")                # явный адрес перебивает автоподбор
fi
NAS_URL=""
for cand in "${NAS_CANDIDATES[@]}"; do
  if [[ "$(code "$cand/tools/hub.html")" == "200" ]]; then NAS_URL="$cand"; break; fi
done

echo
if [[ -z "$NAS_URL" ]]; then
  echo "· NAS не отвечает ни по одному адресу — проверку его конфигов пропускаю."
  for cand in "${NAS_CANDIDATES[@]}"; do echo "    пробовал: $cand"; done
  echo "  (другой адрес: NAS_URL=http://… zsh deploy.zsh)"
else
  echo "· NAS отвечает по $NAS_URL"
  stale=0
  # login.html — индикатор свежести Caddyfile, но коды означают РАЗНОЕ:
  #   401 = конфиг старый (страницы нет в публичном списке → challenge → попап);
  #   404 = конфиг новый, а файла на NAS ещё нет (Synology Drive не досинкал);
  #   200 = всё на месте.
  # Каждая ПУБЛИЧНАЯ страница обязана открываться без пароля. Канарейка на одной
  # login.html этого не ловила: она отвечала 200 со старым конфигом, деплой
  # рапортовал «всё хорошо», а food.html отдавал 403 — то есть БЕЛЫЙ ЭКРАН
  # (тихий 403 отдаётся с пустым телом, отличить его от сломанной страницы
  # нельзя). Реальный случай 2026-07-20. Проверяем ВСЕ публичные пути, а не
  # одну избранную страницу: список растёт вместе с разделами.
  # ⚠ SYNC: список обязан совпадать с публичными `/tools/*.html` из обоих
  # матчеров `not path` в Caddyfile — это сверяется тестом test_caddy_zones.py.
  PUBLIC=(tools/hub.html tools/travel.html tools/games.html tools/food.html tools/money.html
          tools/health.html tools/login.html tools/portfolio-integrated-viewer.html tools/portfolio-sw.js
          tools/sw.js tools/sw-offline.js
          Food/products.json Food/shopping.json Food/recipes/)
  missing_zone=(); missing_file=()
  for p in "${PUBLIC[@]}"; do
    pc=$(code "$NAS_URL/$p")
    case "$pc" in
      403|401) missing_zone+=("$p → $pc") ;;
      404)     missing_file+=("$p → 404") ;;
    esac
  done
  if (( ${#missing_zone[@]} )); then
    echo "⚠  Caddyfile на NAS УСТАРЕЛ: публичные пути требуют пароль."
    for m in "${missing_zone[@]}"; do echo "     $m"; done
    echo "   Симптом: БЕЛЫЙ ЭКРАН (тихий 403 отдаётся с пустым телом)."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart portfolio-viewer   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # 404 на публичном пути означает другое: конфиг свежий, а файла за ним нет.
  # Для /Food/* это почти всегда несмонтированный том — «Еда» переехала в
  # несинхронизируемое дерево и отдаётся с отдельного тома /srv-food.
  # Не отличать 404 от 403 нельзя: команды на NAS для них РАЗНЫЕ, а деплой
  # рапортовал «всё актуально», пока данные раздела не отдавались вовсе.
  if (( ${#missing_file[@]} )); then
    echo "⚠  Публичный путь есть в конфиге, но файла за ним нет:"
    for m in "${missing_file[@]}"; do echo "     $m"; done
    echo "   Для /Food/* это несмонтированный том (нужен /srv-food)."
    echo "   → НА NAS одной командой:"
    echo "     cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d"
    echo "     (именно up -d — restart новый том не подхватит)"
    stale=1
  fi

  # Обратная проверка: личные финансы обязаны быть ЗАКРЫТЫ. money.html публичен
  # (оболочка), а её данные /ZenMoney/* — только с паролем. Без Authorization
  # должно быть 403 (404 — файла ещё нет, тоже не утечка). 200 = данные видны
  # всем: путь случайно попал в публичные исключения Caddyfile.
  zc=$(code "$NAS_URL/ZenMoney/audit/history.json")
  if [[ "$zc" == "200" ]]; then
    echo "❌ /ZenMoney/audit/history.json отдаётся БЕЗ ПАРОЛЯ — финансы открыты."
    echo "   Проверьте списки not path в Caddyfile: /ZenMoney/* в них быть не должно."
    stale=1
  fi

  # выгрузка CSV ZenMoney (последняя записанная — вся история операций): тоже только с паролем
  zc=$(code "$NAS_URL/ZenMoney/csv/last.csv")
  if [[ "$zc" == "200" ]]; then
    echo "❌ /ZenMoney/csv/last.csv отдаётся БЕЗ ПАРОЛЯ — выгрузка операций открыта."
    echo "   Проверьте списки not path в Caddyfile: /ZenMoney/* в них быть не должно."
    stale=1
  fi
  c=$(code "$NAS_URL/tools/login.html")
  if [[ "$c" == "401" ]]; then
    echo "⚠  Caddyfile на NAS УСТАРЕЛ (login.html → 401: страница под паролем)."
    echo "   Симптом: нативный попап пароля вместо страницы входа."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart portfolio-viewer   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  elif [[ "$c" == "404" ]]; then
    echo "· login.html ещё не доехал на NAS (404). Caddyfile при этом свежий."
    echo "  Подождите синхронизацию Synology Drive («Up to date» в меню-баре) и повторите."
    stale=1
  elif [[ "$c" != "200" ]]; then
    echo "⚠  login.html → $c (ожидалось 200) — разбирайтесь по коду."
    stale=1
  fi
  # Сайдкар сам объявляет, какие живые файлы умеет (health_files). Сверяем с
  # тем, что ждёт репозиторий: иначе рассинхрон версий вылезет 403-ей на
  # странице, а не здесь (реальный случай: страница просила studies.json,
  # сайдкар о нём не знал).
  # ⚠ Сначала КОД, потом тело. `/api/health` — приватная зона: с ВНЕШНЕГО адреса
  # (DSM 443 → :8080) он закрыт Basic Auth и отдаёт 401 вообще без JSON. Раньше
  # тело читалось без проверки кода, и 401 выглядел как «сайдкар не сообщает ни
  # одного флага» → семь ложных тревог подряд про древний server.py, который на
  # деле свежий (реальный случай 2026-09-03). Версию судим ТОЛЬКО по живому 200.
  api_code=$(code "$NAS_URL/api/health")
  api_json=$(curl -s --max-time 3 "$NAS_URL/api/health" 2>/dev/null || true)
  api_ok=1
  if [[ "$api_code" != "200" ]]; then
    api_ok=0
    echo "· /api/health → $api_code: версию api/server.py с этого адреса не проверить."
    if [[ "$api_code" == "401" || "$api_code" == "403" ]]; then
      echo "  Это штатно: приватная зона закрыта паролем с внешнего входа."
      echo "  Полная проверка — из домашней сети: NAS_URL=http://192.168.1.10:8080 zsh tools/deploy.zsh"
    fi
  fi
  # Единая точка «флага нет»: при недоступном /api/health молчит, а не обвиняет.
  lacks(){ (( api_ok )) && [[ "$api_json" != *"$1"* ]] }
  want=$(grep -o 'HEALTH_FILES = (\([^)]*\))' "$REPO_HOSTING/api/server.py" | grep -o '"[a-z]*"' | tr -d '"' | sort | tr '\n' ' ')
  if (( ! api_ok )); then
    :                                    # причину уже объяснили выше — молчим
  elif [[ "$api_json" != *health_writable* ]]; then
    echo "⚠  api/server.py на NAS УСТАРЕЛ (в /api/health нет health_writable)."
    echo "   Симптом: аптечка, прививки и вес пустые."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  elif [[ "$api_json" != *health_files* ]]; then
    echo "⚠  api/server.py на NAS СТАРЕЕ репозитория (не сообщает health_files)."
    echo "   Симптом: вкладка «Исследования» пуста + баннер про 403 на странице."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    echo "   Проверить, что доехало: sudo docker exec hub-api grep -c health_files /app/server.py"
    stale=1
  else
    for f in ${=want}; do
      if [[ "$api_json" != *"\"$f\""* ]]; then
        echo "⚠  api/server.py на NAS СТАРЕЕ репозитория: не знает про «$f.json»."
        echo "   Симптом: вкладка пустая + баннер «часть живых данных не загрузилась (403)»."
        echo "   → НА NAS одной командой:"
        echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
        stale=1
        break
      fi
    done
  fi
  # Запись со страницы «Здоровье» (отчёт .md, справка маркера, файл исследования). Модули health-labs лежат в
  # compose отдельными томами: новая строка тома требует `docker compose up -d hub-api` (restart не хватит).
  if lacks health_upload; then
    echo "⚠  api/server.py на NAS не умеет принимать отчёты, справку маркера и файлы исследований (нет health_upload)."
    echo "   → НА NAS: cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d hub-api   # compose с новыми томами validate_*.py"
    stale=1
  elif [[ "$api_json" == *'"health_report": false'* || "$api_json" == *'"health_marker_info": false'* || "$api_json" == *'"health_labs_manual": false'* ]]; then
    echo "⚠  hub-api не видит модули health-labs (validate_report.py / validate_labs_info.py / labs_rules.py не смонтированы)."
    echo "   → НА NAS: cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d hub-api   # пересоздать контейнер с новым compose"
    stale=1
  fi
  # «Еда» переехала на свой корень /srv-food (2026-07-20), и вместе с корнем
  # сменился путь в запросе: «recipes.json» вместо «Food/recipes.json».
  # Рассинхрон тут особенно коварен: страница уже шлёт новый путь, старый
  # сайдкар отвечает 403, и это неотличимо от «нет прав» — список открывается,
  # но галочка «куплено» молча не сохраняется. Маркер нового сайдкара —
  # food_writable в /api/health.
  # Рецепты разделены по файлам (2026-07-20): старый сайдкар пускает только
  # общий recipes.json, которого больше нет, и отклоняет recipes/<id>.json.
  # Симптом обманчив: библиотека ЧИТАЕТСЯ (каталог отдаёт Caddy), а любая
  # правка рецепта молча отлетает 403.
  if lacks food_recipe_dir; then
    echo "⚠  api/server.py на NAS не знает про рецепты по файлам (нет food_recipe_dir)."
    echo "   Симптом: рецепты открываются, но правки НЕ сохраняются."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # Создание новых файлов (base_hash=null) — нужно редактору, чтобы сохранить
  # НОВЫЙ рецепт. Старый сайдкар требует хэш и отвечает «bad request body».
  if lacks food_create; then
    echo "⚠  api/server.py на NAS не умеет создавать новые файлы (нет food_create)."
    echo "   Симптом: правка рецепта работает, а «Новый рецепт» не сохраняется."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # id рецепта стал опциональным (идентичность = имя файла). Страница теперь
  # сохраняет рецепты БЕЗ поля id — старый сайдкар их отклонит («id — непустая
  # строка»), и ЛЮБАЯ правка рецепта перестанет сохраняться.
  if lacks food_id_optional; then
    echo "⚠  api/server.py на NAS требует поле id в рецепте (нет food_id_optional)."
    echo "   Симптом: правка ЛЮБОГО рецепта не сохраняется — «id не прошёл проверку»."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # Удаление рецепта (POST /api/fd/delete, 2026-08-09). Симптом отсутствия
  # мягкий и легко списывается на «так задумано»: кнопки удаления на странице
  # просто НЕТ — она рисуется по признаку food_delete, чтобы «старый сайдкар»
  # не выглядел как «нет прав» (оба ответили бы 40x).
  if lacks food_delete; then
    echo "⚠  api/server.py на NAS не умеет удалять рецепты (нет food_delete)."
    echo "   Симптом: в редакторе рецепта нет кнопки «Удалить рецепт»."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # Задачи сайта (цены eShop, макросрез; 2026-10-21): без зоны /api/job/* hub-notify
  # не может ни записать результат, ни дописать журнал — тихо, только stdout контейнера.
  if lacks site_jobs; then
    echo "⚠  api/server.py на NAS не знает про задачи сайта (нет site_jobs)."
    echo "   Симптом: цены eShop и автоматический макросрез не появляются, «Обновить цены» — 404."
    echo "   Симптом на странице: «не получилось: unknown endpoint»."
    echo "   → НА NAS: cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d && sudo docker restart hub-api"
    echo "     (compose сменился: hub-notify монтирует папку notify/ целиком; hub-api compose"
    echo "      не пересоздаёт — его определение не менялось, новый server.py подхватит только restart)"
    stale=1
  fi
  # Сборка снапшота с вьюера (2026-10-21): hub-api должен пускать запись в Portfolio/snapshots/auto/,
  # hub-notify — иметь openpyxl и numbers-parser (новая метка тома зависимостей в compose).
  if lacks pf_auto; then
    echo "⚠  api/server.py на NAS не знает пробную папку снапшотов (нет pf_auto)."
    echo "   Симптом: «Собрать снапшот» собирает, но «Сохранить» отвечает ошибкой записи."
    echo "   → НА NAS: cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d && sudo docker restart hub-api portfolio-viewer"
    echo "     (compose: hub-notify ставит openpyxl и numbers-parser — первый старт дольше обычного;"
    echo "      portfolio-viewer — Caddyfile: /api/pf/* под паролем в hub-notify)"
    stale=1
  fi
  # маршруты /api/zm/*: без флага zm_csv hub-api на NAS не знает выгрузку CSV
  if lacks zm_csv; then
    echo "⚠  api/server.py на NAS не знает выгрузку CSV ZenMoney (нет zm_csv)."
    echo "   Симптом: «Деньги → Выгрузка» отвечает «unknown endpoint»."
    echo "   → НА NAS: sudo docker restart hub-api hub-notify   # файлы уже на месте: rsync положил их в _nas/"
    echo "     (Caddyfile: /api/zm/* — в not path у @api_trusted, как /api/gm/*; сверить с Caddyfile.example)"
    stale=1
  fi
  if lacks food_writable; then
    echo "⚠  api/server.py на NAS не знает про новый корень «Еды» (нет food_writable)."
    echo "   Симптом: список открывается, но правки НЕ сохраняются (403 на /api/fd/*)."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # То же для «Еды». Проверка здоровья выше была написана под здоровье и про
  # food_files не знала — а страница без них уходит в режим «только просмотр»
  # и молча не даёт отмечать покупки.
  if lacks food_files; then
    echo "⚠  api/server.py на NAS не знает про раздел «Еда» (нет food_files)."
    echo "   Симптом: на странице баннер «сайдкар старее страницы», правки недоступны."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # Вьюер одним запросом (2026-10-23): без pv_sync вьюер работает по-старому (листинги), только медленнее.
  if lacks pv_sync; then
    echo "⚠  api/server.py на NAS без /api/pv/sync (вьюер одним запросом) — вьюер грузится листингами."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart hub-api   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # hub-notify (2026-10-26): раньше деплой его не проверял вовсе — новые файлы ложились в _nas/notify/,
  # а контейнер работал на старых, и новых уведомлений просто не было. hub-notify считает отпечаток
  # своего кода при старте (codehash.py), hub-api отдаёт его в /api/health; сверяем с _nas/notify/.
  if (( api_ok )); then
    if lacks '"notify"'; then
      : # старый hub-api — про него уже сказано выше (pv_sync и др.) или скажет следующий деплой
    else
      nf_have=$(print -r -- "$api_json" | python3 -c 'import json,sys; n=json.load(sys.stdin).get("notify"); print((n or {}).get("code") or ("none" if n is None else "old"))' 2>/dev/null)
      nf_want=$(python3 "$REPO_HOSTING/notify/codehash.py" "$NAS_STAGE/notify" 2>/dev/null)
      if [[ "$nf_have" == "none" ]]; then
        echo "⚠  hub-notify не отвечает hub-api: уведомления и задачи сайта (цены eShop, макросрез) стоят."
        echo "   → НА NAS: sudo docker logs --tail 30 hub-notify ; sudo docker restart hub-notify"
        stale=1
      elif [[ -n "$nf_want" && "$nf_have" != "$nf_want" ]]; then
        echo "⚠  hub-notify работает на СТАРОМ коде (уведомления, цены eShop, макросрез)."
        echo "   → НА NAS одной командой (после того как Synology Drive довёз _nas/notify/):"
        echo "     sudo docker restart hub-notify"
        stale=1
      fi
    fi
  fi
  # hub-api (2026-11-07): тот же приём, что для hub-notify, — процесс отдаёт отпечаток своего server.py в
  # /api/health (api.code), сверяем с разложенным _nas/api/server.py. До этого устаревший hub-api ловился
  # только по известным флагам возможностей, и новый список разрешённых путей (файл сроков) прошёл мимо.
  if (( api_ok )) && ! lacks '"api"'; then
    ac_have=$(print -r -- "$api_json" | python3 -c 'import json,sys; print(((json.load(sys.stdin).get("api") or {}).get("code")) or "none")' 2>/dev/null)
    ac_want=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:16])' "$NAS_STAGE/api/server.py" 2>/dev/null)
    if [[ -n "$ac_want" && "$ac_have" != "none" && "$ac_have" != "$ac_want" ]]; then
      echo "⚠  hub-api работает на СТАРОМ server.py (отпечаток $ac_have, в _nas/api/ — $ac_want)."
      echo "   Симптом: запись с сайта отвечает «path not in whitelist», новых маршрутов нет."
      echo "   → НА NAS одной командой (после того как Synology Drive довёз _nas/api/server.py):"
      echo "     sudo docker restart hub-api"
      stale=1
    fi
  fi
  # Сбой File Station (2026-10-23): правка с сайта записана локально и в зеркало на Маке не уедет,
  # пока Drive не перечитает папку (случай 2026-09-02: 13 дней правок мимо зеркал → затёрта аптечка).
  fsfb=$(print -r -- "$api_json" | grep -o '"fs_fallbacks": *[0-9]*' | grep -o '[0-9]*$')
  if [[ -n "$fsfb" && "$fsfb" != "0" ]]; then
    echo "⚠  Сайдкар $fsfb раз(а) писал мимо File Station — эти правки сайта могут не доехать до Мака."
    echo "   Посмотреть: sudo docker logs hub-api 2>&1 | grep fs-move | tail"
    echo "   Проверить учётку DSM в _nas/.env (HUB_API_DSM_*), затем sudo docker restart hub-api."
    stale=1
  fi
  # _nas/ (стек, .env с паролем DSM): новый Caddy — 404 всем; 403 без пароля = Caddy со старым конфигом
  n=$(code "$NAS_URL/_nas/Caddyfile")
  if [[ "$n" != "404" && "$n" != "000" ]]; then
    echo "⚠  Caddy отдаёт _nas/ не 404 (получено $n) — работает старый Caddyfile без запрета служебного."
    echo "   → НА NAS одной командой:"
    echo "     sudo docker restart portfolio-viewer   # файл уже на месте: rsync положил его в _nas/"
    stale=1
  fi
  # 403/200 = том на месте (403 — штатный отказ без токена).
  # 401 = старый Caddyfile (уже сказали выше) — про том судить нельзя, молчим.
  # 404 = Caddy свежий, а тома нет.
  h=$(code "$NAS_URL/health-data/labs.json")
  if [[ "$h" == "404" ]]; then
    echo "⚠  Том здоровья не смонтирован (health-data/labs.json → 404)."
    echo "   → НА NAS одной командой:"
    echo "     cd /volume1/homes/hubuser/Claude-Memory/_nas && sudo docker compose up -d"
    echo "     (именно up -d — restart не подхватит новый том)"
    stale=1
  fi
  [[ $stale -eq 0 ]] && echo "✓ NAS: Caddyfile, hub-api, hub-notify и том здоровья — отвечают и на коде из репозитория."
  if (( ! CHECK_ONLY )) && [[ $stale -ne 0 ]]; then
    echo "   После команд на NAS проверь, что всё поднялось: zsh tools/deploy.zsh --check"
  fi
fi

echo "Готово: $(date '+%Y-%m-%d %H:%M')"
