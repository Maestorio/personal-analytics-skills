#!/usr/bin/env bash
# Pre-commit hook: валидация схем YAML и базовые тесты.
#
# Установка:
#   cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Или через симлинк (обновляется автоматически):
#   ln -sf ../../scripts/pre-commit-hook.sh .git/hooks/pre-commit

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "=== pre-commit: validate_schema.py ==="

# Собираем staged YAML файлы
STAGED_YAMLS=$(git diff --cached --name-only --diff-filter=ACM | grep '\.yaml$' || true)

if [ -n "$STAGED_YAMLS" ]; then
    echo "Проверяю: $STAGED_YAMLS"
    python3 scripts/validate_schema.py $STAGED_YAMLS
    SCHEMA_EXIT=$?
    if [ $SCHEMA_EXIT -ne 0 ]; then
        echo "[BLOCKED] validate_schema.py вернул ошибки — исправь перед коммитом"
        exit 1
    fi
else
    echo "(нет staged YAML файлов)"
fi

echo "=== pre-commit: базовые unit тесты ==="
python3 tests/test_recalibrate.py > /dev/null && echo "  [OK] test_recalibrate"
python3 tests/test_migration.py   > /dev/null && echo "  [OK] test_migration"
python3 tests/test_integration.py > /dev/null && echo "  [OK] test_integration"

echo "=== pre-commit: OK ==="
