#!/usr/bin/env zsh
# Прогон всех тестов Personal Hub (страницы, сайдкар, зоны Caddy, «Еда»).
#
# Зачем отдельный скрипт, а не цикл в терминале: цикл `for t in …; do …; done`
# не совпадает ни с одним шаблоном allowlist, поэтому каждый прогон требовал
# подтверждения вручную. Одна команда — одно правило.
#
# Системный python3 в этой среде сломан — гоняем через pyenv.
set -u
cd "${0:A:h}/../.."

PY="$HOME/.pyenv/versions/3.12.9/bin/python3"
SUITES=(
  tools/tests/test_write_api.py
  tools/tests/test_pages_contracts.py
  tools/tests/test_caddy_zones.py
  tools/tests/test_validate_recipe.py
  tools/tests/test_match_products.py
  tools/tests/test_nutrition.py
)

typeset -i bad=0 total=0
for suite in "${SUITES[@]}"; do
  out=$("$PY" "$suite" 2>&1)
  rc=$?
  line=${out##*$'\n'}
  printf "%-34s %s\n" "${suite:t:r}" "$line"
  (( rc != 0 )) && (( bad++ ))
  n=${line//[^0-9 ]/}
  total+=${${(z)n}[1]:-0}
done

print -- "---"
if (( bad )); then
  print -- "провалов: $bad из ${#SUITES[@]}"
  exit 1
fi
print -- "всё зелено · проверок: $total"
