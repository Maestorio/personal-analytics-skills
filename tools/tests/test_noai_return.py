#!/usr/bin/env python3
"""
Тест tools/noai_return.py — сверка зеркала Mac с NAS перед возвратом к ИИ (stdlib, без сети).

Ответ маршрута /api/hub/changes берётся из файла (--changes-json); зеркало — временный корень с
`_hub/settings.json`. Запуск: python3 tools/tests/test_noai_return.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import noai_return  # noqa: E402

SCRIPT = str(REPO / "tools/noai_return.py")
passed = failed = 0


# переменные сайта из оболочки владельца (HUB_URL/HUB_AUTH) не должны уводить проверки «без сети» в настоящий NAS
for _k in ("HUB_URL", "HUB_AUTH"):
    os.environ.pop(_k, None)


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def cli(*args):
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


def item(path, content):
    return {"path": path, "size": len(content), "mtime": "2026-11-09T12:00:00+03:00", "sha256": sha(content)}


OFF = "2026-11-09T10:00:00+03:00"
tmp = tempfile.mkdtemp(prefix="noai-return-")
try:
    root = Path(tmp) / "mirror"
    (root / "_hub").mkdir(parents=True)
    (root / "_hub/settings.json").write_text(json.dumps(
        {"schema": "hub-settings@1", "ai_mode": "off", "off_since": OFF, "returned_at": None,
         "by": "site", "note": "", "updated_at": OFF}), encoding="utf-8")
    same_c, diff_c = b'{"a": 1}', b'{"b": 2}'
    (root / "Portfolio/decisions").mkdir(parents=True)
    (root / "Portfolio/decisions/d1.json").write_bytes(same_c)
    (root / "Gaming").mkdir()
    (root / "Gaming/user-state.json").write_bytes("старое".encode())
    chg = Path(tmp) / "changes.json"

    def write_changes(files, truncated=False, since=OFF):
        chg.write_text(json.dumps({"since": since, "generated_at": OFF, "zones": [], "files": files,
                                   "truncated": truncated}), encoding="utf-8")

    # 1. совпал / отличается / нет на зеркале
    write_changes([item("Portfolio/decisions/d1.json", same_c),
                   item("Gaming/user-state.json", diff_c),
                   item("Health/labs.json", b"{}")])
    code, out, err = cli("--root", str(root), "--changes-json", str(chg), "--json")
    res = json.loads(out) if out.strip().startswith("{") else {}
    check(f"отстаёт → код 1 ({code}) {err.strip()[:80]}", code == 1)
    check("--json: differs", res.get("differs") == ["Gaming/user-state.json"])
    check("--json: missing", res.get("missing") == ["Health/labs.json"])
    check("--json: same=1, всего 3, ok false", res.get("same") == 1 and res.get("files_changed_on_nas") == 3
          and res.get("ok") is False)
    check("--json: since из off_since зеркала", res.get("since") == OFF)
    kinds = dict((k, n) for k, n in res.get("by_kind", []))
    check("by_kind: «решения владельца с сайта» = 1", kinds.get("решения владельца с сайта") == 1)
    code, out, _ = cli("--root", str(root), "--changes-json", str(chg))
    check("текст: вердикт «зеркало отстаёт»", code == 1 and "зеркало отстаёт: 2" in out
          and "≠ Gaming/user-state.json" in out and "нет на зеркале: Health/labs.json" in out)

    # 2. всё совпало
    (root / "Gaming/user-state.json").write_bytes(diff_c)
    (root / "Health").mkdir()
    (root / "Health/labs.json").write_bytes(b"{}")
    code, out, _ = cli("--root", str(root), "--changes-json", str(chg))
    check(f"всё совпало → код 0 ({code})", code == 0)
    check("строка «зеркало догнало NAS»", "зеркало догнало NAS" in out)
    code, out, _ = cli("--root", str(root), "--changes-json", str(chg), "--json")
    check("--json ok true при совпадении", code == 0 and json.loads(out)["ok"] is True)

    # 3. truncated
    write_changes([item("Portfolio/decisions/d1.json", same_c)], truncated=True)
    code, out, _ = cli("--root", str(root), "--changes-json", str(chg), "--json")
    check("truncated → код 1, ok false", code == 1 and json.loads(out)["truncated"] is True
          and json.loads(out)["ok"] is False)

    # 4. нет данных
    write_changes([item("Portfolio/decisions/d1.json", same_c)])
    bare = Path(tmp) / "bare"
    bare.mkdir()
    code, _, err = cli("--root", str(bare), "--changes-json", str(chg))
    check(f"без off_since и без --since → код 2 ({code})", code == 2 and "--since" in err)
    code, _, _ = cli("--root", str(root))
    check(f"без --changes-json и без url → код 2 ({code})", code == 2)
    code, _, err = cli("--root", str(Path(tmp) / "нет-такой"), "--changes-json", str(chg))
    check(f"несуществующий --root → код 2 ({code})", code == 2)

    # 5. --since перекрывает off_since
    code, out, _ = cli("--root", str(bare), "--changes-json", str(chg), "--since", "2026-11-01T00:00:00+03:00", "--json")
    check("явный --since работает без флага (код 1: на пустом зеркале файла нет)", code == 1 and json.loads(out)["since"] == "2026-11-01T00:00:00+03:00")
    code, out, _ = cli("--root", str(root), "--changes-json", str(chg), "--since", "2026-11-02T00:00:00+03:00", "--json")
    check("явный --since перекрывает off_since", json.loads(out)["since"] == "2026-11-02T00:00:00+03:00")

    # 6. run() импортом
    check("run(argv) импортом → 0", noai_return.run(["--root", str(root), "--changes-json", str(chg)]) == 0)

    # 7. classify
    for path, label in (("Gaming/user-state.json", "оверлей игр"),
                        ("Health/labs.json", "точки анализов (ручные — source: manual)"),
                        ("ZenMoney/audit/x.json", "итоги месяцев и поездок из CSV"),
                        ("Portfolio/decisions/x.json", "решения владельца с сайта"),
                        ("scenarios/w.json", "веса сценариев и сроки"),
                        ("чужое", "прочее")):
        check(f"classify {path} → {label}", noai_return.classify(path) == label)

    # 8. compare / summarize
    c = noai_return.compare(root, [item("Portfolio/decisions/d1.json", same_c), {"path": "Gaming/user-state.json"},
                                   item("nope.json", b"x")])
    check("compare: файл без sha256 считается differs", c["same"] == ["Portfolio/decisions/d1.json"]
          and c["differs"] == ["Gaming/user-state.json"] and c["missing"] == ["nope.json"])
    check("summarize: сортировка по убыванию",
          noai_return.summarize([{"path": "Gaming/user-state.json"}, {"path": "Gaming/user-state.json"},
                                 {"path": "чужое"}])[0] == ("оверлей игр", 2))
finally:
    shutil.rmtree(tmp)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
