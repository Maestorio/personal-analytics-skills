#!/usr/bin/env python3
"""
Тест зон доступа Caddy (tools/hosting/Caddyfile) — поднимает НАСТОЯЩИЙ caddy на
эфемерном порту с реальным конфигом (подменены только пути, порт и хэш).

Зачем: зоны — это не документация, а поведение, и раньше его никто не проверял.
Реальный баг 2026-07-17: анти-попапные матчеры опознавали фоновый запрос по
заголовкам (Sec-Fetch-Dest / Accept: application/json), но браузер НЕ шлёт
Sec-Fetch-* по простому http:// (LAN-адрес — не secure context). Любой
приватный запрос без Accept:json проваливался в basic_auth → 401 +
WWW-Authenticate → нативное окно пароля поверх публичного хаба. Теперь правило
header-агностично, и этот тест держит его: WWW-Authenticate не должен уходить
НИКОГДА, кроме случая явно неверного токена.

Запуск:
    python3 tools/tests/test_caddy_zones.py
Требует caddy в PATH (brew install caddy). Без него — пропуск (exit 0).
"""
import base64
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CADDYFILE = REPO / "tools/hosting/Caddyfile"

passed = 0
failed = 0


def check(name: str, cond: bool) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


caddy = shutil.which("caddy") or shutil.which("/opt/homebrew/bin/caddy")
if not caddy:
    print("caddy не найден в PATH — пропуск (brew install caddy, чтобы гонять зоны)")
    sys.exit(0)
# Рабочий Caddyfile в .gitignore (секреты) — на чистом клоне зоны гоняются по примеру
# с подставленными плейсхолдерами: тело примера обязано совпадать с рабочим (сверка в конце).
EXAMPLE = REPO / "tools/hosting/Caddyfile.example"
SOURCE = CADDYFILE if CADDYFILE.exists() else EXAMPLE
if not SOURCE.exists():
    print("нет ни Caddyfile, ни Caddyfile.example — пропуск")
    sys.exit(0)
if SOURCE is EXAMPLE:
    print(f"нет {CADDYFILE} (рабочий конфиг gitignored) — зоны по Caddyfile.example")

PORT = 8897
PASSWORD = "test-zones"
tmp = tempfile.mkdtemp(prefix="caddy-zones-")
root, health = Path(tmp) / "srv", Path(tmp) / "srv-health"
# «Еда» — отдельный том несинхронизируемого дерева (2026-07-20),
# как здоровье. Корень тома — САМ каталог Food, файлы лежат в нём.
food = Path(tmp) / "srv-food"
(root / "tools/assets").mkdir(parents=True)
(root / "Portfolio/integrated-views").mkdir(parents=True)
(root / "travel-planner/trips").mkdir(parents=True)
(root / "Gaming").mkdir(parents=True)
(root / "ZenMoney/audit").mkdir(parents=True)
food.mkdir(parents=True)
health.mkdir()
(root / "tools/hub.html").write_text("hub", encoding="utf-8")
(root / "tools/health.html").write_text("health", encoding="utf-8")
(root / "tools/food.html").write_text("food", encoding="utf-8")
(root / "tools/login.html").write_text("login", encoding="utf-8")
(root / "tools/portfolio-sw.js").write_text("// sw", encoding="utf-8")
(root / "tools/sw.js").write_text("// sw", encoding="utf-8")
(root / "tools/sw-offline.js").write_text("// core", encoding="utf-8")
(root / "tools/travel.html").write_text("travel", encoding="utf-8")
(root / "tools/games.html").write_text("games", encoding="utf-8")
(root / "tools/money.html").write_text("money", encoding="utf-8")
(root / "ZenMoney/audit/history.json").write_text('{"schema":"zenmoney-audit@1"}', encoding="utf-8")
(root / "tools/portfolio-integrated-viewer.html").write_text("viewer", encoding="utf-8")
(root / "tools/assets/viewer.js").write_text("//", encoding="utf-8")
(root / "tools/assets/help/viewer").mkdir(parents=True)
(root / "tools/assets/help/viewer/01-run.md").write_text("## 1. Запуск {#run}", encoding="utf-8")
(root / "Portfolio/integrated-views/integrated-view-2026-07-05.md").write_text("x", encoding="utf-8")
(root / "travel-planner/trips/trip.yaml").write_text("x", encoding="utf-8")
(root / "Gaming/library_full.yaml").write_text("x", encoding="utf-8")
(food / "products.json").write_text('{"schema":"food-products@1"}', encoding="utf-8")
(health / "labs.json").write_text('{"schema":"health-labs@1"}', encoding="utf-8")
# служебное внутри дерева: стек контейнеров, копии версий сайдкара, его черновики, Synology
(root / "_nas/api").mkdir(parents=True)
(root / "_nas/.env").write_text("HUB_API_DSM_PASSWORD=secret", encoding="utf-8")
(root / "_nas/Caddyfile").write_text("# hash", encoding="utf-8")
for _d in ("Portfolio/.versions", ".hub-api-staging", "Portfolio/@eaDir", "#recycle"):
    (root / _d).mkdir(parents=True, exist_ok=True)
    (root / _d / "x.json").write_text("{}", encoding="utf-8")
(food / ".versions").mkdir()
(food / ".versions/20261023-120000_products.json").write_text("{}", encoding="utf-8")
(health / ".versions").mkdir()
(health / ".versions/20261023-120000_labs.json").write_text("{}", encoding="utf-8")

hashed = subprocess.run([caddy, "hash-password", "--plaintext", PASSWORD],
                        capture_output=True, text=True).stdout.strip()
cfg = SOURCE.read_text(encoding="utf-8")
cfg = cfg.replace("<BCRYPT_HASH_HERE>", hashed).replace("<VPN_IP>", "10.8.0.2")
cfg = cfg.replace("<HOST>", "portfolio.example.org").replace("<BASE_DOMAIN>", "example.org")
cfg = cfg.replace(":8080 {", f":{PORT} {{}}".replace("{}", "{"))
cfg = cfg.replace("root * /srv-health", f"root * {health}")
cfg = cfg.replace("root * /srv-food", f"root * {food}")
cfg = cfg.replace("root * /srv", f"root * {root}", 1)
cfg = re.sub(r"\$2a\$14\$[A-Za-z0-9./]+", hashed, cfg)
# внешний HTTPS-редирект мешает локальной пробе (мы «внешние» для матчера)
cfg = re.sub(r"^\s*redir @http_external .*$", "", cfg, flags=re.M)
cfg_path = Path(tmp) / "Caddyfile"
cfg_path.write_text(cfg, encoding="utf-8")

proc = subprocess.Popen([caddy, "run", "--config", str(cfg_path), "--adapter", "caddyfile"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{PORT}"
GOOD = base64.b64encode(f"hubuser:{PASSWORD}".encode()).decode()
BAD = base64.b64encode(b"hubuser:nope").decode()


def req(path, headers=None):
    """→ (код, есть ли WWW-Authenticate)"""
    r = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, bool(resp.headers.get("WWW-Authenticate"))
    except urllib.error.HTTPError as e:
        return e.code, bool(e.headers.get("WWW-Authenticate"))
    except Exception:
        return 0, False


try:
    for _ in range(40):
        if req("/tools/hub.html")[0]:
            break
        time.sleep(0.25)

    # ── 1. НИКАКОГО нативного попапа ────────────────────────────────────────
    # Ни один запрос БЕЗ Authorization не должен получить WWW-Authenticate —
    # именно этот заголовок заставляет браузер показать окно пароля.
    print("нет попапа без входа")
    NO_AUTH_PATHS = [
        "/Portfolio/",
        "/Portfolio/integrated-views/",
        "/Portfolio/integrated-views/integrated-view-2026-07-05.md",
        "/health-data/labs.json",
        "/health-data/",
        "/ZenMoney/audit/history.json",  # money.html публичен, его данные — нет
        "/api/hd/file?path=meds.json",
        "/forecasts/",
        "/tools/",                     # листинг служебной папки — тоже приватный
    ]
    # разные виды запроса: навигация, фоновый fetch по https, fetch по голому http
    HEADER_SETS = {
        "навигация": {"Sec-Fetch-Dest": "document", "Accept": "text/html"},
        "fetch (https)": {"Sec-Fetch-Dest": "empty"},
        "fetch (голый http — Sec-Fetch НЕ шлётся)": {},
        "fetch + json": {"Accept": "application/json"},
        "iframe": {"Sec-Fetch-Dest": "iframe", "Accept": "text/html"},
        "картинка": {"Sec-Fetch-Dest": "image"},
    }
    for label, hdrs in HEADER_SETS.items():
        for p in NO_AUTH_PATHS:
            code, popup = req(p, hdrs)
            check(f"{p} [{label}] → без WWW-Authenticate (получено {code})", not popup)
            check(f"{p} [{label}] → 403, а не 401", code == 403)

    # ── 2. Публичное доступно без пароля ────────────────────────────────────
    print("публичное")
    # Еда публична по решению 2026-07-20: список покупок открывают в магазине
    # вдвоём и с мобильного интернета. Данные /Food/* — тоже, иначе страница
    # у гостя осталась бы пустой оболочкой.
    for p in ("/tools/hub.html", "/tools/health.html", "/tools/login.html",
              "/tools/travel.html", "/tools/games.html", "/tools/food.html", "/tools/money.html",
              "/tools/portfolio-integrated-viewer.html", "/tools/assets/viewer.js", "/tools/assets/help/viewer/01-run.md",
              "/travel-planner/trips/trip.yaml", "/Gaming/library_full.yaml",
              "/Food/products.json"):
        code, popup = req(p)
        check(f"{p} публичен (200, получено {code})", code == 200)
        check(f"{p} без попапа", not popup)

    # ── 3. С верным токеном приватное открывается ───────────────────────────
    print("вход по токену")
    for p in ("/Portfolio/integrated-views/", "/health-data/labs.json", "/ZenMoney/audit/history.json"):
        code, _ = req(p, {"Authorization": "Basic " + GOOD})
        check(f"{p} с токеном → 200 (получено {code})", code == 200)

    # ── 4. Неверный пароль ──────────────────────────────────────────────────
    # Единственное место, где Caddy шлёт WWW-Authenticate. Навигацией
    # недостижимо (токен живёт в localStorage), а в fetch попап гасит
    # credentials:'omit' на стороне страницы.
    print("неверный пароль")
    code, popup = req("/health-data/labs.json", {"Authorization": "Basic " + BAD})
    check(f"неверный токен → 401 (получено {code})", code == 401)

    # ── 5. Здоровье под паролем даже из LAN ─────────────────────────────────
    # 127.0.0.1 попадает в private_ranges, то есть это «доверенный IP».
    print("здоровье строже travel")
    code, _ = req("/api/hd/file?path=meds.json")
    check(f"/api/hd/* из LAN без токена → 403, а не проход (получено {code})", code == 403)
    code, _ = req("/api/health")
    check(f"/api/* из LAN без токена → проходит к сайдкару (получено {code})", code in (200, 502))

    # ── зона «Еда»: публична и на запись, с ЛЮБОГО IP ───────────────────────
    # X-Forwarded-For подделывает внешний клиент: в Caddyfile стоит
    # `trusted_proxies static private_ranges`, а тест ходит с 127.0.0.1 —
    # значит заголовку верят и client_ip становится 8.8.8.8.
    # 502 здесь = «дошло до reverse_proxy, а сайдкара в тесте нет» — именно это
    # и проверяем: НЕ 403.
    EXT = {"X-Forwarded-For": "8.8.8.8"}
    code, _ = req("/api/fd/file?path=products.json", EXT)
    check(f"/api/fd/* с ЧУЖОГО IP без токена → доходит до сайдкара (получено {code})",
          code in (200, 404, 502))
    # Контраст: соседние зоны с того же чужого IP обязаны остаться закрытыми,
    # иначе окажется, что публичной стала не только еда.
    code, _ = req("/api/file?path=Gaming/recommendations/a.md", EXT)
    check(f"/api/* с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/hd/file?path=meds.json", EXT)
    check(f"/api/hd/* с чужого IP без токена → 403 (получено {code})", code == 403)

    # ── котировки MOEX: публично, с ЛЮБОГО IP, не задевая соседей ──────────
    # 502 = дошло до reverse_proxy (сайдкара в тесте нет), 403 = закрыто.
    print("moex публичен")
    code, auth = req("/api/moex/quotes?boards=TQBR", EXT)
    check(f"/api/moex/* с чужого IP без токена → доходит до сайдкара (получено {code})",
          code in (200, 400, 502))
    check("/api/moex/* не challenge'ит (нет WWW-Authenticate)", not auth)
    code, _ = req("/api/moex/quotes?boards=TQBR", {**EXT, "Authorization": "Basic " + BAD})
    check(f"/api/moex/* с неверным токеном не проверяет пароль (получено {code})",
          code in (200, 400, 502))
    code, _ = req("/api/moex/quotes")
    check(f"/api/moex/* из LAN → доходит до сайдкара (получено {code})", code in (200, 400, 502))
    # публичность moex не должна расползтись на соседей
    code, _ = req("/api/hd/file?path=meds.json", EXT)
    check(f"/api/hd/* после moex по-прежнему 403 с чужого IP (получено {code})", code == 403)
    code, _ = req("/api/hd/moex/quotes", EXT)
    check(f"/api/hd/moex/* не публичен (получено {code})", code == 403)
    code, _ = req("/api/moexx/quotes", EXT)
    check(f"/api/moexx/* (чужой префикс) не публичен (получено {code})", code == 403)
    code, _ = req("/Portfolio/integrated-views/", EXT)
    check(f"портфель с чужого IP → 403 (получено {code})", code == 403)

    # ── push-уведомления (v3-B, 2026-10-16): пароль с ЛЮБОГО IP, как здоровье ──
    # 502 = дошло до hub-notify (в тесте его нет), 403 = закрыто, 401 = пароль неверен.
    print("push под паролем")
    code, auth = req("/api/push/key")
    check(f"/api/push/* из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/push/key", EXT)
    check(f"/api/push/* с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/push/key", {"Authorization": "Basic " + BAD})
    check(f"/api/push/* с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/push/key", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/push/* с паролем → доходит до hub-notify (получено {code})", code == 502)
    # ── сборка снапшота с вьюера (2026-10-21): выгрузки брокера — пароль с ЛЮБОГО IP ──
    print("сборка снапшота под паролем")
    code, auth = req("/api/pf/status")
    check(f"/api/pf/* из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/pf/status", EXT)
    check(f"/api/pf/* с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/pf/status", {"Authorization": "Basic " + BAD})
    check(f"/api/pf/* с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/pf/status", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/pf/* с паролем → доходит до hub-notify (получено {code})", code == 502)
    # решение владельца с карточки бумаги (POST /api/pf/decision, hub-notify): тот же маршрут /api/pf/* — пароль с любого IP
    for label, hdr, want in (("из LAN без токена", {}, 403), ("с чужого IP без токена", EXT, 403),
                             ("с неверным паролем", {"Authorization": "Basic " + BAD}, 401),
                             ("с паролем с чужого IP", {**EXT, "Authorization": "Basic " + GOOD}, 502)):
        code, _ = req("/api/pf/decision", hdr)
        check(f"/api/pf/decision {label} → {want} (получено {code})", code == want)
        code, _ = req("/api/pf/condition", hdr)          # условие-напоминание владельца (condition_job): тот же /api/pf/*
        check(f"/api/pf/condition {label} → {want} (получено {code})", code == want)
    code, _ = req("/tools/portfolio-sw.js")
    check(f"фоновый скрипт вьюера публичен без пароля (получено {code})", code == 200)
    for _p in ("/tools/sw.js", "/tools/sw-offline.js"):     # офлайн всех страниц (2026-10-23)
        code, popup = req(_p)
        check(f"{_p} публичен без пароля — иначе фоновый скрипт не зарегистрируется (получено {code})",
              code == 200 and not popup)

    # ── служебное (2026-10-23): _nas/ — 404 всем; копии версий и черновики — как будто их нет ──
    # Случай 23.10: /_nas/.env (пароль DSM) отдавался любому, кто знает пароль кабинета.
    print("служебное закрыто")
    for p in ("/_nas/.env", "/_nas/Caddyfile", "/_nas/", "/_nas", "/_nas/api/"):
        for label, h in (("без пароля", {}), ("с паролем", {"Authorization": "Basic " + GOOD}),
                         ("с чужого IP с паролем", {**EXT, "Authorization": "Basic " + GOOD})):
            code, popup = req(p, h)
            check(f"{p} {label} → 404 (получено {code})", code == 404 and not popup)
    for p in ("/Portfolio/.versions/x.json", "/Portfolio/.versions/", "/.hub-api-staging/x.json",
              "/Portfolio/@eaDir/x.json", "/%23recycle/x.json", "/Food/.versions/20261023-120000_products.json",
              "/Food/.versions/", "/health-data/.versions/20261023-120000_labs.json"):
        code, _ = req(p, {"Authorization": "Basic " + GOOD})
        check(f"{p} с паролем → 404 (получено {code})", code == 404)
    import json as _json
    _r = urllib.request.Request(BASE + "/Portfolio/", headers={"Authorization": "Basic " + GOOD,
                                                                "Accept": "application/json"})
    with urllib.request.urlopen(_r) as _resp:
        _names = [e["name"] for e in _json.loads(_resp.read())]
    check(f"листинг /Portfolio/ без служебных папок ({_names})",
          "integrated-views/" in _names and not any(n.strip("/") in (".versions", "@eaDir") for n in _names))
    code, _ = req("/Food/products.json")
    check(f"данные «Еды» по-прежнему публичны (получено {code})", code == 200)
    code, _ = req("/health-data/labs.json", {"Authorization": "Basic " + GOOD})
    check(f"медданные с паролем по-прежнему открываются (получено {code})", code == 200)

    # ── /api/pv/* (вьюер одним запросом, 2026-10-23): пароль с ЛЮБОГО IP, как сами файлы портфеля ──
    print("вьюер одним запросом под паролем")
    code, auth = req("/api/pv/sync")
    check(f"/api/pv/* из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/pv/sync", EXT)
    check(f"/api/pv/* с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/pv/sync", {"Authorization": "Basic " + BAD})
    check(f"/api/pv/* с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/pv/sync", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/pv/* с паролем → доходит до hub-api (получено {code})", code == 502)
    code, auth = req("/api/pv/plan")
    check(f"/api/pv/plan из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/pv/plan", EXT)
    check(f"/api/pv/plan с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/pv/plan", {"Authorization": "Basic " + BAD})
    check(f"/api/pv/plan с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/pv/plan", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/pv/plan с паролем → доходит до hub-api (получено {code})", code == 502)
    # ── /api/pv/macro/inflation (форма «Внести инфляцию», owner.jsonl): запись — только под паролем, с любого IP ──
    code, auth = req("/api/pv/macro/inflation")
    check(f"/api/pv/macro/inflation из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/pv/macro/inflation", EXT)
    check(f"/api/pv/macro/inflation с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/pv/macro/inflation", {"Authorization": "Basic " + BAD})
    check(f"/api/pv/macro/inflation с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/pv/macro/inflation", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/pv/macro/inflation с паролем → доходит до hub-api (получено {code})", code == 502)
    # ── /api/hub/settings (режим сайта «с ИИ / без ИИ»): пароль с ЛЮБОГО IP, как /api/pv/* ──
    code, auth = req("/api/hub/settings")
    check(f"/api/hub/settings из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/hub/settings", EXT)
    check(f"/api/hub/settings с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/hub/settings", {"Authorization": "Basic " + BAD})
    check(f"/api/hub/settings с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/hub/settings", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/hub/settings с паролем → доходит до hub-api (получено {code})", code == 502)

    # ── /api/gm/* (оверлей игр gaming-user@1): пароль с ЛЮБОГО IP, как /api/pv/* ──
    code, auth = req("/api/gm/file")
    check(f"/api/gm/file из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/gm/file", EXT)
    check(f"/api/gm/file с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/gm/file", {"Authorization": "Basic " + BAD})
    check(f"/api/gm/file с неверным паролем → 401 (получено {code})", code == 401)
    code, _ = req("/api/gm/file", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/gm/file с паролем → доходит до hub-api (получено {code})", code == 502)

    # ── /api/zm/* (выгрузка CSV ZenMoney): пароль с ЛЮБОГО IP, как /api/gm/* ──
    code, auth = req("/api/zm/csv-state")
    check(f"/api/zm/csv-state из LAN без токена → 403 (получено {code})", code == 403 and not auth)
    code, _ = req("/api/zm/csv-state", EXT)
    check(f"/api/zm/csv-state с чужого IP без токена → 403 (получено {code})", code == 403)
    code, _ = req("/api/zm/csv-apply", {"Authorization": "Basic " + BAD})
    check(f"/api/zm/csv-apply с неверным паролем → 401 (получено {code})", code == 401)
    for _p in ("/api/zm/stmt", "/api/zm/stmt-report"):
        code, _ = req(_p, EXT)
        check(f"{_p} с чужого IP без токена → 403 (получено {code})", code == 403)
        code, _ = req(_p, {**EXT, "Authorization": "Basic " + GOOD})
        check(f"{_p} с паролем с любого IP → доходит до hub-api (получено {code})", code == 502)
    code, _ = req("/api/zm/csv-state", {**EXT, "Authorization": "Basic " + GOOD})
    check(f"/api/zm/csv-state с паролем → доходит до hub-api (получено {code})", code == 502)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    shutil.rmtree(tmp, ignore_errors=True)


# ── Caddyfile.example ↔ рабочий Caddyfile ──────────────────────────────────
# Рабочий Caddyfile в .gitignore (в нём bcrypt-хэш и домашний IP), поэтому
# ЕДИНСТВЕННОЕ, что видит чужая машина и этот тест из чистого клона, — пример.
# Отстал пример — развёртывание с нуля молча теряет зону: раздел «Еда» приехал
# 2026-07-20, а в примере его не было вовсе (страница выкладывалась, но
# /api/fd/* отдавал 403 и список покупок был нередактируем).
print("\nexample")
_ex_path = REPO / "tools/hosting/Caddyfile.example"
check("Caddyfile.example существует", _ex_path.exists())
if _ex_path.exists() and CADDYFILE.exists():
    _ex = _ex_path.read_text(encoding="utf-8")
    # Секреты в примере недопустимы — он коммитится.
    check("пример без bcrypt-хэша", not re.search(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}", _ex))
    check("пример без реального IP", not re.search(r"client_ip private_ranges \d+\.\d+\.\d+\.\d+", _ex))
    check("пример без реального хоста", "example" not in _ex)
    check("в примере размечены плейсхолдеры",
          "<BCRYPT_HASH_HERE>" in _ex and "<VPN_IP>" in _ex)

    def _norm(s):
        s = re.sub(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}|<BCRYPT_HASH_HERE>", "H", s)
        s = re.sub(r"client_ip private_ranges [^\s]+", "client_ip private_ranges IP", s)
        s = re.sub(r"(?:https://)?(?:[\w.-]*example\.synology\.me|<HOST>|<BASE_DOMAIN>)", "HOST", s)
        # комментарии расходятся законно (в примере — инструкция «как завести»)
        return [l.rstrip() for l in s.splitlines() if l.strip() and not l.lstrip().startswith("#")]

    _a, _b = _norm(CADDYFILE.read_text(encoding="utf-8")), _norm(_ex)
    check(f"тело примера совпадает с рабочим ({len(_a)} ↔ {len(_b)} строк)", _a == _b)
    if _a != _b:
        import difflib
        for _l in list(difflib.unified_diff(_a, _b, "Caddyfile", "Caddyfile.example",
                                            lineterm=""))[:14]:
            print("    " + _l)


# ── сторож деплоя ↔ публичные пути Caddy ───────────────────────────────────
# deploy.zsh после выкладки проверяет, что публичные страницы реально
# открываются без пароля. Канарейка была ОДНА (login.html) — и промахнулась:
# со старым конфигом login.html отвечал 200, деплой рапортовал «всё хорошо», а
# food.html отдавал 403. Тихий 403 идёт с пустым телом, поэтому на экране это
# выглядит как БЕЛАЯ СТРАНИЦА, а не как отказ доступа (случай 2026-07-20).
# Список проверяемых путей обязан покрывать все публичные страницы конфига.
print("\ndeploy-canary")
_dep = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
if SOURCE.exists():
    _cfg = SOURCE.read_text(encoding="utf-8")
    # публичные страницы = исключения `not path` в приватных матчерах
    _pub_pages = sorted({p for line in _cfg.splitlines()
                         if line.strip().startswith("not path")
                         for p in re.findall(r"/tools/[\w.-]+\.html", line)})
    check(f"в Caddyfile найдены публичные страницы ({len(_pub_pages)})", len(_pub_pages) >= 5)
    _m = re.search(r"PUBLIC=\(([^)]*)\)", _dep, re.S)
    check("deploy.zsh объявляет список публичных путей PUBLIC", bool(_m))
    if _m:
        _probed = set(_m.group(1).split())
        _gap = sorted(p for p in _pub_pages if p.lstrip("/") not in _probed)
        check("сторож деплоя проверяет КАЖДУЮ публичную страницу конфига"
              + (" — не покрыты: " + ", ".join(_gap) if _gap else ""), not _gap)
        # 403/401 на публичном пути = устаревший конфиг, и сказать об этом надо
        # словами «белый экран»: именно так это выглядит у человека.
        check("сторож объясняет симптом белого экрана",
              "БЕЛЫЙ ЭКРАН" in _dep and "403" in _dep)
# Сайдкар объявляет зоны через /api/health. Проверка была написана под здоровье
# и про еду не знала — страница уходила в «только просмотр» молча.
check("сторож деплоя проверяет и зону еды в сайдкаре", "food_files" in _dep)

# ── caddyfile_from_example.py: рабочий из примера со своими секретами (2026-10-23) ──
print("\ncaddyfile_from_example")
sys.path.insert(0, str(REPO / "tools/hosting"))
import caddyfile_from_example as cfe  # noqa: E402
_h = "$2a$14$" + "a" * 53
_work = (EXAMPLE.read_text(encoding="utf-8").replace("<BCRYPT_HASH_HERE>", _h).replace("<VPN_IP>", "10.8.0.2")
         .replace("<HOST>", "hub.example.com").replace("<BASE_DOMAIN>", "nas.example.com"))
_sec = cfe.secrets(_work)
check("секреты рабочего: хэш, VPN-IP, домен", _sec == {"hash": _h, "vpn": "10.8.0.2", "host": "hub.example.com"})
_out = cfe.render(EXAMPLE.read_text(encoding="utf-8"), _sec)
_body = lambda t: [l for l in t.splitlines() if l.strip() and not l.lstrip().startswith("#")]  # noqa: E731
check("пересборка = пример с секретами (тело)", _body(_out) == _body(_work))
check("в теле нет плейсхолдеров, секреты не в комментариях",
      "<" + "VPN_IP>" not in "\n".join(_body(_out)) and not any(_h in l for l in _out.splitlines() if l.lstrip().startswith("#")))
for _bad, _why in ((_work.replace(_h, "$2a$14$" + "b" * 53, 1), "два разных хэша"),
                   (_work.replace("client_ip private_ranges 10.8.0.2", "client_ip private_ranges <VPN_IP>"), "VPN-IP не вписан")):
    try:
        cfe.secrets(_bad)
        check(f"отказ: {_why}", False)
    except ValueError:
        check(f"отказ: {_why}", True)

print(f"\ncaddy_zones: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
