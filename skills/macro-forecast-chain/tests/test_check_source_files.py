#!/usr/bin/env python3
"""Тесты check_source_files.py: warning на фактор без source_files (контракт 3.111.0, вьюер угадывает входы стресс-теста по теме).

Запуск из корня репозитория: python3 skills/macro-forecast-chain/tests/test_check_source_files.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills/macro-forecast-chain/scripts/check_source_files.py"
LIVE = REPO / "tools/tests/fixtures/stress-roles/macro-chain/macro-scenarios-2026-10-04.yaml"
sys.path.insert(0, str(SCRIPT.parent))
from check_source_files import check, check_forecast_files, forecast_files_from_sources, render_block  # noqa: E402

passed = failed = 0


def ok(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


ok("с source_files — тишина", check({"factors": {"brent": {"status": "FRESH", "source_files": ["forecasts/b.yaml"]}}}) == [])
w = check({"factors": {"brent": {"status": "FRESH"}, "cbr_rate": {"source_files": []}, "usd": {"source_files": ["forecasts/u.yaml"]}}})
ok("без поля и с пустым списком — по предупреждению", len(w) == 2 and "factors.brent" in w[0] and "factors.cbr_rate" in w[1])
ok("MISSING без файла не проверяется", check({"factors": {"x": {"status": "MISSING"}, "y": {"status": "accepted_missing"}}}) == [])
ok("строка вместо списка — предупреждение", len(check({"factors": {"b": {"source_files": "forecasts/b.yaml"}}})) == 1)
ok("нет factors — предупреждение", check({}) == ["нет блока factors"])
live = subprocess.run([sys.executable, str(SCRIPT), str(LIVE)], capture_output=True, text=True)
ok("живой bundle 04.10 (до source_files): CLI код 0, warning на 8 факторов", live.returncode == 0 and live.stdout.count("WARNING") >= 8)
ok("файла нет — код 2", subprocess.run([sys.executable, str(SCRIPT), str(Path(tempfile.gettempdir()) / "нет-такого.yaml")], capture_output=True, text=True).returncode == 2)

# --- forecast_files (шаг 14, schema.md §4.6): ссылка макросценариев на прогнозы ---
src = {"schema_version": 2, "factors": {
    "brent_price": {"source_files": ["forecasts/brent-price-2026-09-17.yaml", "scenarios/geo-2026-07-01.yaml"]},
    "cbr_rate": {"source_files": ["forecasts/cbr-a-2026-09-17.yaml", "forecasts/cbr-b-2026-09-17.yaml"]},
    "xauusd_price": {"status": "MISSING"}}}
m, probs = forecast_files_from_sources(src)
ok("из source_files: только forecasts/, имя без расширения", m == {"brent_price": "brent-price-2026-09-17"})
ok("два файла прогноза — проблема, не угадываем", len(probs) == 1 and "cbr_rate" in probs[0])
e, _ = check_forecast_files(src)
ok("новый файл (schema_version 2) без forecast_files — ошибка", len(e) == 1 and "обязателен" in e[0])
ok("старый файл (schema_version 1) без forecast_files — без ошибок", check_forecast_files(dict(src, schema_version=1)) == ([], []))
good = dict(src, forecast_files={"brent_price": "brent-price-2026-09-17", "cbr_rate": "cbr-a-2026-09-17"})
e, w = check_forecast_files(good)
ok("с forecast_files — без ошибок", e == [] and w == [])
e, w = check_forecast_files(dict(src, forecast_files={"brent_price": "forecasts/brent-price-2026-09-17.yaml"}))
ok("путь/расширение в значении — ошибка", len(e) == 1 and "без папки" in e[0])
e, w = check_forecast_files(dict(src, forecast_files={"brent_price": "brent-price-2026-07-28", "gold": "x-2026-01-01"}))
ok("расхождение с source_files и чужой фактор — предупреждения", e == [] and len(w) == 2)
ok("не объект — ошибка", len(check_forecast_files(dict(src, forecast_files=["a"]))[0]) == 1)
import yaml  # noqa: E402
blk = render_block(m)
ok("блок --forecast-files читается как строки, не даты", yaml.safe_load(blk) == {"forecast_files": m})
with tempfile.TemporaryDirectory() as td:
    f = Path(td) / "ms.yaml"
    f.write_text(yaml.safe_dump(src, allow_unicode=True), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    ok("CLI: новый файл без forecast_files — код 1", r.returncode == 1 and "ОШИБКА: forecast_files" in r.stdout)
    r = subprocess.run([sys.executable, str(SCRIPT), "--forecast-files", str(f)], capture_output=True, text=True)
    ok("CLI --forecast-files печатает блок, неоднозначное — в stderr",
       r.returncode == 0 and yaml.safe_load(r.stdout) == {"forecast_files": m} and "cbr_rate" in r.stderr)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
