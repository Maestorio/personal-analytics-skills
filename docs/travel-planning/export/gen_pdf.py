#!/usr/bin/env python3
"""Generate PDF travel plan for Korea 2024."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import os

# Register fonts
FONT_DIR = "/usr/share/fonts/truetype/dejavu"
pdfmetrics.registerFont(TTFont("DejaVu", f"{FONT_DIR}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", f"{FONT_DIR}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Oblique", f"{FONT_DIR}/DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-BoldOblique", f"{FONT_DIR}/DejaVuSans-BoldOblique.ttf"))
pdfmetrics.registerFontFamily(
    "DejaVu",
    normal="DejaVu",
    bold="DejaVu-Bold",
    italic="DejaVu-Oblique",
    boldItalic="DejaVu-BoldOblique",
)

# Colors
C_DARK = colors.HexColor("#1a1a2e")
C_ACCENT = colors.HexColor("#16213e")
C_BLUE = colors.HexColor("#0f3460")
C_CORAL = colors.HexColor("#e94560")
C_LIGHT = colors.HexColor("#f5f5f5")
C_MID = colors.HexColor("#d0d0d0")
C_WARN = colors.HexColor("#fff3cd")
C_WARN_BORDER = colors.HexColor("#e6a817")
C_HEAD_BG = colors.HexColor("#0f3460")
C_ROW_ALT = colors.HexColor("#eef2f7")
C_GREEN = colors.HexColor("#2d6a4f")
C_OLIVE = colors.HexColor("#f0f7f4")

W, H = A4
MARGIN = 18 * mm
CONTENT_W = W - 2 * MARGIN

# Styles
styles = getSampleStyleSheet()

def S(name, **kw):
    base = kw.pop("parent", "Normal")
    kw.setdefault("fontName", "DejaVu")
    return ParagraphStyle(name, parent=styles[base], **kw)

sTitle   = S("sTitle",   fontSize=22, leading=28, textColor=C_DARK,
             spaceAfter=4, fontName="DejaVu-Bold", alignment=TA_CENTER)
sSubt    = S("sSubt",    fontSize=11, leading=16, textColor=colors.HexColor("#555555"),
             spaceAfter=2, alignment=TA_CENTER)
sH1      = S("sH1",      fontSize=15, leading=20, textColor=colors.white,
             fontName="DejaVu-Bold", spaceAfter=0, spaceBefore=0)
sH2      = S("sH2",      fontSize=12, leading=16, textColor=C_BLUE,
             fontName="DejaVu-Bold", spaceBefore=10, spaceAfter=4,
             borderPad=0)
sH3      = S("sH3",      fontSize=10, leading=14, textColor=C_DARK,
             fontName="DejaVu-Bold", spaceBefore=8, spaceAfter=3)
sNormal  = S("sNormal",  fontSize=9,  leading=13, textColor=C_DARK,
             spaceBefore=2, spaceAfter=2)
sBullet  = S("sBullet",  fontSize=9,  leading=13, textColor=C_DARK,
             leftIndent=12, spaceBefore=1, spaceAfter=1)
sWarn    = S("sWarn",    fontSize=8.5, leading=12, textColor=colors.HexColor("#7a5c00"),
             leftIndent=8)
sSmall   = S("sSmall",   fontSize=8,  leading=11, textColor=colors.HexColor("#666666"))
sMeta    = S("sMeta",    fontSize=8,  leading=12, textColor=colors.HexColor("#888888"),
             alignment=TA_CENTER)
sDayHdr  = S("sDayHdr",  fontSize=10, leading=14, textColor=colors.white,
             fontName="DejaVu-Bold")
sDayBody = S("sDayBody", fontSize=9,  leading=13, textColor=C_DARK)
sCode    = S("sCode",    fontSize=8,  leading=11, textColor=colors.HexColor("#333333"),
             fontName="DejaVu")
sYen     = S("sYen",     fontSize=9,  leading=13, textColor=C_GREEN, fontName="DejaVu-Bold")
sCaption = S("sCaption", fontSize=8,  leading=11, textColor=colors.HexColor("#777777"),
             spaceBefore=0)

def h1_block(text):
    """Section header with colored background."""
    tbl = Table([[Paragraph(text, sH1)]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_HEAD_BG),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return [Spacer(1, 6), tbl, Spacer(1, 6)]

def warn_block(text):
    """Warning/caution box."""
    tbl = Table([[Paragraph("⚠ " + text, sWarn)]], colWidths=[CONTENT_W])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_WARN),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("BOX", (0,0), (-1,-1), 1, C_WARN_BORDER),
    ]))
    return tbl

def budget_pill(text):
    """Small green budget badge inline in day header."""
    return text

def bullet(text):
    return Paragraph("• " + text, sBullet)

def bullets(items):
    return [bullet(t) for t in items]

def day_block(num, date, title, location, hotel, program_items, budget_str, warnings, note=None):
    """Full day block."""
    elements = []
    # Day header row
    hdr_left = Paragraph(f"День {num} — {date}", sDayHdr)
    hdr_right = Paragraph(budget_str, sYen)
    hdr = Table([[hdr_left, hdr_right]], colWidths=[CONTENT_W*0.75, CONTENT_W*0.25])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), C_ACCENT),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    elements.append(hdr)

    # Title + location + hotel
    if title:
        elements.append(Paragraph(title, sH3))
    if location:
        elements.append(Paragraph(f"📍 {location}", sSmall))
    if hotel:
        elements.append(Paragraph(f"🏨 {hotel}", sSmall))
    elements.append(Spacer(1, 3))

    # Program
    for item in program_items:
        elements.append(bullet(item))

    # Warnings
    for w in warnings:
        elements.append(Spacer(1, 3))
        elements.append(warn_block(w))

    if note:
        elements.append(Paragraph(note, sSmall))

    elements.append(Spacer(1, 8))
    return KeepTogether(elements)

def make_table(headers, rows, col_widths, header_bg=C_HEAD_BG):
    data = [[Paragraph(h, ParagraphStyle("th", parent=styles["Normal"],
                       fontName="DejaVu-Bold", fontSize=8, textColor=colors.white,
                       leading=11)) for h in headers]]
    for i, row in enumerate(rows):
        data.append([Paragraph(str(c), ParagraphStyle("td", parent=styles["Normal"],
                               fontName="DejaVu", fontSize=8, textColor=C_DARK,
                               leading=11)) for c in row])
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0,0), (-1,0), header_bg),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("GRID", (0,0), (-1,-1), 0.5, C_MID),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0,i), (-1,i), C_ROW_ALT))
    tbl.setStyle(TableStyle(style))
    return tbl

# ─────────────────────────────────────────────
# PAGE TEMPLATE
# ─────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    # Footer
    canvas.setFont("DejaVu", 7.5)
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.drawString(MARGIN, 10*mm, "Южная Страна А 2024 · 26 марта – 13 апреля · Stage 5 Final Plan")
    canvas.drawRightString(W - MARGIN, 10*mm, f"Стр. {doc.page}")
    # Top accent line
    canvas.setFillColor(C_CORAL)
    canvas.rect(MARGIN, H - 12*mm, CONTENT_W, 1.5, fill=1, stroke=0)
    canvas.restoreState()

# ─────────────────────────────────────────────
# BUILD
# ─────────────────────────────────────────────
output_path = "/mnt/user-data/outputs/korea_2024_final_plan.pdf"
doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    leftMargin=MARGIN, rightMargin=MARGIN,
    topMargin=16*mm, bottomMargin=16*mm,
    title="Южная Страна А 2024 — Финальный план",
    author="travel-planning skill",
)

story = []

# ── TITLE PAGE ──────────────────────────────
story.append(Spacer(1, 20))
story.append(Paragraph("🇰🇷 Южная Страна А", sTitle))
story.append(Paragraph("26 марта – 13 апреля 2024 · 19 дней · 5 регионов", sSubt))
story.append(Paragraph("Финальный план маршрута (Stage 5 · Вариант А)", sSubt))
story.append(HRFlowable(width=CONTENT_W, thickness=2, color=C_CORAL, spaceAfter=10))

# Key params table
kp_data = [
    ["Параметр", "Значение"],
    ["Формат", "Соло, 18 ночей / 19 дней"],
    ["Маршрут", "Сеул → Сораксан → Кёнджу → Пусан → Чонджу → Сеул"],
    ["Темп", "Balanced (3.6 ночи/база)"],
    ["Бюджет in-Korea", "~182 000 ₽ (≈155–215 тыс ₽ диапазон)"],
    ["Бюджет all-in (с перелётом)", "~250–280 000 ₽ · target 257 000 ₽ → on target"],
    ["Курс справочно (март 2024)", "₩1 000 ≈ 69 ₽ · $1 ≈ 92 ₽ ≈ ₩1 340"],
    ["Вариант", "А — города + горы + деревни (сбалансированный)"],
    ["Режим составления", "Reconstructive (ретроспектива, поездка уже состоялась)"],
]
story.append(make_table(
    kp_data[0], kp_data[1:],
    col_widths=[CONTENT_W*0.38, CONTENT_W*0.62]
))
story.append(Spacer(1, 10))

# Key decisions
story.append(Paragraph("Логика ключевых решений", sH2))
story += bullets([
    "Сеул разбит на блок прилёта (2н) и финальный блок (3н) — чистая наземная петля без бэктрека; "
    "финальный Сеул попадает на пик сакуры ~7–13 апреля.",
    "День 5 — погодный буфер на Сораксане: конец марта = остаточный снег/лёд; "
    "буфер позволяет перенести Ульсанбави на ясную погоду.",
    "Переезд Сораксан→Кёнджу (день 6) — узкое звено: восточно-побережный коридор ~7 ч, "
    "несколько пересадок. Swap: через Сеул-хаб при плохих стыковках.",
    "Чеджу не выбран осознанно (тег «можно»): слот отдан Сораксану.",
    "Чинхэ (день 12): сознательный сдвиг после фестиваля — цветение без давки 2.6 млн человек.",
])
story.append(Spacer(1, 4))

# What's NOT in the route
story.append(Paragraph("Исключено из маршрута (осознанно)", sH2))
excluded = [
    ("Чеджу", "тег «можно», выбор в пользу Сораксана"),
    ("Андон", "тег «пропуск» (8 POI: Хахве, Понджонса, Тосан-совон и др.)"),
    ("Кончжу/Пуё (земли Пэкче)", "тег «не интересно»"),
    ("Хянгё Чонджу", "комментарий «скучно»"),
    ("Норэбаны у Тондэмуна + ДМЗ (Сеул)", "комментарий «не интересно / не хочу»"),
]
story.append(make_table(
    ["Место", "Причина исключения"],
    excluded,
    col_widths=[CONTENT_W*0.42, CONTENT_W*0.58]
))

story.append(PageBreak())

# ── CRITICAL PREP ────────────────────────────
story += h1_block("Критические подготовительные пункты")

story.append(Paragraph("Виза и въезд", sH2))
story += bullets([
    "РФ → Республика Страна А: безвизовый въезд до 60 дней.",
    "K-ETA обязателен (Россия НЕ в списке освобождённых) — оформлять на k-eta.go.kr "
    "за ≥72 ч до вылета; сбор ~₩10 000; действует 2 года. TODO: оформить заранее.",
    "Международный перелёт: Москва ↔ Инчхон, стыковочный (Китай / ЦА / Ближний Восток). "
    "~70–100 тыс ₽ — вне total_budget_rub по конвенции home_eq_start: true. "
    "TODO: верифицировать стоимость и транзитные визы стран пересадки.",
    "ICN → центр: экспресс AREX ~₩9 000–11 000, ~50–60 мин до Сеульского вокзала "
    "(last train ~23:40 — при позднем прилёте: лимузин-автобус или такси).",
])

story.append(Paragraph("Деньги", sH2))
story += bullets([
    "Российские карты Visa/Mastercard в Страна А (март 2024) НЕ работают.",
    "Стратегия: везти наличные USD/EUR, менять в Сеуле (Мёндон, Итхэвон) — лучший курс; "
    "аэропортный обменник — хуже.",
    "Купить T-money (киоски CU/GS25, пополнять наличными) — метро, автобусы, часть такси, "
    "мелкие покупки.",
    "Запасной буфер: ~150–200 USD наличными отдельно (медицина, экстренные).",
    "TODO: уточнить, какие карты пользователя работают; заложить наличный буфер.",
])

story.append(Paragraph("SIM / интернет", sH2))
story += bullets([
    "SIM или eSIM с данными — стойки в Инчхоне (KT, SK Telecom) или предзаказ онлайн.",
    "Тур. тариф ~₩20 000–35 000 / 2–4 недели; альтернатива — арендный pocket Wi-Fi.",
    "TODO: выбрать и оформить до вылета или взять в ICN.",
])

story.append(Paragraph("Транспорт внутри страны", sH2))
story += bullets([
    "Весь маршрут — общественный транспорт (прокат авто не нужен).",
    "Билеты на экспресс-автобусы: kobus.co.kr / txbus.t-money.go.kr / Klook.",
    "KTX/SRT: letskorail.com / srail.go.kr.",
    "Korea Rail Pass невыгоден (много автобусов) — покупать посегментно.",
])

story.append(Paragraph("Сезонные риски", sH2))
story.append(warn_block(
    "Конец марта на Сораксане — остаточный снег/лёд на высотных тропах. "
    "Нужна нескользящая обувь, желательно микрошипы."
))
story.append(Spacer(1, 4))

story.append(Paragraph("Бронирования с дедлайном", sH2))
story.append(warn_block(
    "Секретный сад Чхандоккуна — только по таймслотам, лимит 100 чел./сессия "
    "(50 онлайн). Бронь на сайте дворца eng.cdg.go.kr на день 2 — заранее."
))

story.append(PageBreak())

# ── ROUTE BY DAYS ────────────────────────────
story += h1_block("Маршрут по дням")
story.append(Paragraph(
    "💰 в заголовке дня — дневные расходы (входы + еда + локальный транспорт + активности). "
    "Жильё и межгород — в сводной таблице бюджета.",
    sSmall
))
story.append(Spacer(1, 6))

# Day 1
story.append(day_block(
    1, "26.03 Вт", "Старт: Москва → Сеул",
    "Москва → Сеул-Инчхон → AREX → Чонно (~50–60 мин)",
    "Aventree Hotel Jongno, Чонно (ночи 1, 2). Ориентир ~₩80 000–105 000/н (~5 500–7 200 ₽). "
    "Альтернатива: Gongsimga Hanok Guesthouse. TODO: верифицировать.",
    [
        "Вечерняя прогулка без нагрузки (компенсация джетлага): ручей Чхонгечхон, "
        "площадь Кванхвамун, переулки Чонно 3-га.",
        "Ужин рядом с отелем.",
    ],
    "💰 ~₩35 000–50 000 (~2 400–3 400 ₽)",
    ["Прилёт стыковочным рейсом — время плавающее. При позднем прилёте — "
     "только заселение (AREX last train ~23:40)."],
))

# Day 2
story.append(day_block(
    2, "27.03 Ср", "Сеул: дворцы Чосон",
    None, None,
    [
        "09:00–11:30 — Кёнбоккун (경복궁): главный дворец Чосон (1395), крупнейший из пяти. "
        "Павильоны Кёнхверу и Хянвонджон. Вход ₩3 000; смена караула ~10:00. "
        "Комбо-билет ₩10 000 на 4 дворца + Чонмё (действует 3 мес.).",
        "11:30–13:00 — Букчон Ханок Виллидж: квартал чосонских городских ханоков между "
        "двумя дворцами. Лучший свет — утро/день.",
        "14:00–16:30 — Чхандоккун (창덕궁) + Секретный сад Хувон. Объект ЮНЕСКО; "
        "вписан в рельеф. Хувон — только с гидом по таймслоту. Закрыт по понедельникам.",
        "Вечер — Инсадон и Иксондон (старые фасады, новые интерьеры), ужин.",
    ],
    "💰 ~₩40 000–60 000 (~2 800–4 100 ₽)",
    ["Секретный сад без брони — можно не попасть в нужный слот. "
     "Кёнбоккун по вторникам закрыт — день выбран средой намеренно."],
))

# Day 3
story.append(day_block(
    3, "28.03 Чт", "Переезд Сеул → Сораксан / Сокчхо",
    "Сеул → Сокчхо: экспресс-автобус Seoul Express Bus Terminal → Sokcho, "
    "~2 ч 20 мин, каждые ~30 мин, ₩13 000–23 000 (kobus.co.kr).",
    "Hotelaround Sokcho или Chestertons Sokcho, центр. ~₩65 000–90 000/н. "
    "TODO: верифицировать на Booking. (Ночи 3, 4, 5)",
    [
        "Абай-маыль (아바이마을) — район выходцев из Сев. Страна А (Хамгён), "
        "добраться ручным канатным паромом через протоку. Блюдо — абай-сундэ.",
        "Рыбный рынок Сокчхо и набережная.",
        "Павильон Ёнгымджон на скалах — закатная точка.",
    ],
    "💰 ~₩35 000–50 000 (~2 400–3 400 ₽)",
    ["Утренний автобус бронировать накануне (kobus.co.kr) — "
     "в пик-сезон разбирают. До Сораксана от Сокчхо — городские автобусы 7/7-1."],
))

# Day 4
story.append(day_block(
    4, "29.03 Пт", "Сораксан: Синхынса и Ульсанбави",
    "Сокчхо → Сораксан, автобус 7/7-1 (~30 мин). Вход в нацпарк бесплатный.",
    None,
    [
        "Храм Синхынса (один из старейших дзенских) + бронзовая статуя Тхониль Тэбуль.",
        "Тропа на Ульсанбави (울산바위) — шестипиковый гранитный гребень ~873 м. "
        "Маршрут т/о ~6–7.6 км, ~3–4 ч; финальный отрезок — крутые металлические лестницы. "
        "В конце марта возможен снег/лёд — нескользящая обувь + микрошипы.",
        "Опц. при сухой погоде — канатная дорога Квонгымсон (~₩15 000 т/о, ~09:00–17:30). "
        "При ветре закрывается — проверять утром.",
    ],
    "💰 ~₩25 000–40 000 (~1 700–2 800 ₽)",
    ["Туман обнуляет виды; при тумане/наледи — перенести на буфер-день 5, "
     "поменять местами с долинной программой."],
))

# Day 5
story.append(day_block(
    5, "30.03 Сб", "Сораксан: долина Писондэ + погодный буфер",
    None, None,
    [
        "Долинная тропа к скале Писондэ (비선대): ~3 км в одну сторону, ~1 ч 20 мин, "
        "пологий маршрут вдоль ручья — проходим даже при остаточном снеге.",
        "Тропа к водопаду Пирён (Biryong Falls) — ~1.5 ч т/о, умеренные подъёмы.",
        "Функция дня: погодный буфер. Если день 4 сорван погодой — "
        "сюда переносится Ульсанбави.",
    ],
    "💰 ~₩20 000–35 000 (~1 400–2 400 ₽)",
    ["Если погода плохая оба дня — приоритет нижним тропам (Писондэ, Пирён) и канатке; "
     "верхняя программа жертвуется осознанно."],
))

# Day 6
story.append(day_block(
    6, "31.03 Вс", "Переезд Сораксан → Кёнджу (восточный коридор)",
    "Сокчхо → Каннын (~1 ч 15 мин, ₩6 500–10 000) → "
    "Каннын → Пхохан (~4 ч, ₩26 000–34 000) → Пхохан → Кёнджу (~40 мин). "
    "Итого ~6.5–7.5 ч. День уходит на переезд.",
    "Hwangnamkwan Hanok Hotel или Soi Hanok Stay, Хваннам-дон / Хваннидан-гиль. "
    "~₩60 000–90 000/н. TODO: Booking/Klook. (Ночи 6, 7, 8)",
    [
        "Вечером — пруд Вольджи (월지, дворцовый пруд Тоннгун): "
        "подсветка вечером, отражения павильонов. Лучшее время — когда схлынули туристы.",
    ],
    "💰 ~₩45 000–60 000 (~3 100–4 100 ₽)",
    ["Узкое звено: стыковка Каннын→Пхохан — редкие автобусы. "
     "Проверить расписание (bustago.or.kr). Если не складывается → swap: "
     "Сокчхо→Сеул (2 ч 20 мин) + KTX Сеул→Кёнджу (~2 ч)."],
))

# Day 7
story.append(day_block(
    7, "01.04 Пн", "Кёнджу: Пульгукса + грот Соккурам",
    "Из центра — автобус #10/#11 до Пульгукса (~30 мин, ₩1 500), "
    "далее #12 до Соккурама (~20 мин).",
    None,
    [
        "Пульгукса (불국사) — шедевр буддийской архитектуры Силла (528→751). "
        "Пагоды Соккатхап и Таботхап, лестничные мосты Чхонунгё/Пэгунгё VIII в. Объект ЮНЕСКО.",
        "Грот Соккурам (석굴암) — гранитная ротонда ~750 м над морем; "
        "Будда в позе бхумиспарша-мудра, окружён рельефами бодхисаттв. "
        "От парковки ~20 мин пешком с видом на море.",
        "Вход: по состоянию на апрель 2024 — бесплатно (отменена плата). "
        "TODO: верифицировать актуальность. Часы ~07:00–18:00.",
        "Вторая половина дня — чайные/кофейни Хваннидан-гиль.",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["Автобусы #10/#11/#12 — нечастые. Проверить расписание возврата. "
     "Synergy-пара работает только при раннем выезде."],
))

# Day 8
story.append(day_block(
    8, "02.04 Вт", "Кёнджу: исторический кор Силла",
    None, None,
    [
        "Вольджонгё (월정교) — реконструированный мост-павильон Силла через Намчхон; "
        "фотогеничен в мягком свете.",
        "Чхомсондэ (첨성대) — каменная астрономическая башня VII в., "
        "одна из древнейших обсерваторий Восточной Азии.",
        "Тэрынвон (대릉원, парк курганов Силла) и вскрытый курган Чхонмачхон "
        "— ландшафтный транзит.",
        "Вольсон (городище дворца Силла) — проходной осмотр.",
        "Традиционная деревня Кёчхон + улица Хваннидан-гиль. "
        "Опц.: Национальный музей Кёнджу (по вт. открыт).",
    ],
    "💰 ~₩20 000–35 000 (~1 400–2 400 ₽)",
    ["Кёнджу компактен; всё в пешей доступности от ханок-района. Такси дёшевы как резерв."],
))

# Day 9
story.append(day_block(
    9, "03.04 Ср", "Переезд Кёнджу → Пусан",
    "KTX/SRT со ст. Кёнджу, ~30 мин, ₩12 000–37 000.",
    "Ibis Ambassador Busan City Centre, Сомён (пересечение линий метро 1 и 2). "
    "~₩70 000–95 000/н. TODO: Booking. (Ночи 9, 10, 11, 12)",
    [
        "Камчхон Культурная деревня (감천문화마을) — лестничный посёлок на склоне, "
        "дома уступами, переулки и муралы. Плотная городская фактура, фотогенично.",
        "Вечер — Сомён или набережная Кванналли.",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["Поезд бронировать на letskorail.com / srail.go.kr."],
))

# Day 10
story.append(day_block(
    10, "04.04 Чт", "Пусан: Помоса + крепость Кымчжонсансон",
    "Метро линия 1 до ст. Помоса → автобус 90 до храма.",
    None,
    [
        "Храм Помоса (범어사) — основан 678, головной храм ордена Чоге; "
        "сосново-глициниевый лес, ворота Ильчжумун.",
        "Тропа от Помоса к Северным воротам крепости Кымчжонсансон — "
        "стены ~17 км, длиннейшая горная крепость Страна А (Чосон); "
        "виды на Пусан и море. Подъём ~30–90 мин; далее гребневая тропа.",
        "Бесплатный выход, без оператора.",
    ],
    "💰 ~₩20 000–35 000 (~1 400–2 400 ₽)",
    ["Автобус 90 нечастый — проверить расписание. "
     "Тропа маркирована неидеально — оффлайн-карта обязательна."],
))

# Day 11
story.append(day_block(
    11, "05.04 Пт", "Пусан: прибрежная тропа Игидэ + рынки",
    None, None,
    [
        "Утро — прибрежная тропа Игидэ (이기대): скальная тропа по обрывам над морем, "
        "дощатые настилы; виды на залив и Кванан-мост. "
        "Опц.: Орюкто Скайуок (стеклянная площадка).",
        "День — рыбный рынок Чагальчхи + рынок Кукче: уличная еда "
        "(рыба — да; морские гады — нет). Холм Йондуса с обзорной башней.",
        "Опц. вечер — храм Хэдон Йонгунса на скалах у моря (морской буддийский; "
        "добираться дольше).",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["Настилы Игидэ скользкие после дождя — обувь с протектором."],
))

# Day 12
story.append(day_block(
    12, "06.04 Сб", "Пусан: радиал в Чинхэ (сакура после фестиваля)",
    "Пусан → Чинхэ (район Чханвона), автобус ~1 ч.",
    None,
    [
        "Станция Кёнхва — 800 м ж/д путей в коридоре цветущих деревьев, "
        "главная фототочка.",
        "Ручей Ёджвачхон с мостами + парк Чехвансан — закатные виды.",
        "Логика: фестиваль Кунханчже (ориентировочно ~23 марта – 1–3 апреля 2024) "
        "завершился, но цветение держится; толпы 2.6 млн схлынули — "
        "фактура без давки.",
    ],
    "💰 ~₩25 000–40 000 (~1 700–2 800 ₽)",
    ["Цветение непредсказуемо: к 6 апреля может уже облететь. "
     "Swap при отсутствии цветения: Чинхэ даёт ж/д-фактуру Кёнхва и без цвета; "
     "либо переориентировать на Тэджондэ / Хыннёуль / Йонгунса."],
))

# Day 13
story.append(day_block(
    13, "07.04 Вс", "Переезд Пусан → Чонджу",
    "Прямой экспресс-автобус Busan Central (Нопхо) → Jeonju, ~3 ч, "
    "ежечасно, ₩17 000–30 000 (kobus.co.kr). Прямого KTX нет — автобус оптимален.",
    "Ханок-стэй в Чонджу Ханок Виллидж (Jungdam Hanok / Lahan Hotel Jeonju). "
    "~₩50 000–85 000/н. TODO: Booking. (Ночи 13, 14, 15)",
    [
        "Чонджу Ханок Виллидж — крупнейший жилой ханок-квартал Страна А (>800 домов). "
        "Вечерняя прогулка по подсвеченным переулкам без дневных групп.",
        "Собор Чондон (전동성당) — экстерьер вечером: "
        "романская кирпичная церковь на месте казни католических мучеников Чосон. "
        "По вс.: интерьер 09:00–18:00.",
    ],
    "💰 ~₩40 000–55 000 (~2 800–3 800 ₽)",
    ["Автобус из Пусана — с терминала Нопхо (Busan Central Bus Terminal, север города). "
     "Заложить время на метро от Сомёна."],
))

# Day 14
story.append(day_block(
    14, "08.04 Пн", "Чонджу: ханок-квартал вглубь",
    None, None,
    [
        "Святилище Кёнгиджон (경기전, 1410) — хранит портрет короля Тхэджо; "
        "Музей королевских портретов. Вход ₩3 000, 09:00–18:00.",
        "Омокдэ (오목대) — холмовой павильон, обзорная точка на черепичные кровли. "
        "HIDDEN GEM.",
        "Деревня муралов Чаман, ремесленные мастерские, рынок Намбу, переулок макколли.",
        "Кофе — независимые кофейни в ханоках (профильный интерес; Чонджу известен ими).",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["Собор Чондон по понедельникам закрыт (интерьер) — перенесён на день 15."],
))

# Day 15
story.append(day_block(
    15, "09.04 Вт", "Чонджу: Собор Чондон, набережная, буфер",
    None, None,
    [
        "Утро — интерьер Собора Чондон (вторник — открыт): "
        "романский неф, кирпичная кладка; контекст мученичества чосонских католиков. "
        "Рядом — ворота Пуннаммун.",
        "День — павильон Ханбёкдан на прибрежной скале, прогулка по набережной, "
        "кофейни и ремесленные ханоки. Лёгкий темп перед переездом.",
    ],
    "💰 ~₩25 000–40 000 (~1 700–2 800 ₽)",
    ["День сознательно легче — буфер перед переездом и компенсация плотного дня 14."],
))

# Day 16
story.append(day_block(
    16, "10.04 Ср", "Переезд Чонджу → Сеул",
    "KTX со ст. Чонджу (линия Хонам) → Йонсан, ~1 ч 45 мин – 2 ч, ₩34 600. "
    "Замыкает наземную петлю.",
    "Aventree Hotel Jongno (тот же отель, ночи 16, 17, 18).",
    [
        "Дворец Токсугун (덕수궁) + каменная дорога Чондон: "
        "павильоны западной архитектуры рубежа XIX–XX вв., контраст к Кёнбоккуну. "
        "Закрыт по пн; 10.04 среда — открыт.",
        "Опц. святилище Чонмё — конфуцианское королевское святилище, объект ЮНЕСКО "
        "(закрыто по вт; в среду открыто).",
        "Вечер — Сечхон или Кванчжан-рынок.",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["KTX отправляется со ст. Чонджу (не автовокзал) — заложить ~15 мин от ханок-квартала."],
))

# Day 17
story.append(day_block(
    17, "11.04 Чт", "Радиал в Сувон: крепость Хвасон",
    "Сеул → Сувон, электричка/метро линия 1 или пригородный поезд, ~1 ч.",
    None,
    [
        "Крепость Хвасон (수원 화성, 1796) — объект ЮНЕСКО, "
        "образец военной архитектуры с элементами западной фортификации. "
        "Обход по стене ~5.7 км; ворота, бастионы, командные павильоны.",
        "Дворец Хвасон Хэнгун внутри крепостного кольца.",
        "Начало апреля — пик цветения сакуры в Кёнгидо: стена и ручей в цвету.",
        "Возврат в Сеул вечером.",
    ],
    "💰 ~₩25 000–40 000 (~1 700–2 800 ₽)",
    ["При усталости — пройти ключевой участок (Paldalmun → Сонандже) и срезать."],
))

# Day 18
story.append(day_block(
    18, "12.04 Пт", "Сеул: финал — городская стена и сакура",
    None, None,
    [
        "Сеульская городская стена (한양도성), участок Наксан — "
        "прогулка по гребню чосонской стены XIV в. через парк Наксан; "
        "городская панорама, цветение; без туристических толп.",
        "Деревня муралов Ихва на склоне Наксана. "
        "Опц.: возврат в Букчон для фотосъёмки в ином свете.",
        "Вечер — Кванчжан-рынок или Ыльчжиро: уличная еда, последний сеульский вечер.",
    ],
    "💰 ~₩30 000–45 000 (~2 100–3 100 ₽)",
    ["Массовые сакура-споты (Йоыйдо) сознательно не закладываю — толпы. "
     "Стена Наксана даёт цветение и фактуру без давки. "
     "Йоыйдо — опция по желанию."],
))

# Day 19
story.append(day_block(
    19, "13.04 Сб", "Завершение: Сеул → Москва",
    "Сеул → Инчхон (AREX, ~50–60 мин) → стыковочный перелёт в Москву.",
    None,
    [
        "При дневном/вечернем рейсе — утренняя прогулка, кофе рядом с отелем, "
        "последние покупки.",
        "Выезд в ICN с запасом ≥3 ч до международного вылета.",
    ],
    "💰 ~₩20 000–35 000 (~1 400–2 400 ₽)",
    ["Время вылета плавающее — программу подгонять под него. "
     "Регистрация на международный рейс — за 24 ч онлайн."],
))

story.append(PageBreak())

# ── TRANSPORT TABLE ──────────────────────────
story += h1_block("Транспорт: межгородские переезды")

transport_rows = [
    ["ICN → Чонно (д.1)", "Экспресс AREX", "₩9 000–11 000", "~50–60 мин", "T-money / на месте"],
    ["Сеул → Сокчхо (д.3)", "Экспресс-автобус Ko Bus", "₩13 000–23 000", "~2 ч 20 мин", "kobus.co.kr"],
    ["Сокчхо → Кёнджу (д.6)", "Автобус, 2–3 пересадки", "~₩35 000–45 000", "~6.5–7.5 ч", "bustago.or.kr"],
    ["Кёнджу → Пусан (д.9)", "KTX/SRT", "₩12 000–37 000", "~30 мин", "letskorail.com"],
    ["Пусан → Чонджу (д.13)", "Экспресс-автобус Ko Bus", "₩17 000–30 000", "~3 ч", "kobus.co.kr"],
    ["Чонджу → Сеул-Йонсан (д.16)", "KTX линия Хонам", "₩34 600", "~1 ч 45 мин – 2 ч", "letskorail.com"],
    ["Сеул → ICN (д.19)", "Экспресс AREX", "₩9 000–11 000", "~50–60 мин", "T-money / на месте"],
    ["Радиалы (Сораксан, Чинхэ, Сувон)", "Городской транспорт, метро", "₩1 500–15 000/пзд", "—", "T-money"],
]
story.append(make_table(
    ["Участок", "Способ", "Цена/чел.", "Время", "Бронирование"],
    transport_rows,
    col_widths=[CONTENT_W*0.26, CONTENT_W*0.18, CONTENT_W*0.16, CONTENT_W*0.13, CONTENT_W*0.27]
))
story.append(Paragraph(
    "TODO: верифицировать актуальные расписания и цены на даты поездки.",
    sSmall
))

story.append(Spacer(1, 10))

# ── BUDGET TABLE ─────────────────────────────
story += h1_block("Бюджет")
story.append(Paragraph(
    "Расчёт на одного, in-Korea часть (18 ночей / 19 дней). Курс: ₩1 000 ≈ 69 ₽.",
    sSmall
))
story.append(Spacer(1, 4))

budget_rows = [
    ["Жильё (18 ночей)", "~95 000 ₽", "mid-range / ханок, нижняя половина диапазона"],
    ["Внутренний транспорт", "~20 000 ₽", "межгород + метро/автобусы/такси + радиалы"],
    ["Еда (19 дней)", "~52 000 ₽", "~₩35 000–45 000/день"],
    ["Активности и входы", "~8 000 ₽", "дворцы, канатка Сораксан, музеи, баня"],
    ["Прочее (SIM, сувениры, буфер)", "~7 000 ₽", "SIM ~₩20 000–35 000 + резерв"],
    ["ИТОГО in-Korea", "~182 000 ₽", "Диапазон: 155 000–215 000 ₽"],
    ["Международный перелёт (отдельно)", "~70 000–100 000 ₽", "НЕ в total_budget_rub · TODO верифицировать"],
    ["All-in (с перелётом)", "~250 000–280 000 ₽", "Profil target 257 000 ₽ → ON TARGET"],
]

tbl_data = [[Paragraph(h, ParagraphStyle("th2", parent=styles["Normal"],
                        fontName="DejaVu-Bold", fontSize=8,
                        textColor=colors.white, leading=11)) for h in ["Статья", "Сумма", "Комментарий"]]]
for i, row in enumerate(budget_rows):
    is_total = "ИТОГО" in row[0] or "All-in" in row[0]
    style_fn = lambda t, bold=is_total: Paragraph(t, ParagraphStyle(
        "td2", parent=styles["Normal"],
        fontName="DejaVu-Bold" if bold else "DejaVu",
        fontSize=8, textColor=C_DARK if not bold else C_BLUE, leading=11
    ))
    tbl_data.append([style_fn(row[0]), style_fn(row[1]), style_fn(row[2])])

btbl = Table(tbl_data, colWidths=[CONTENT_W*0.32, CONTENT_W*0.20, CONTENT_W*0.48], repeatRows=1)
bstyle = [
    ("BACKGROUND", (0,0), (-1,0), C_HEAD_BG),
    ("TOPPADDING",    (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ("LEFTPADDING",   (0,0), (-1,-1), 5),
    ("RIGHTPADDING",  (0,0), (-1,-1), 5),
    ("GRID", (0,0), (-1,-1), 0.5, C_MID),
    ("VALIGN", (0,0), (-1,-1), "TOP"),
    ("BACKGROUND", (0,5), (-1,5), colors.HexColor("#ddeeff")),
    ("BACKGROUND", (0,7), (-1,7), colors.HexColor("#d4edda")),
    ("BACKGROUND", (0,6), (-1,6), colors.HexColor("#fff3cd")),
]
for i in [2, 4]:
    bstyle.append(("BACKGROUND", (0,i), (-1,i), C_ROW_ALT))
btbl.setStyle(TableStyle(bstyle))
story.append(btbl)

story.append(Spacer(1, 4))
story.append(Paragraph(
    "budget_status: under_target в YAML — формально (сравнивает in-Korea итог ~182k "
    "с all-in target 257k). С учётом перелёта — on_target.",
    sSmall
))

story.append(PageBreak())

# ── GASTRONOMY ───────────────────────────────
story += h1_block("Гастрономия (шпаргалка по городам)")
story.append(Paragraph(
    "Профиль: простая еда, рыбу ест, НЕ ест морские гады (моллюски, ракообразные) и грибы. "
    "Кофе — да; алкоголь — норма.",
    sSmall
))
story.append(Spacer(1, 4))

gastro = [
    ("Сеул", [
        "Кальгуксу и ноль-наби (район Чонно/Кванчжан) — лапша и супы без морских гадов.",
        "Страна А барбекю (самгёпсаль, кальби) — переулки Чонно 3-га.",
        "Кофе — независимые обжарщики Сечхона и Иксондона.",
        "⚠ Хемул-блюда и пиндэтток с устрицами — уточнять состав.",
    ]),
    ("Сокчхо", [
        "Абай-сундэ (колбаса) в Абай-маыль — мясное, без морских гадов.",
        "Даккальби, рыбные блюда; рыбный рынок — выбирать рыбу, не моллюсков/крабов.",
    ]),
    ("Кёнджу", [
        "Ссамбап (рис с овощами и мясом в листьях) — фирменное блюдо.",
        "Хлеб Кёнджу-ппан с красной фасолью; чайные Хваннидан-гиль.",
    ]),
    ("Пусан", [
        "⚠ Пусан — морская кухня; много блюд с моллюсками/крабами.",
        "Безопасны: тведжи-кукпаб (свиной суп), миль-мён (холодная лапша), "
        "уличная еда рынков (рыба на гриле, ходтток).",
    ]),
    ("Чонджу", [
        "Чонджу-пибимпаб — каноничное блюдо (овощи, мясо, яйцо).",
        "Конналь-кукпаб (суп с проростками), переулок макколли.",
    ]),
]

for city, items in gastro:
    story.append(Paragraph(city, sH3))
    story += bullets(items)

story.append(Spacer(1, 4))
story.append(warn_block("При выборе блюд на месте — уточнять отсутствие морских гадов и грибов."))

story.append(PageBreak())

# ── RISK PLAN ────────────────────────────────
story += h1_block("План реагирования на риски")

risk_rows = [
    ["Снег/лёд на Ульсанбави (д.4)", "40–55%",
     "Перенести на буфер-день 5; при наледи оба дня — нижние тропы + канатка."],
    ["Туман на Ульсанбави / Квонгымсон", "35–45%",
     "Перенести на буфер-день; при стойком тумане — долинная программа."],
    ["Канатка Квонгымсон закрыта по ветру", "25–35%",
     "Проверять статус утром; при закрытии — пешая программа."],
    ["Стыковки Каннын→Пхохан не складываются (д.6)", "25–35%",
     "Swap: Сокчхо→Сеул (авт. 2 ч 20 мин) + KTX Сеул→Кёнджу (~2 ч)."],
    ["Чинхэ: цветение облетело к 6 апреля (д.12)", "35–45%",
     "Кёнхва даёт ж/д-фактуру и без цветения; либо переориентировать на Тэджондэ / Йонгунса."],
    ["Сакура в Сеуле/Кёнгидо мимо окна (д.17–18)", "30–40%",
     "Цветение — бонус; программа Хвасон и стены Наксана ценна без сакуры."],
    ["Задержка/сбой стыковочного рейса", "15–25%",
     "Длинные стыковки при покупке; страховка с покрытием задержек."],
    ["Российские карты не работают, нехватка наличных", "20–30%",
     "Достаточный наличный буфер (USD/EUR); T-money для повседневного."],
]
story.append(make_table(
    ["Сценарий", "P", "Действие"],
    risk_rows,
    col_widths=[CONTENT_W*0.38, CONTENT_W*0.07, CONTENT_W*0.55]
))
story.append(Spacer(1, 6))
story.append(Paragraph(
    "Запасные деньги: ~150–200 USD наличными отдельно — медицина и экстренные расходы.",
    sNormal
))
story.append(Paragraph(
    "Контакты: Посольство РФ в Страна А (Сеул) · страховая компания (полис + 24/7 линия) · "
    "туристическая горячая линия Страна А 1330 (англоязычная, 24/7).",
    sNormal
))

story.append(PageBreak())

# ── CHECKLISTS ───────────────────────────────
story += h1_block("Чеклисты")
story.append(Paragraph("За 2 недели до поездки", sH2))
checklist_2w = [
    "Прогноз погоды по регионам (Windy / KMA web.kma.go.kr/eng/)",
    "Статус цветения сакуры — прогнозы KMA / visitkorea.or.kr",
    "Снег/состояние троп Сораксана — english.knps.or.kr",
    "Точные даты фестиваля Чинхэ Кунханчже 2024 — jgfestival.or.kr/eng/",
    "Курсы валют RUB/KRW и USD/KRW — cbr.ru / xe.com",
    "Действительность K-ETA — k-eta.go.kr",
    "Актуальность безвизового режима РФ→Страна А — посольство",
    "Регистрация на международные рейсы за 24 ч",
    "Бронь таймслота Секретного сада Чхандоккуна — eng.cdg.go.kr",
    "Подтверждение броней всех отелей",
    "Расписания межгородских автобусов и KTX — kobus, bustago, letskorail, srail",
    "Оффлайн-карты: Maps.me / Google Maps offline; Naver Map + KakaoMap + Papago",
    "Распечатать маршрутные квитанции и страховой полис",
]
story += bullets(checklist_2w)

story.append(Paragraph("TODO для верификации (за 1–2 месяца)", sH2))
todo_items = [
    "Оформить K-ETA на k-eta.go.kr (≥72 ч до вылета, ~₩10 000)",
    "Международный перелёт Москва ↔ Сеул — верифицировать стоимость, стыковки, транзитные визы",
    "Booking: Aventree Hotel Jongno (ночи 1–2 и 16–18) — рейтинг и цена",
    "Booking: отель в Сокчхо (Hotelaround / Chestertons) — рейтинг и цена",
    "Booking/Klook: ханок в Кёнджу (Hwangnamkwan / Soi Hanok) — рейтинг и цена",
    "Booking: Ibis Ambassador Busan City Centre — рейтинг и цена",
    "Booking: ханок-стэй в Чонджу (Jungdam / Lahan) — рейтинг и цена",
    "Расписания и цены всех межгородских переездов на даты",
    "Выбрать SIM/eSIM — онлайн до вылета или стойка ICN",
    "Наличный буфер: уточнить стратегию (USD/EUR + T-money)",
    "Верифицировать бесплатный вход в Пульгукса и Соккурам",
    "Уточнить дни закрытия дворцов на конкретные даты",
]
story += bullets(todo_items)

# ── FINAL NOTE ───────────────────────────────
story.append(Spacer(1, 16))
story.append(HRFlowable(width=CONTENT_W, thickness=1, color=C_MID))
story.append(Spacer(1, 6))
story.append(Paragraph(
    "Документ сгенерирован: travel-planning skill · Stage 5 Final Plan v1 · "
    "trip_id: страна_а_2024-03 · режим: reconstructive",
    sMeta
))
story.append(Paragraph(
    "Retrospective: true — поездка уже состоялась (март–апрель 2024). "
    "Цены, расписания и часы работы носят справочный характер.",
    sMeta
))

# ── BUILD ────────────────────────────────────
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
print(f"OK: {output_path}")
