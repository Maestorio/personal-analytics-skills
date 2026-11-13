#!/usr/bin/env zsh
# Упаковщик скиллов из skills/<имя>/ в outputs/<имя>.skill (zip).
#
# Архитектура (embed-on-pack):
#   - Канонические shared-файлы лежат в _shared-references/: .md (через shared_refs:
#     → инжектятся в references/) и .py (через bundle_scripts: → инжектятся в scripts/).
#     Кросс-скилл ссылок между scripts/ НЕТ — общий .py всегда из _shared-references/.
#   - skills/<имя>/references/ в репо обычно пуст (или содержит только
#     специфичные для скилла файлы).
#   - Если для конкретного скилла нужна правленая версия канона — положи
#     её полную копию в skills/<имя>/references/<name>.md. Она override'ит
#     канон при упаковке.
#   - Pack делает временную копию скилла, инжектит туда канонические
#     shared-файлы (если их нет в скилле), зипает во временный пакет, сверяет
#     его с outputs/<имя>.skill и заменяет пакет, только если содержимое другое.
#     Репо после запуска не меняется.
#   - Внутри .skill всегда лежит самодостаточная references/ — скилл
#     при развёртывании работает изолированно.
#
# Использование: ./pack.sh <скилл1> [скилл2] ...
#                ./pack.sh            — упаковать только изменившиеся скиллы
#                ./pack.sh --check    — только показать изменившиеся, без упаковки
# Изменившийся = пакета outputs/<имя>.skill нет, или новая сборка отличается от него по содержимому
# (имена и байты файлов внутри zip, без дат). Время файлов — только быстрый фильтр: собираются
# и сверяются лишь скиллы, у которых файл (кроме tests/, __pycache__) или подключённый канон из
# _shared-references/ (shared_refs, bundle_scripts, импорты) новее пакета. git checkout/pull/rebase,
# переписавшие файлы без смены содержимого, упаковки не вызывают: пакет остаётся прежним, ему
# обновляется только время (без --check), чтобы следующий запуск отсеял его фильтром.
# Запускается только из корня репозитория claude_skills.

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$ROOT/skills"
SHARED_DIR="$ROOT/_shared-references"
OUT_DIR="$ROOT/outputs"
PY="${PACK_PYTHON:-$HOME/.pyenv/versions/3.12.9/bin/python3}"

[[ -d "$SKILLS_DIR" ]] || { echo "✗ Папка skills/ не найдена в $ROOT"; exit 1; }
mkdir -p "$OUT_DIR"

extract_shared_refs() {
    local skill_md="$1"
    awk '
        /^---[[:space:]]*$/ { fm = !fm; next }
        fm && /^shared_refs:/ {
            sub(/^shared_refs:[[:space:]]*\[/, "")
            sub(/\][[:space:]]*$/, "")
            gsub(/[[:space:]]/, "")
            n = split($0, arr, ",")
            for (i = 1; i <= n; i++) if (arr[i] != "") print arr[i]
        }
    ' "$skill_md"
}

extract_bundle_scripts() {
    # Парсит `bundle_scripts: [<file.py>, ...]` из frontmatter.
    # Общие python-скрипты с единым каноном лежат в _shared-references/ и встраиваются
    # при упаковке в scripts/ скилла (аналог shared_refs для .md), чтобы .skill был
    # самодостаточным. Источник — ТОЛЬКО _shared-references/ (без кросс-скилл ссылок).
    local skill_md="$1"
    awk '
        /^---[[:space:]]*$/ { fm = !fm; next }
        fm && /^bundle_scripts:/ {
            sub(/^bundle_scripts:[[:space:]]*\[/, "")
            sub(/\][[:space:]]*$/, "")
            gsub(/[[:space:]]/, "")
            n = split($0, arr, ",")
            for (i = 1; i <= n; i++) if (arr[i] != "") print arr[i]
        }
    ' "$skill_md"
}

# Файлы общих модулей, которые импортируют .py в каталоге $1 (с флагом -r — и в подкаталогах), включая
# транзитивные импорты самих общих модулей: _shared-references/<имя>.py и, если есть, <имя>.json (данные модуля).
# Импорт распознаётся по строке `import <имя>` или `from <имя> import` (с отступом — тоже).
shared_import_files() {
    local dir="$1" deep="$2" name
    local -a queue seen files
    [[ -d "$dir" ]] || return 0
    if [[ "$deep" == "-r" ]]; then
        files=("${(@f)$(find "$dir" -name '*.py' ! -path '*/tests/*' ! -path '*/__pycache__/*')}")
    else
        files=("$dir"/*.py(N))
    fi
    (( ${#files} )) || return 0
    queue=($(module_imports "${files[@]}"))
    while (( ${#queue} )); do
        name="${queue[1]}"; queue=("${(@)queue[2,-1]}")
        (( ${seen[(Ie)$name]} )) && continue
        [[ -f "$SHARED_DIR/$name.py" ]] || continue
        seen+=("$name")
        echo "$SHARED_DIR/$name.py"
        [[ -f "$SHARED_DIR/$name.json" ]] && echo "$SHARED_DIR/$name.json"
        queue+=($(module_imports "$SHARED_DIR/$name.py"))
    done
}

# Имена модулей верхнего уровня из строк `import X` / `from X import` в перечисленных файлах.
module_imports() {
    grep -hoE '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' "$@" 2>/dev/null \
        | awk '{print $2}' | sort -u
}

# Сверка двух .skill по содержимому: пусто — одинаковы; иначе первое расхождение
# («+ путь» — появился, «- путь» — пропал, «≠ путь» — другое содержимое). Даты и каталоги не сравниваются.
zip_diff() {
    PYTHONIOENCODING=utf-8 "$PY" -I - "$1" "$2" <<'PYEOF'
import sys, zipfile
try:
    old = zipfile.ZipFile(sys.argv[1])
except zipfile.BadZipFile:
    print("прежний пакет не читается как zip")
    sys.exit(0)
new = zipfile.ZipFile(sys.argv[2])
names_old = {i.filename for i in old.infolist() if not i.is_dir()}
names_new = {i.filename for i in new.infolist() if not i.is_dir()}
for n in sorted(names_old ^ names_new):
    print(("+ " if n in names_new else "- ") + n)
    sys.exit(0)
for n in sorted(names_old):
    if old.read(n) != new.read(n):
        print("≠ " + n)
        sys.exit(0)
PYEOF
}

cleanup() {
    [[ -n "$TMP" && -d "$TMP" ]] && rm -rf "$TMP"
    unset TMP
}
trap cleanup EXIT INT TERM

# Первый изменившийся после пакета файл скилла (путь от корня) или «нет пакета»; пусто — пакет свежий.
# Это быстрый фильтр по времени; окончательное решение — сверка содержимого (zip_diff).
stale_reason() {
    local dir="$1" out="$2" f name src
    [[ -f "$out" ]] || { echo "нет пакета"; return; }
    f="$(find "$dir" -type f -newer "$out" ! -path '*/__pycache__/*' ! -name '*.pyc' \
        ! -name '.DS_Store' ! -path '*/tests/*' | head -1)"
    if [[ -z "$f" ]]; then
        for name in $(extract_shared_refs "$dir/SKILL.md"); do
            [[ -f "$dir/references/$name.md" ]] && continue      # локальная копия уже проверена выше
            src="$SHARED_DIR/$name.md"
            [[ "$src" -nt "$out" ]] && { f="$src"; break; }
        done
    fi
    if [[ -z "$f" ]]; then
        for name in $(extract_bundle_scripts "$dir/SKILL.md"); do
            [[ -f "$dir/scripts/$name" ]] && continue
            src="$SHARED_DIR/$name"
            [[ "$src" -nt "$out" ]] && { f="$src"; break; }
        done
    fi
    if [[ -z "$f" ]]; then
        for src in $(shared_import_files "$dir/scripts" -r); do
            [[ "$src" -nt "$out" ]] && { f="$src"; break; }
        done
    fi
    [[ -n "$f" ]] && echo "${f#$ROOT/}"
    return 0
}

# Собирает пакет скилла $1 во временный $NEWPKG (каталог $TMP). Сообщения о сборке копит в LOG —
# они печатаются, только если пакет действительно заменяется. Ошибка проверки → echo и код 1.
build_pack() {
    local SKILL="$1" SKILL_PATH="$SKILLS_DIR/$1" BUILD SKILL_MD DESC_LEN REFS_DIR SCRIPTS_DIR DEST SRC \
          ref_name spec src INJECTED=0 OVERRIDDEN=0 BUNDLED=0 ADDED
    local -a AUTO
    LOG=()
    TMP="$(mktemp -d)"
    BUILD="$TMP/$SKILL"
    NEWPKG="$TMP/$SKILL.skill"
    cp -R "$SKILL_PATH" "$BUILD"

    SKILL_MD="$BUILD/SKILL.md"
    if [[ -f "$SKILL_MD" ]]; then
        # Загрузчик скиллов отвергает description длиннее 1024 символов — ловим до упаковки.
        # Длина считается по разобранному YAML (а не по строке файла), как её видит загрузчик.
        DESC_LEN="$(PYTHONIOENCODING=utf-8 "$PY" -I - "$SKILL_MD" <<'PYEOF' 2>&1
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
m = re.match(r"---\n(.*?)\n---", s, re.S)
if not m:
    print("ERR: нет YAML frontmatter"); sys.exit(0)
try:
    import yaml
    d = yaml.safe_load(m.group(1)).get("description", "")
except ImportError:
    mm = re.search(r"^description:\s*(.*?)(?=^\S[^\n]*:|\Z)", m.group(1), re.S | re.M)
    d = re.sub(r"\s+", " ", mm.group(1)).strip().strip('"') if mm else ""
except Exception as e:
    print("ERR: frontmatter не разбирается как YAML: " + str(e).splitlines()[0][:120]); sys.exit(0)
if re.search(r"<[^<>]*>", str(d)):
    print("ERR: description содержит угловые скобки (" + re.search(r"<[^<>]*>", str(d)).group(0) + ") — загрузчик отвергает XML-теги"); sys.exit(0)
print(len(str(d)))
PYEOF
)"
        if [[ "$DESC_LEN" == ERR* ]]; then
            echo "✗ $SKILL: $DESC_LEN"; return 1
        elif (( DESC_LEN > 1024 )); then
            echo "✗ $SKILL: description $DESC_LEN символов — лимит загрузки 1024, сократи"; return 1
        fi
        REFS_DIR="$BUILD/references"
        mkdir -p "$REFS_DIR"
        while IFS= read -r ref_name; do
            [[ -z "$ref_name" ]] && continue
            DEST="$REFS_DIR/${ref_name}.md"
            if [[ -f "$DEST" ]]; then
                OVERRIDDEN=$((OVERRIDDEN + 1))
                LOG+=("  • $SKILL: local override for '${ref_name}'")
                continue
            fi
            SRC="$SHARED_DIR/${ref_name}.md"
            if [[ -f "$SRC" ]]; then
                cp "$SRC" "$DEST"
                INJECTED=$((INJECTED + 1))
            else
                echo "  ⚠ $SKILL: shared-ref '${ref_name}' не найден ни локально, ни в $SHARED_DIR"
            fi
        done < <(extract_shared_refs "$SKILL_MD")
        (( INJECTED > 0 )) && LOG+=("  ↻ $SKILL: injected canonical refs: $INJECTED")
        (( OVERRIDDEN > 0 )) && LOG+=("  ✎ $SKILL: kept local overrides: $OVERRIDDEN")

        # Bundle общие python-скрипты из _shared-references/ (embed-on-pack для
        # самодостаточности .skill). Источник только _shared-references/, без кросс-скилл.
        SCRIPTS_DIR="$BUILD/scripts"
        while IFS= read -r spec; do
            [[ -z "$spec" ]] && continue
            DEST="$SCRIPTS_DIR/$spec"
            if [[ -f "$DEST" ]]; then
                LOG+=("  • $SKILL: local script '$spec' (override, не трогаю)")
                continue
            fi
            SRC="$SHARED_DIR/$spec"
            if [[ -f "$SRC" ]]; then
                mkdir -p "$SCRIPTS_DIR"
                cp "$SRC" "$DEST"
                BUNDLED=$((BUNDLED + 1))
            else
                echo "  ⚠ $SKILL: bundle-script '$spec' не найден в _shared-references/ ($SRC)"
            fi
        done < <(extract_bundle_scripts "$SKILL_MD")
        (( BUNDLED > 0 )) && LOG+=("  ⤵ $SKILL: bundled shared scripts: $BUNDLED")

        # Общие модули по импорту: любой `import <имя>` / `from <имя> import …` в scripts/*.py (своём или встроенном
        # выше), для которого есть _shared-references/<имя>.py, кладёт рядом этот модуль и его данные
        # (_shared-references/<имя>.json, если есть: codelists.py → codelists.json) — рекурсивно, пока модули
        # тянут новые (conditions_merge → codelists, time_msk). Свой файл скилла с тем же именем не трогается.
        if [[ -d "$SCRIPTS_DIR" ]]; then
            while :; do
                ADDED=0
                for src in $(shared_import_files "$SCRIPTS_DIR"); do
                    [[ -f "$SCRIPTS_DIR/${src:t}" ]] && continue
                    cp "$src" "$SCRIPTS_DIR/${src:t}"
                    AUTO+=("${src:t}"); ADDED=1
                done
                (( ADDED )) || break
            done
            (( ${#AUTO} )) && LOG+=("  ⤵ $SKILL: bundled shared imports: ${AUTO[*]}")
        fi
    fi

    (cd "$BUILD" && zip -r --quiet "$NEWPKG" . -x "*/__pycache__/*" -x "*.pyc" -x "*/.DS_Store" -x ".DS_Store" -x "*/tests/*" -x "tests/*") \
        && [[ -f "$NEWPKG" ]] || { echo "✗ $SKILL: zip не собрал пакет"; return 1; }
    return 0
}

CHECK_ONLY=0
if (( ! $# )) || [[ "$1" == "--check" ]]; then
    [[ "$1" == "--check" ]] && CHECK_ONLY=1
    CANDIDATES=()
    for dir in "$SKILLS_DIR"/*(/); do
        [[ -f "$dir/SKILL.md" ]] || continue
        [[ -n "$(stale_reason "$dir" "$OUT_DIR/${dir:t}.skill")" ]] && CANDIDATES+=("${dir:t}")
    done
    set -- "${CANDIDATES[@]}"
fi

FAILED=0
CHANGED=()
SAME=()
for SKILL in "$@"; do
    [[ -d "$SKILLS_DIR/$SKILL" ]] || { echo "✗ '$SKILL' не найден в skills/, пропускаю"; continue; }
    if ! build_pack "$SKILL"; then
        FAILED=1; CHANGED+=("$SKILL"); cleanup; continue
    fi
    OUT="$OUT_DIR/${SKILL}.skill"
    if [[ -f "$OUT" ]]; then
        WHY="$(zip_diff "$OUT" "$NEWPKG")"
    else
        WHY="нет пакета"
    fi
    if [[ -z "$WHY" ]]; then
        SAME+=("$SKILL")
        (( CHECK_ONLY )) || touch "$OUT"
        cleanup; continue
    fi
    CHANGED+=("$SKILL")
    if (( CHECK_ONLY )); then
        echo "  ↺ $SKILL: $WHY"
    else
        for line in "${LOG[@]}"; do echo "$line"; done
        mv -f "$NEWPKG" "$OUT"
        echo "✓ $OUT ($WHY)"
    fi
    cleanup
done

(( ${#SAME} )) && echo "  = содержимое пакета не изменилось, пакет оставлен прежним: ${SAME[*]}"
if (( ! ${#CHANGED} )); then
    echo "✓ все пакеты совпадают с исходниками — упаковывать нечего"
elif (( CHECK_ONLY )); then
    echo "изменились: ${CHANGED[*]}"
fi
(( FAILED )) && { echo "✗ упаковка завершена с ошибками"; exit 1; }
exit 0
