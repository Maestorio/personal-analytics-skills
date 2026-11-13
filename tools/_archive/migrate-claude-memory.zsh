#!/usr/bin/env zsh
# migrate-claude-memory.zsh — Phase 0, Step 4
#
# Запускать из Terminal (не VSCode) — нужен полный доступ к Synology Drive.
#
# Использование:
#   zsh migrate-claude-memory.zsh           # реальная миграция
#   zsh migrate-claude-memory.zsh --dry-run # только показывает, что будет сделано
#
# Что делает:
#   1. Создаёт новые папки (Portfolio/, domains/, macro-chain/, и т.д.)
#   2. Macro-Chain/ → macro-chain/ + lowercase файлы внутри
#   3. Portfolio-Stress/ → Portfolio/stress/ + lowercase файлы
#   4. Sibling Portfolio-Snapshots/ → Portfolio/snapshots/ + lowercase
#   5. Sibling Macro-Snapshots/ → macro-snapshots/ + lowercase (дубликаты → -dup)
#   6. Sibling Claude-Portfolio/ → Portfolio/ (INDEX.md + forecasts/)
#   7. Domain-папки (geopolitics и др.) → domains/
#   8. Флажок на _meta-analysis/ (не трогает)

set -euo pipefail

EXT_GDRIVE="$HOME/Library/CloudStorage/SynologyDrive-home/Ext_gDrive"
CM="$EXT_GDRIVE/Claude-Memory"
DRY=${1:-""}

# ── helpers ──────────────────────────────────────────────────────────

do_mkdir() {
  [[ "$DRY" == "--dry-run" ]] && { echo "[DRY] mkdir -p $1"; return; }
  mkdir -p "$1" && echo "✓ mkdir  $1"
}

# Переместить файл/папку с поддержкой case-only rename
do_mv() {
  local src="$1" dst="$2"
  [[ "$DRY" == "--dry-run" ]] && { echo "[DRY] mv '$src' → '$dst'"; return; }
  [[ ! -e "$src" ]] && { echo "⚠ нет '$src' — пропуск"; return; }
  local src_lower="${src:l}" dst_lower="${dst:l}"
  if [[ "$src_lower" == "$dst_lower" ]]; then
    # case-only rename: через временное имя
    local tmp="${src}_mig$$"
    mv "$src" "$tmp" && mv "$tmp" "$dst"
  else
    mv "$src" "$dst"
  fi
  echo "✓ mv  '$src' → '$dst'"
}

# Переместить все файлы из src_dir в dst_dir с lowercase rename
move_files_lower() {
  local src_dir="$1" dst_dir="$2"
  local count=0
  for f in "$src_dir/"*(ND); do
    [[ -d "$f" ]] && continue   # папки пропускаем (не ожидаются)
    local fname="${f:t}" lower="${f:t:l}"
    local dst="$dst_dir/$lower"
    if [[ -e "$dst" ]]; then
      # уже существует — добавить -dup суффикс
      local ext="${lower##*.}" base="${lower%.*}"
      dst="$dst_dir/${base}-dup.${ext}"
      echo "⚠ коллизия — переименую в ${base}-dup.${ext}"
    fi
    do_mv "$f" "$dst"
    count=$(( count + 1 ))
  done
  if [[ $count -eq 0 ]]; then echo "  (папка пуста)"; fi
}

rmdir_safe() {
  local dir="$1"
  [[ "$DRY" == "--dry-run" ]] && { echo "[DRY] rmdir '$dir'"; return; }
  if rmdir "$dir" 2>/dev/null; then
    echo "✓ rmdir '$dir'"
  else
    echo "⚠ '$dir' не пуст — не удалён (проверь вручную)"
  fi
}

echo "============================================================"
echo " Миграция Claude-Memory — Phase 0, Step 4"
echo " Корень: $CM"
[[ "$DRY" == "--dry-run" ]] && echo " *** DRY RUN — ничего не меняется ***"
echo "============================================================"
echo ""

# ── 0. Проверка доступа ──────────────────────────────────────────────
if [[ ! -d "$CM" ]]; then
  echo "❌ '$CM' недоступна. Убедись, что Synology Drive смонтирован."
  exit 1
fi
echo "✓ Synology Drive доступен"
echo ""

# ── 1. Создать новые папки (кроме macro-chain — создаётся в шаге 2) ─
echo "--- 1. Создание новых папок ---"
do_mkdir "$CM/forecast-collections"
do_mkdir "$CM/audits"
do_mkdir "$CM/macro-snapshots"
do_mkdir "$CM/_shared"
do_mkdir "$CM/Portfolio"
do_mkdir "$CM/Portfolio/snapshots"
do_mkdir "$CM/Portfolio/stress"
do_mkdir "$CM/Portfolio/forecasts"
do_mkdir "$CM/Portfolio/weekly-reviews"
do_mkdir "$CM/Portfolio/integrated-views"
do_mkdir "$CM/domains"
echo ""

# ── 2. Macro-Chain/ → macro-chain/ ──────────────────────────────────
# macro-chain/ не создаём заранее: на case-insensitive FS mkdir macro-chain
# вернул бы уже существующую Macro-Chain, и move_files_lower переместила бы
# файлы внутрь той же папки. Вместо этого: переносим файлы в уже-созданный
# macro-chain (если его нет — создаём только после переноса).
echo "--- 2. Macro-Chain/ → macro-chain/ (+ lowercase файлы) ---"
if [[ -d "$CM/Macro-Chain" ]]; then
  # Создаём целевую папку только если её нет И она не совпадает с Macro-Chain
  [[ ! -d "$CM/macro-chain" ]] && do_mkdir "$CM/macro-chain"
  move_files_lower "$CM/Macro-Chain" "$CM/macro-chain"
  rmdir_safe "$CM/Macro-Chain"
else
  echo "⚠ Macro-Chain/ не найдена (уже переименована?)"
fi
echo ""

# ── 3. Portfolio-Stress/ → Portfolio/stress/ ────────────────────────
echo "--- 3. Portfolio-Stress/ → Portfolio/stress/ (+ lowercase) ---"
if [[ -d "$CM/Portfolio-Stress" ]]; then
  move_files_lower "$CM/Portfolio-Stress" "$CM/Portfolio/stress"
  rmdir_safe "$CM/Portfolio-Stress"
else
  echo "⚠ Portfolio-Stress/ не найдена"
fi
echo ""

# ── 4. Sibling Portfolio-Snapshots/ → Portfolio/snapshots/ ──────────
echo "--- 4. Portfolio-Snapshots/ → Claude-Memory/Portfolio/snapshots/ ---"
PS_DIR="$EXT_GDRIVE/Portfolio-Snapshots"
if [[ -d "$PS_DIR" ]]; then
  move_files_lower "$PS_DIR" "$CM/Portfolio/snapshots"
  rmdir_safe "$PS_DIR"
else
  echo "⚠ Portfolio-Snapshots/ не найдена"
fi
echo ""

# ── 5. Sibling Macro-Snapshots/ → macro-snapshots/ ──────────────────
echo "--- 5. Macro-Snapshots/ → Claude-Memory/macro-snapshots/ ---"
echo "   ⚠ Внимание: обнаружены дубликаты RU-2026-05-02.md (1 Google Doc + 2 plain)."
echo "     Дубликаты получат суффикс -dup — разбери вручную после миграции."
MS_DIR="$EXT_GDRIVE/Macro-Snapshots"
if [[ -d "$MS_DIR" ]]; then
  move_files_lower "$MS_DIR" "$CM/macro-snapshots"
  rmdir_safe "$MS_DIR"
else
  echo "⚠ Macro-Snapshots/ не найдена"
fi
echo ""

# ── 6. Sibling Claude-Portfolio/ → Portfolio/ ───────────────────────
echo "--- 6. Claude-Portfolio/ → Claude-Memory/Portfolio/ ---"
CP_DIR="$EXT_GDRIVE/Claude-Portfolio"
if [[ -d "$CP_DIR" ]]; then
  # INDEX.md
  if [[ -f "$CP_DIR/INDEX.md" ]]; then
    if [[ ! -f "$CM/Portfolio/INDEX.md" ]]; then
      do_mv "$CP_DIR/INDEX.md" "$CM/Portfolio/INDEX.md"
    else
      echo "⚠ Portfolio/INDEX.md уже существует — оставляем $CP_DIR/INDEX.md"
    fi
  fi
  # forecasts/ субпапку (portfolio-level/)
  if [[ -d "$CP_DIR/forecasts" ]]; then
    for sub in "$CP_DIR/forecasts/"*(ND); do
      subname="${sub:t}"
      if [[ -d "$sub" ]]; then
        do_mv "$sub" "$CM/Portfolio/forecasts/$subname"
      else
        do_mv "$sub" "$CM/Portfolio/forecasts/${subname:l}"
      fi
    done
    rmdir_safe "$CP_DIR/forecasts"
  fi
  rmdir_safe "$CP_DIR"
else
  echo "⚠ Claude-Portfolio/ не найдена"
fi
echo ""

# ── 7. Domain-папки → domains/ ──────────────────────────────────────
echo "--- 7. Domain-папки → Claude-Memory/domains/ ---"
echo "   (Эти папки не были в списке §9 плана, но нужны по целевой структуре)"
for domain in geopolitics ru-sellside global-banks tech-ceo ru-macro commodity-agencies; do
  if [[ -d "$CM/$domain" ]]; then
    do_mv "$CM/$domain" "$CM/domains/$domain"
  else
    echo "⚠ $domain/ не найдена в корне (уже перемещена?)"
  fi
done
echo ""

# ── 8. _meta-analysis/ — флажок ─────────────────────────────────────
echo "--- 8. _meta-analysis/ ---"
if [[ -d "$CM/_meta-analysis" ]]; then
  echo "⚠ Папка _meta-analysis/ найдена — не трогаем."
  echo "  Это не плановая папка. Содержимое:"
  ls "$CM/_meta-analysis" 2>/dev/null | sed 's/^/    /' || true
  echo "  Реши судьбу вручную."
fi
echo ""

# ── Итог ─────────────────────────────────────────────────────────────
echo "============================================================"
echo " Миграция завершена"
echo "============================================================"
echo ""
echo "Следующие шаги (вручную):"
echo "  1. Разобрать дубликаты в macro-snapshots/*-dup.md"
echo "  2. Решить судьбу _meta-analysis/"
echo "  3. Создать _shared/DEPENDENCY-MAP.md, SOURCE-REGISTRY.md, PERSPECTIVE-MAPS.md"
echo "  4. Создать Portfolio/README.md (если нет)"
echo "  5. Обновить INDEX.md в корне Claude-Memory/"
echo "  6. Обновить _sync_log.md: добавить запись о миграции"
