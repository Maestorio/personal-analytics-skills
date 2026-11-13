#!/usr/bin/env python3
"""Пересобрать рабочий tools/hosting/Caddyfile из Caddyfile.example, сохранив свои секреты.

Рабочий Caddyfile живёт только на Маке (gitignored: bcrypt-хэш пароля, домашний VPN-IP, домен),
поэтому правки зон в репозитории (пример) переносились в него руками — и расходились. Скрипт берёт
из текущего рабочего файла хэш, VPN-IP и домен, подставляет их в пример и показывает разницу.

    python3 tools/hosting/caddyfile_from_example.py           # только показать разницу
    python3 tools/hosting/caddyfile_from_example.py --write   # записать (старый — в Caddyfile.bak-<время>)
    python3 tools/hosting/caddyfile_from_example.py --hash '$2a$14$…' --write   # и сменить пароль сайта

Новый хэш: на NAS `sudo docker exec -it portfolio-viewer caddy hash-password` (спросит пароль дважды).

После записи: python3 tools/tests/test_caddy_zones.py (тело рабочего обязано совпасть с примером),
затем tools/deploy.zsh и `sudo docker restart portfolio-viewer` на NAS. Только stdlib.
"""
import difflib
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXAMPLE = HERE / "Caddyfile.example"
WORK = HERE / "Caddyfile"

HASH_RE = re.compile(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}")
VPN_RE = re.compile(r"client_ip private_ranges (\S+)")
HOST_RE = re.compile(r"redir @http_external https://([^{\s]+)\{uri\}")


def secrets(text):
    """→ {hash, vpn, host} из рабочего Caddyfile; чего нет — ValueError с объяснением."""
    h, v, d = HASH_RE.findall(text), VPN_RE.findall(text), HOST_RE.findall(text)
    if not h or len(set(h)) != 1:
        raise ValueError(f"bcrypt-хэш: ожидался один и тот же во всех basic_auth, найдено {len(set(h))}")
    if not v or len(set(v)) != 1 or v[0].startswith("<"):
        raise ValueError(f"VPN-IP после «client_ip private_ranges»: найдено {sorted(set(v))}")
    if len(set(d)) != 1 or d[0].startswith("<"):
        raise ValueError(f"домен в «redir @http_external https://…{{uri}}»: найдено {sorted(set(d))}")
    return {"hash": h[0], "vpn": v[0], "host": d[0]}


def render(example, s):
    base = s["host"].split(".", 1)[1] if "." in s["host"] else s["host"]
    def sub(line):                     # комментарии примера (инструкция «как завести») — как есть
        if line.lstrip().startswith("#"):
            return line
        return (line.replace("<BCRYPT_HASH_HERE>", s["hash"]).replace("<VPN_IP>", s["vpn"])
                .replace("<HOST>", s["host"]).replace("<BASE_DOMAIN>", base))
    out = "\n".join(sub(l) for l in example.split("\n"))
    left = re.findall(r"<(BCRYPT_HASH_HERE|VPN_IP|HOST|BASE_DOMAIN)>",
                      "\n".join(l for l in out.split("\n") if not l.lstrip().startswith("#")))
    if left:
        raise ValueError(f"в примере остались плейсхолдеры: {sorted(set(left))}")
    return out


def main(argv):
    if not WORK.exists():
        print(f"нет {WORK} — нечего брать за основу (заведи по шапке Caddyfile.example)")
        return 2
    old = WORK.read_text(encoding="utf-8")
    try:
        sec = secrets(old)
        if "--hash" in argv:
            h = argv[argv.index("--hash") + 1] if argv.index("--hash") + 1 < len(argv) else ""
            if not HASH_RE.fullmatch(h):
                raise ValueError("--hash: нужен bcrypt-хэш целиком ($2a$14$… — 60 символов, в одинарных кавычках)")
            sec["hash"] = h
        new = render(EXAMPLE.read_text(encoding="utf-8"), sec)
    except ValueError as e:
        print(f"✗ {e}")
        return 2
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "Caddyfile (сейчас)",
                                     "Caddyfile (из примера)", lineterm="", n=1))
    if not diff:
        print("✓ рабочий Caddyfile уже совпадает с примером")
        return 0
    print("\n".join(HASH_RE.sub("<хэш>", l) for l in diff))
    if "--write" not in argv:
        print("\nЭто разница. Записать: python3 tools/hosting/caddyfile_from_example.py --write")
        return 0
    bak = WORK.with_name(f"Caddyfile.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(WORK, bak)
    WORK.write_text(new, encoding="utf-8")
    print(f"\n✓ записан {WORK} (прежний — {bak.name}). Дальше: python3 tools/tests/test_caddy_zones.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
