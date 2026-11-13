#!/usr/bin/env zsh
set -euo pipefail

CM="$HOME/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory"

echo "=== 1. Дубликат macro-snapshots ==="
# Оригинал ru-2026-05-02.md лучше: есть недельная инфляция (0.05%), модель Sonnet 4.6
rm "$CM/macro-snapshots/ru-2026-05-02 (1).md"
echo "✓ удалён ru-2026-05-02 (1).md"

echo "=== 2. Macro-Chain: убираем -dup суффиксы ==="
mv "$CM/Macro-Chain/macro-input-2026-05-04-dup.yaml" \
   "$CM/Macro-Chain/macro-input-2026-05-04.yaml"
mv "$CM/Macro-Chain/mfc-20260504-prompts-dup.md" \
   "$CM/Macro-Chain/mfc-20260504-prompts.md"
echo "✓ -dup файлы переименованы"

echo "=== 3. Macro-Chain → macro-chain (case-only rename) ==="
mv "$CM/Macro-Chain" "$CM/_Macro-Chain-mig"
mv "$CM/_Macro-Chain-mig" "$CM/macro-chain"
echo "✓ macro-chain/ готово"

echo "=== 4. _meta-analysis/ (пустая) ==="
rmdir "$CM/_meta-analysis"
echo "✓ _meta-analysis/ удалена"

echo "=== 5. Обновление INDEX.md ==="
python3 - "$CM/INDEX.md" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    content = f.read()

# Last sync
content = content.replace(
    'Last sync: 2026-05-04 (Goldman Sachs added)',
    'Last sync: 2026-05-05 (миграция Phase 0, Step 4)'
)
# Subfolder paths: add domains/ prefix
for d in ['geopolitics','ru-sellside','ru-macro','global-banks','commodity-agencies','tech-ceo']:
    content = content.replace(f'| {d} |', f'| domains/{d} |')
content = content.replace('| ru-sellside + ru-macro |',
                          '| domains/ru-sellside + domains/ru-macro |')

# Append updated Cross-references block at end of file
xref_block = """
## Cross-references (обновлено 2026-05-05)

- `retrospective-forecast-audit` → пишет новые файлы в `domains/{domain}/`
- `memory-sync` → читает INDEX, агрегирует frontmatter из `domains/`, обновляет memory
- `_sync_log.md` → лог операций save-to-library и memory-sync
- `macro-chain/` → macro-input YAML (macro-forecast-chain → portfolio-scenario-stress)
- `macro-snapshots/` → ru-{date}.md (macro-ru-watcher → macro-forecast-chain)
- `forecast-collections/` → fc-{source}-collection-{date}.md (forecast-collector)
- `audits/` → {source}-audit-{date}.md (retrospective-forecast-audit)
- `Portfolio/` → портфельная ветка (snapshots, stress, integrated-views, weekly-reviews)
- `_shared/` → DEPENDENCY-MAP, SOURCE-REGISTRY, PERSPECTIVE-MAPS
"""

# Replace old cross-references section if present, else append
if '## Cross-references' in content:
    content = re.sub(r'\n## Cross-references.*', xref_block, content, flags=re.DOTALL)
else:
    content += xref_block

with open(path, 'w') as f:
    f.write(content)
print("✓ INDEX.md обновлён")
PYEOF

echo "=== 6. Обновление _sync_log.md ==="
cat >> "$CM/_sync_log.md" << 'LOGEOF'

---

## Migration 2026-05-05 (Phase 0, Step 4 · migrate-claude-memory.zsh)

- Новые папки: forecast-collections/, audits/, macro-snapshots/, _shared/, Portfolio/(snapshots/stress/forecasts/weekly-reviews/integrated-views/), domains/
- Перемещено: Portfolio-Snapshots/ → Portfolio/snapshots/, Macro-Snapshots/ → macro-snapshots/, Claude-Portfolio/ → Portfolio/, Portfolio-Stress/ → Portfolio/stress/, 6 domain-папок → domains/
- Macro-Chain/ файлы переименованы в lowercase; папка → macro-chain/
- Дубликат macro-snapshots/ru-2026-05-02 (1).md удалён (оставлен оригинал)
- Удалена _meta-analysis/ (пустая)
- Созданы через MCP: _shared/DEPENDENCY-MAP.md, SOURCE-REGISTRY.md, PERSPECTIVE-MAPS.md; Portfolio/README.md
- INDEX.md: пути обновлены (domains/ prefix), cross-references расширены
LOGEOF
echo "✓ _sync_log.md обновлён"

echo ""
echo "=== Готово ==="
echo "Остаток: Portfolio/INDEX.md содержит старые пути (Claude-Portfolio/, UPPER_CASE)"
echo "Ревизия при следующей рабочей сессии."
