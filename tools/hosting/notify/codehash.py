"""Отпечаток кода hub-notify: по нему deploy.zsh видит, что контейнер работает на старых файлах.

hub-notify считает отпечаток своей папки (/app) при старте и отдаёт его через hub-api
(/api/health → notify.code); deploy.zsh считает тот же отпечаток по разложенной папке
_nas/notify/ и при расхождении печатает «sudo docker restart hub-notify». Раньше деплой
проверял только hub-api, и забытый перезапуск hub-notify был незаметен (2026-10-26).

Только stdlib: deploy.zsh запускает файл системным python3 — `python3 codehash.py <папка>`.
"""
import hashlib
import sys
from pathlib import Path


def code_hash(root):
    """sha256 по всем *.py и *.json папки (вложенные тоже, без __pycache__): путь и содержимое.
    JSON считается тоже: кодлисты (codelists.json) читаются при старте процесса, их правка = устаревший контейнер."""
    root = Path(root)
    h = hashlib.sha256()
    for f in sorted(p for p in list(root.rglob("*.py")) + list(root.rglob("*.json")) if "__pycache__" not in p.parts):
        h.update(f.relative_to(root).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()[:16]


if __name__ == "__main__":
    print(code_hash(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent))
