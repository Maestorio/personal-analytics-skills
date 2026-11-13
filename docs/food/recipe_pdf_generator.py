"""
recipe_pdf_generator.py
Генератор PDF-рецептов в стиле «Венгерский гуляш» (эталон 17.05.2026).
Использует ReportLab + DejaVu Sans (кириллица).

Использование:
    Заполни словарь RECIPE ниже и запусти скрипт.
    PDF сохранится рядом со скриптом под именем, указанным в recipe['filename'].
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import pt
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# ─── ШРИФТЫ ────────────────────────────────────────────────────────────────────
# Укажи путь к TTF-файлам DejaVu Sans.
# Скачать: https://dejavu-fonts.github.io/
# На Ubuntu/Debian обычно: /usr/share/fonts/truetype/dejavu/
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

pdfmetrics.registerFont(TTFont("DejaVu",      FONT_REGULAR))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))

# ─── ЦВЕТА ─────────────────────────────────────────────────────────────────────
DARK_RED        = colors.HexColor("#C0392B")
TABLE_HEADER_BG = colors.HexColor("#922B21")
SECTION_BG      = colors.HexColor("#FEF9E7")
ROW_ALT         = colors.HexColor("#FDFAF0")
ROW_WHITE       = colors.white
TEXT_MAIN       = colors.HexColor("#1A1A1A")
BORDER_COLOR    = colors.HexColor("#CCCCCC")

# ─── СТИЛИ ─────────────────────────────────────────────────────────────────────
def make_styles():
    return {
        "title": ParagraphStyle(
            "title",
            fontName="DejaVu-Bold",
            fontSize=26,
            textColor=DARK_RED,
            alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "meta_key": ParagraphStyle(
            "meta_key",
            fontName="DejaVu-Bold",
            fontSize=10,
            textColor=TEXT_MAIN,
            leading=16,
        ),
        "section": ParagraphStyle(
            "section",
            fontName="DejaVu-Bold",
            fontSize=13,
            textColor=DARK_RED,
            backColor=SECTION_BG,
            spaceBefore=14,
            spaceAfter=8,
            leftIndent=0,
            borderPadding=(5, 6, 5, 6),  # top right bottom left
        ),
        "step_title": ParagraphStyle(
            "step_title",
            fontName="DejaVu-Bold",
            fontSize=11,
            textColor=TEXT_MAIN,
            spaceBefore=8,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="DejaVu",
            fontSize=10,
            textColor=TEXT_MAIN,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=4,
        ),
        "body_left": ParagraphStyle(
            "body_left",
            fontName="DejaVu",
            fontSize=10,
            textColor=TEXT_MAIN,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "table_header": ParagraphStyle(
            "table_header",
            fontName="DejaVu-Bold",
            fontSize=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "table_cell",
            fontName="DejaVu",
            fontSize=10,
            textColor=TEXT_MAIN,
            alignment=TA_LEFT,
        ),
        "source": ParagraphStyle(
            "source",
            fontName="DejaVu",
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            leading=13,
            spaceAfter=2,
        ),
    }

# ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ───────────────────────────────────────────────────
def section_heading(text, styles):
    """Заголовок раздела с цветным фоном."""
    return Paragraph(text, styles["section"])

def ingredients_table(ingredients, col_label, styles, page_width, margin):
    """
    ingredients: список кортежей [("Ингредиент", "Количество"), ...]
    col_label: заголовок второй колонки, например "На 8 порций"
    """
    usable_width = page_width - 2 * margin
    col_widths = [usable_width * 0.65, usable_width * 0.35]

    header = [
        Paragraph("Ингредиент", styles["table_header"]),
        Paragraph(col_label, styles["table_header"]),
    ]
    data = [header]
    for name, amount in ingredients:
        data.append([
            Paragraph(name, styles["table_cell"]),
            Paragraph(amount, styles["table_cell"]),
        ])

    # Зебра: чётные строки (индекс 1,3,5...) — белые, нечётные (2,4,6...) — ROW_ALT
    row_styles = []
    for i in range(1, len(data)):
        bg = ROW_WHITE if i % 2 == 1 else ROW_ALT
        row_styles.append(("BACKGROUND", (0, i), (-1, i), bg))

    table_style = TableStyle([
        # Шапка
        ("BACKGROUND",  (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
        ("FONTNAME",    (0, 0), (-1, 0), "DejaVu-Bold"),
        # Общее
        ("FONTNAME",    (0, 1), (-1, -1), "DejaVu"),
        ("FONTSIZE",    (0, 0), (-1, -1), 10),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Рамки
        ("BOX",         (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("LINEBELOW",   (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ] + row_styles)

    return Table(data, colWidths=col_widths, style=table_style)

# ─── ДАННЫЕ РЕЦЕПТА ────────────────────────────────────────────────────────────
# Замени содержимое этого словаря на данные нового рецепта.

RECIPE = {
    "filename": "Название_блюда.pdf",

    # Шапка
    "title":      "Название блюда",
    "cuisine":    "Национальная кухня",
    "servings":   "X обедов × 2 человека = X порций",
    "time":       "Подготовка: X мин | Приготовление: X мин | Итого: X мин",
    "difficulty": "X из 5",

    # Блок «Выбор ингредиента» — убери ключ целиком если не нужен
    "key_ingredient": {
        "section_title": "Выбор мяса",   # или «Выбор рыбы», «Выбор пасты» и т.д.
        "paragraphs": [
            "Рекомендую: лопатка — оптимальный выбор...",
            "Избегать: грудинка (слишком жирная)...",
        ],
    },

    # Таблица ингредиентов
    "ingredients_col_label": "На X порций",
    "ingredients": [
        ("Ингредиент 1",      "X г"),
        ("Ингредиент 2",      "X мл"),
        ("Соль, чёрный перец","по вкусу"),
    ],

    # Шаги приготовления: список словарей {title, text}
    "steps": [
        {
            "title": "Шаг 1. Подготовка ингредиентов",
            "text":  "Текст шага. Ориентир готовности: ...",
        },
        {
            "title": "Шаг 2. Обжарка",
            "text":  "Текст шага. Температура X°C, время X мин.",
        },
        {
            "title": "Финальная проверка",
            "text":  "Как выглядит готовое блюдо: цвет, текстура, запах.",
        },
    ],

    # Инвентарь — список строк
    "equipment": [
        "Кастрюля 5–6 л с толстым дном",
        "Деревянная или силиконовая лопатка",
    ],

    # Хранение — список строк
    "storage": [
        "В холодильнике: X дней в герметичном контейнере.",
        "Заморозка: да, до X месяцев.",
        "Разогрев: на низком огне со щепоткой воды.",
    ],

    # Примечание (опционально) — убери ключ целиком если не нужен
    "note": {
        "title": "Примечание по жирности",
        "text":  "Охладить блюдо в холодильнике — жир поднимется и легко удалится ложкой.",
    },

    # Советы по подаче — список строк
    "serving": [
        "Гарниры: кнедлики, хлеб, пюре.",
        "Соусы: сметана отдельно в мисочке.",
        "Напиток: Egri Bikavér (венгерское красное).",
    ],

    # Источники — список строк
    "sources": [
        "Классический рецепт без единственного источника.",
    ],

    "date": "ДД.ММ.ГГГГ",
}

# ─── ГЕНЕРАТОР ─────────────────────────────────────────────────────────────────
def build_pdf(recipe, output_path):
    MARGIN = 40 * pt
    PAGE_W, PAGE_H = A4

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )
    styles = make_styles()
    story = []

    # Заголовок
    story.append(Paragraph(recipe["title"], styles["title"]))
    story.append(Spacer(1, 6))

    # Мета-блок
    meta_lines = [
        ("Кухня:",      recipe["cuisine"]),
        ("Порции:",     recipe["servings"]),
        ("Время:",      recipe["time"]),
        ("Сложность:",  recipe["difficulty"]),
    ]
    for key, val in meta_lines:
        story.append(Paragraph(f'<b>{key}</b>  {val}', styles["body_left"]))
    story.append(Spacer(1, 8))

    # Выбор ключевого ингредиента (опционально)
    if "key_ingredient" in recipe:
        ki = recipe["key_ingredient"]
        story.append(section_heading(ki["section_title"], styles))
        for para in ki["paragraphs"]:
            story.append(Paragraph(para, styles["body"]))
        story.append(Spacer(1, 4))

    # Ингредиенты
    story.append(section_heading("Ингредиенты", styles))
    story.append(ingredients_table(
        recipe["ingredients"],
        recipe["ingredients_col_label"],
        styles, PAGE_W, MARGIN
    ))
    story.append(Spacer(1, 10))

    # Приготовление
    story.append(section_heading("Приготовление", styles))
    for step in recipe["steps"]:
        story.append(Paragraph(step["title"], styles["step_title"]))
        story.append(Paragraph(step["text"], styles["body"]))

    # Инвентарь
    story.append(section_heading("Инвентарь", styles))
    for item in recipe["equipment"]:
        story.append(Paragraph(f"• {item}", styles["body_left"]))
    story.append(Spacer(1, 4))

    # Хранение
    story.append(section_heading("Хранение", styles))
    for item in recipe["storage"]:
        story.append(Paragraph(item, styles["body"]))
    story.append(Spacer(1, 4))

    # Примечание (опционально)
    if "note" in recipe:
        story.append(section_heading(recipe["note"]["title"], styles))
        story.append(Paragraph(recipe["note"]["text"], styles["body"]))
        story.append(Spacer(1, 4))

    # Советы по подаче
    story.append(section_heading("Советы по подаче", styles))
    for item in recipe["serving"]:
        story.append(Paragraph(item, styles["body"]))
    story.append(Spacer(1, 4))

    # Источники
    story.append(section_heading("Источники", styles))
    for src in recipe["sources"]:
        story.append(Paragraph(src, styles["source"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Дата создания: {recipe['date']}", styles["source"]))

    doc.build(story)
    print(f"PDF сохранён: {output_path}")


if __name__ == "__main__":
    output = os.path.join(os.path.dirname(__file__), RECIPE["filename"])
    build_pdf(RECIPE, output)
