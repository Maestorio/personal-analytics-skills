#!/usr/bin/env python3
"""
fetch_awd.py — обход BPC-challenge на forum.awd.ru
Stdlib only. Парсит phpBB-разметку и извлекает первый пост.

Usage:
    python3 fetch_awd.py <URL>
    python3 fetch_awd.py --batch urls.txt
    python3 fetch_awd.py --json <URL>     # JSON output для скрипта-обёртки
"""
import sys, re, json, gzip, time, argparse, html
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS_BASE = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

def _read(resp):
    raw = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")

def fetch_awd(url, timeout=20, max_attempts=3):
    """GET с обходом BPC. Возвращает HTML строки."""
    cookies = {}
    current_url = url
    for attempt in range(max_attempts):
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers = dict(HEADERS_BASE)
        if cookie_header:
            headers["Cookie"] = cookie_header
        req = Request(current_url, headers=headers)
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = _read(resp)
        except HTTPError as e:
            if e.code != 429:
                raise
            body = _read(e)
        # Проверяем challenge
        m_cookie = re.search(r'document\.cookie\s*=\s*"([^"=]+)=([^";]+)"', body)
        m_redir = re.search(r'document\.location\.href\s*=\s*"([^"]+)"', body)
        if m_cookie and m_redir:
            cookies[m_cookie.group(1)] = m_cookie.group(2)
            current_url = html.unescape(m_redir.group(1))
            time.sleep(1.5)  # вежливый ритм для phpBB
            continue
        return body
    raise RuntimeError(f"BPC challenge не пробит за {max_attempts} попыток")

class FirstPostExtractor(HTMLParser):
    """Извлекает первый пост из phpBB-разметки awd.ru."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_first_post = False
        self.in_post_body = False
        self.in_postauthor = False
        self.in_postdate = False
        self.in_title = False
        self.post_count = 0
        self.depth = 0
        self.body_depth = None
        self.author = ""
        self.date = ""
        self.title = ""
        self.body_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class", "") or ""
        if tag == "title":
            self.in_title = True
            return
        # phpBB postbody — div.postbody внутри div.post
        if tag == "div" and "post " in (cls + " "):
            self.post_count += 1
            if self.post_count == 1:
                self.in_first_post = True
        if self.in_first_post:
            if tag == "div" and "postbody" in cls:
                self.in_post_body = True
                self.body_depth = self.depth
            if tag in ("a", "span") and "username" in cls.lower():
                self.in_postauthor = True
            if tag == "p" and "author" in cls:
                self.in_postauthor = True
            if self.in_post_body:
                self.depth += 1
                # картинки — пропускаем
                if tag in ("img",):
                    pass
                elif tag == "br":
                    self.body_parts.append("\n")
                elif tag == "p":
                    self.body_parts.append("\n\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.in_post_body:
            self.depth -= 1
            if self.depth <= 0:
                self.in_post_body = False
                self.in_first_post = False
        if tag in ("a", "span", "p") and self.in_postauthor:
            self.in_postauthor = False

    def handle_data(self, data):
        if self.in_title and not self.title:
            self.title = data.strip()
        if self.in_postauthor and not self.author:
            t = data.strip()
            if t and not t.startswith("Сообщение"):
                self.author = t
        if self.in_post_body:
            self.body_parts.append(data)

def extract_all_posts(html_str):
    """Парсит все посты со страницы: список dict {author, date, body}."""
    posts = []
    # Каждый пост: <p class="author">...</p> + ниже <div class="postbody">
    # Используем split по <p class="author"> чтобы не путаться в quote-блоках.
    chunks = re.split(r'(?=<p class="author">)', html_str)
    for ch in chunks[1:]:
        # author + date
        m_au = re.search(
            r'<p class="author">.*?<strong>\s*<a [^>]*memberlist\.php[^>]*>([^<]+)</a>\s*</strong>\s*&raquo;\s*([^<]+?)</p>',
            ch, re.DOTALL)
        if not m_au:
            continue
        # body — первый postbody до postprofile/back2top/signature
        m_bd = re.search(
            r'<div[^>]*class="postbody"[^>]*>(.+?)</div>\s*(?=<dl class="postprofile"|<dl class="attachbox"|<div class="back2top"|<div class="signature)',
            ch, re.DOTALL)
        if not m_bd:
            m_bd = re.search(r'<div[^>]*class="content"[^>]*>(.+?)</div>', ch, re.DOTALL)
        body = m_bd.group(1) if m_bd else ""
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        body = re.sub(r'</p>', '\n\n', body, flags=re.IGNORECASE)
        # Цитаты — компактно
        body = re.sub(r'<blockquote[^>]*>', '\n> ', body, flags=re.IGNORECASE)
        body = re.sub(r'</blockquote>', '\n', body, flags=re.IGNORECASE)
        body = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*>', r'[img:\1]', body)
        body = re.sub(r'<img[^>]*>', '[img]', body)
        body = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', r'\2 (\1)', body)
        body = re.sub(r'<[^>]+>', '', body)
        body = html.unescape(body)
        body = re.sub(r'\n{3,}', '\n\n', body).strip()
        posts.append({
            "author": html.unescape(m_au.group(1)).strip(),
            "date":   html.unescape(m_au.group(2)).strip(),
            "body":   body,
        })
    return posts

def get_page_count(html_str):
    """Кол-во страниц по пагинации awd.ru (posts_per_page=50)."""
    starts = [int(s) for s in re.findall(
        r'viewtopic\.php\?t=\d+(?:&amp;sid=[^&]+)?&amp;start=(\d+)', html_str)]
    if not starts:
        return 1
    return max(starts) // 50 + 1

def fetch_all_pages(base_url, max_pages=20):
    """Прогон по всем страницам темы. base_url — без &start=."""
    # обрезаем &start= если есть
    base_url = re.sub(r'&start=\d+', '', base_url).rstrip('&?')
    sep = '&' if '?' in base_url else '?'
    all_posts = []
    page = 0
    page_count = None
    while True:
        url = base_url if page == 0 else f"{base_url}{sep}start={page*50}"
        html_str = fetch_awd(url)
        posts = extract_all_posts(html_str)
        all_posts.extend(posts)
        if page_count is None:
            page_count = get_page_count(html_str)
        page += 1
        if page >= page_count or page >= max_pages:
            break
        time.sleep(2)  # вежливость между страницами
    return all_posts

def extract_author_profile(html_str):
    """Парсит первый <dl class="postprofile"> — данные автора первого поста.
    Возвращает dict с полями Город, Возраст, Пол, Регистрация, Сообщения,
    Страны, Отчёты и любыми другими, что найдёт в формате <strong>Key:</strong> Value."""
    m = re.search(r'<dl class="postprofile"[^>]*>(.+?)</dl>', html_str, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    # Внутри <dd><strong>Key:</strong> Value</dd>
    out = {}
    for fm in re.finditer(
            r'<dd[^>]*>\s*<strong>([^<:]+)\s*:\s*</strong>(.+?)</dd>',
            block, re.DOTALL):
        key = html.unescape(fm.group(1)).strip()
        val_raw = fm.group(2)
        # Чистим теги, &nbsp;
        val = re.sub(r'<[^>]+>', '', val_raw)
        val = html.unescape(val).replace('\xa0', ' ').strip()
        val = re.sub(r'\s+', ' ', val)
        out[key] = val
    return out

def extract_phpbb(html_str):
    """Тонкий regex-парс — устойчивее HTMLParser для phpBB."""
    out = {"url": None, "title": "", "author": "", "date": "", "body": ""}
    # title
    m = re.search(r"<title>([^<]+)</title>", html_str, re.IGNORECASE)
    if m:
        title = html.unescape(m.group(1)).strip()
        title = re.sub(r"\s*[•·]\s*Форум Винского.*$", "", title)
        out["title"] = title.strip()
    # первый блок post-author и postbody
    # phpBB: <p class="author"><a href="...">USER</a></p>... <strong>Заголовок: ...</strong>... Сообщение: дата
    # phpBB awd.ru: первый <p class="author"> с автором в <strong><a memberlist...>NICK</a></strong> &raquo; ДАТА
    m_first = re.search(
        r'<p class="author">.*?<strong>\s*<a [^>]*memberlist\.php[^>]*>([^<]+)</a>\s*</strong>\s*&raquo;\s*([^<]+?)</p>',
        html_str, re.DOTALL)
    if m_first:
        out["author"] = html.unescape(m_first.group(1)).strip()
        out["date"] = html.unescape(m_first.group(2)).strip()
    # тело — первый div.postbody / div.content
    m_body = re.search(
        r'<div[^>]*class="postbody"[^>]*>(.+?)</div>\s*(?=<dl class="postprofile"|<dl class="attachbox"|<div class="back2top"|<div class="signature)',
        html_str, re.DOTALL)
    if not m_body:
        m_body = re.search(
            r'<div[^>]*class="content"[^>]*>(.+?)</div>',
            html_str, re.DOTALL)
    # Профиль автора
    out["author_profile"] = extract_author_profile(html_str)
    if m_body:
        body = m_body.group(1)
        # Чистка: <br> → \n, <p> → \n\n, теги долой
        body = re.sub(r'<br\s*/?>', '\n', body, flags=re.IGNORECASE)
        body = re.sub(r'</p>', '\n\n', body, flags=re.IGNORECASE)
        body = re.sub(r'<img[^>]*alt="([^"]*)"[^>]*>', r'[img:\1]', body)
        body = re.sub(r'<img[^>]*>', '[img]', body)
        body = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>([^<]*)</a>', r'\2 (\1)', body)
        body = re.sub(r'<[^>]+>', '', body)
        body = html.unescape(body)
        # Сжать пустые строки
        body = re.sub(r'\n{3,}', '\n\n', body).strip()
        out["body"] = body
    return out

def process(url, all_posts=False, author_only=False, max_pages=20):
    if not all_posts:
        html_str = fetch_awd(url)
        data = extract_phpbb(html_str)
        data["url"] = url
        data["html_size"] = len(html_str)
        return data
    # all_posts: все страницы, посты автора первого поста (если author_only)
    posts = fetch_all_pages(url, max_pages=max_pages)
    if not posts:
        return {"url": url, "error": "no posts found"}
    first_author = posts[0]["author"]
    # title — из первого fetch уже не сохранён, перезаберём через extract_phpbb
    # дешевле: берём заголовок из первого fetch HTML
    html0 = fetch_awd(url)
    title_m = re.search(r"<title>([^<]+)</title>", html0, re.IGNORECASE)
    title = ""
    if title_m:
        title = re.sub(r'\s*[•·]\s*Форум Винского.*$', '', html.unescape(title_m.group(1))).strip()
    author_profile = extract_author_profile(html0)
    selected = [p for p in posts if (not author_only or p["author"] == first_author)]
    body_combined = "\n\n--- [пост от {a} | {d}] ---\n\n".format(
        a=first_author, d=posts[0]["date"])
    body_combined = ""
    for p in selected:
        body_combined += f"\n\n--- [{p['author']} | {p['date']}] ---\n\n{p['body']}"
    return {
        "url": url,
        "title": title,
        "author": first_author,
        "author_profile": author_profile,
        "date": posts[0]["date"],
        "posts_total": len(posts),
        "posts_by_author": len(selected),
        "body": body_combined.strip(),
    }


def list_subforums(query=None, parent_url="https://forum.awd.ru/"):
    """Список subforum'ов с фильтром по подстроке в названии (регистронезависимо)."""
    html_str = fetch_awd(parent_url)
    items = re.findall(
        r'<a [^>]*href="\./viewforum\.php\?f=(\d+)[^"]*"[^>]*class="forumtitle"[^>]*>([^<]+)</a>',
        html_str)
    out = []
    for fid, name in items:
        name = html.unescape(name).strip()
        if query is None or query.lower() in name.lower():
            out.append({"f": fid, "name": name})
    return out

def find_subforum_by_topic(topic_url):
    """Из URL темы достать breadcrumbs subforum'ов (от верха к низу)."""
    html_str = fetch_awd(topic_url)
    crumbs = re.findall(
        r'<a [^>]*href="\./viewforum\.php\?f=(\d+)[^"]*"[^>]*>([^<]+)</a>',
        html_str)
    seen, out = set(), []
    for fid, name in crumbs:
        if fid in seen:
            continue
        seen.add(fid)
        out.append({"f": fid, "name": html.unescape(name).strip()})
    return out

def list_topics(f_id, pages=1, filters=None):
    """Список тем subforum'а. filters — список regex для фильтра по заголовку (AND).
    Возвращает [{t, title}, ...]."""
    out = []
    for page in range(pages):
        start = page * 25
        url = f"https://forum.awd.ru/viewforum.php?f={f_id}"
        if start:
            url += f"&start={start}"
        html_str = fetch_awd(url)
        items = re.findall(
            r'<a [^>]*href="\./viewtopic\.php\?[^"]*?t=(\d+)[^"]*"[^>]*class="topictitle"[^>]*>([^<]+)</a>',
            html_str)
        for tid, title in items:
            title = html.unescape(title).strip()
            if filters:
                if not all(re.search(f, title, re.IGNORECASE) for f in filters):
                    continue
            out.append({"t": tid, "title": title,
                        "url": f"https://forum.awd.ru/viewtopic.php?t={tid}"})
        if len(items) < 25 and page < pages - 1:
            break  # последняя страница
        time.sleep(1.5)
    return out


def _child_subforums(html_str):
    """Дочерние subforum'ы со страницы viewforum.php (для категорий)."""
    items = re.findall(
        r'<a [^>]*href="\./viewforum\.php\?f=(\d+)[^"]*"[^>]*class="forumtitle"[^>]*>([^<]+)</a>',
        html_str)
    return [{"f": fid, "name": html.unescape(n).strip()} for fid, n in items]

# --- Выбор reports-subforum скорингом названия (страно-независимо) -----------
# У страны на awd.ru несколько детей: травелоги (отчёты+фото) и планирование
# («помогите с маршрутом») лежат в РАЗНЫХ subforum'ах, и слово «отзыв» есть в
# обоих. Поэтому не «первый с отчёт|отзыв», а максимум по баллу названия.
# Калибровка: Китай f=247 «…впечатления, отчёты и фото» ≈ +8 (нужен) vs
# f=911 «Маршруты… советы, планирование и отзывы» ≈ −7 (ловушка).
_REPORTS_POS = {
    "отчёт": 3, "отчет": 3, "впечатлен": 2, "рассказ": 2,
    "фото": 2, "дневник": 2, "путешеств": 1,
}
_REPORTS_NEG = {
    "маршрут": -3, "планирован": -3, "вопрос": -3, "совет": -2,
    "подготовк": -2, "организац": -2, "виз": -3, "транспорт": -3,
    "отел": -3, "деньги": -3, "связь": -3, "таможн": -3,
    "медицин": -3, "шоп": -3, "ресторан": -2, "достоприм": -1,
    # `виз` ловит виза/визы/визовый; `шоп` — шопинг/шоппинг; `ресторан` —
    # инфо-ветки «Шопинг и рестораны», чтобы они не зависали на 0 и не
    # попадали в тай-кластер с настоящей travelogue-веткой.
}


def score_reports_subforum(name):
    """Балл «это ветка отчётов, а не планирования/инфо». >0 — кандидат.

    Слово «отзыв» — слабый неоднозначный сигнал (+1): есть и в травелог-, и
    в планировочной ветке, не должен решать исход в одиночку.
    """
    n = name.lower()
    score = 0
    for k, v in _REPORTS_POS.items():
        if k in n:
            score += v
    for k, v in _REPORTS_NEG.items():
        if k in n:
            score += v
    if "отзыв" in n:
        score += 1
    return score


def _report_ratio(f_id):
    """Доля отчётных заголовков на первой странице subforum'а (тай-брейк).

    Травелог-ветка даёт ratio заметно выше планировочной. Сетевой вызов —
    зовётся только при близких баллах двух кандидатов.
    """
    topics = list_topics(f_id, pages=1)
    if not topics:
        return 0.0
    q = re.compile(r"помог|подскаж|прош|вопрос|критик|планир|оптимиз|\?$",
                   re.IGNORECASE)
    rep = re.compile(r"отчёт|отчет|дневник|как мы|вернул|съезди|побыва|"
                     r"впечатл|за \d+ дн|\d{4}", re.IGNORECASE)
    good = sum(1 for t in topics
               if rep.search(t["title"]) and not q.search(t["title"]))
    return good / len(topics)


def pick_reports_subforum(children, tie_threshold=1):
    """Выбрать дочерний reports-subforum скорингом названия.

    Возвращает dict child + поля `score` и `selected_by`
    ('score' | 'score+ratio'), либо None если ни один кандидат не набрал >0.
    При близких баллах топ-кластера (разница ≤ tie_threshold) — тай-брейк по
    эмпирической доле отчётных заголовков первой страницы (§4.2 памятки).
    """
    scored = [(c, score_reports_subforum(c["name"])) for c in children]
    cands = sorted([(c, s) for c, s in scored if s > 0],
                   key=lambda cs: cs[1], reverse=True)
    if not cands:
        return None
    best_score = cands[0][1]
    cluster = [cs for cs in cands if best_score - cs[1] <= tie_threshold]
    if len(cluster) > 1:
        cluster.sort(key=lambda cs: _report_ratio(cs[0]["f"]), reverse=True)
        chosen, chosen_score = cluster[0]
        selected_by = "score+ratio"
    else:
        chosen, chosen_score = cands[0]
        selected_by = "score"
    out = dict(chosen)
    out["score"] = chosen_score
    out["selected_by"] = selected_by
    return out


def discover_reports(country_query, filter_patterns=None, pages=3, max_results=20):
    """Авто-discovery отчётов по стране.

    1. Найти country-level subforum по подстроке.
    2. Прочитать его страницу — если в нём есть темы, использовать его.
       Иначе найти дочерний subforum с 'отчёт|отзыв' в названии.
    3. Перечислить темы reports-subforum с опц. regex-фильтром.

    Возвращает dict:
        {"country_forum": {f, name}, "reports_forum": {f, name},
         "topics": [{t, title, url}, ...]}

    Кидает ValueError если ничего не нашлось.
    """
    # 1. country forum
    subs = list_subforums(country_query)
    if not subs:
        raise ValueError(f"Не нашёл subforum по запросу '{country_query}'. "
                         f"Попробуй --list-subforums без аргумента и поищи руками.")
    # Берём первый совпавший, предпочитая ALL-CAPS country-level
    country = next((s for s in subs if s['name'].upper().startswith(country_query.upper())), subs[0])

    # 2. читаем страницу country forum
    url = f"https://forum.awd.ru/viewforum.php?f={country['f']}"
    html_str = fetch_awd(url)
    own_topics_count = len(re.findall(
        r'<a [^>]*href="\./viewtopic\.php\?[^"]*?t=\d+[^"]*"[^>]*class="topictitle"[^>]*>',
        html_str))
    children = _child_subforums(html_str)

    if own_topics_count >= 10:
        # У самого country forum есть свои темы — используем его
        reports = dict(country)
        reports["selected_by"] = "own_topics"
    else:
        # Выбираем дочерний reports-subforum СКОРИНГОМ названия, а не первым
        # совпавшим по «отчёт|отзыв» (иначе ловушка-планировочная ветка с
        # «отзывы» в названии перехватывает выбор — см. discovery-памятку).
        reports = pick_reports_subforum(children)
        if reports is None:
            raise ValueError(
                f"У subforum '{country['name']}' (f={country['f']}) нет ни своих "
                f"тем (n={own_topics_count}), ни дочернего травелог-subforum по "
                f"скорингу названия. Дочерние: "
                + ", ".join(f"f={c['f']} '{c['name']}'" for c in children[:8]))

    # 3. list_topics
    topics = list_topics(reports['f'], pages=pages, filters=filter_patterns)
    return {
        "country_forum": country,
        "reports_forum": reports,
        "topics": topics[:max_results],
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("url", nargs="?")
    p.add_argument("--batch", help="файл со списком URL по одному на строку")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--max-body", type=int, default=0,
                   help="обрезать body до N символов (0 = не обрезать)")
    p.add_argument("--all-posts", action="store_true",
                   help="собрать все посты темы со всех страниц (по умолчанию — только первый)")
    p.add_argument("--author-only", action="store_true",
                   help="с --all-posts: оставить только посты автора первого поста (рекомендуется для travel-отчётов)")
    p.add_argument("--max-pages", type=int, default=20,
                   help="макс. число страниц при --all-posts (по умолч. 20)")
    p.add_argument("--list-subforums", metavar="QUERY", nargs="?", const="",
                   help="перечислить subforum'ы (опц. фильтр по подстроке)")
    p.add_argument("--breadcrumbs", metavar="TOPIC_URL",
                   help="из темы достать breadcrumbs (родительские subforum'ы)")
    p.add_argument("--list-topics", metavar="F_ID",
                   help="перечислить темы subforum'а f=ID")
    p.add_argument("--discover-reports", metavar="COUNTRY",
                   help="одной командой: найти reports-subforum страны + перечислить темы. "
                        "Использовать с --filter и --pages. Пример: --discover-reports вьетнам --filter 'Сапа|Хойан'")
    p.add_argument("--max-results", type=int, default=20,
                   help="макс. число тем в --discover-reports (по умолч. 20)")
    p.add_argument("--pages", type=int, default=1,
                   help="сколько страниц брать для --list-topics")
    p.add_argument("--filter", action="append", default=[],
                   help="regex-фильтр заголовков (можно несколько, AND)")
    args = p.parse_args()

    if args.list_subforums is not None:
        res = list_subforums(args.list_subforums or None)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for r in res:
                print(f"f={r['f']:>5}  {r['name']}")
        sys.exit(0)

    if args.breadcrumbs:
        res = find_subforum_by_topic(args.breadcrumbs)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for r in res:
                print(f"f={r['f']:>5}  {r['name']}")
        sys.exit(0)

    if args.discover_reports:
        try:
            res = discover_reports(args.discover_reports,
                                    filter_patterns=args.filter,
                                    pages=args.pages,
                                    max_results=args.max_results)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"Country forum: f={res['country_forum']['f']} '{res['country_forum']['name']}'")
            _rf = res['reports_forum']
            _basis = _rf.get("selected_by", "?")
            _sc = f", score={_rf['score']}" if _rf.get("score") is not None else ""
            print(f"Reports forum: f={_rf['f']} '{_rf['name']}' "
                  f"[выбран: {_basis}{_sc}]")
            print(f"Topics ({len(res['topics'])}):")
            for t in res['topics']:
                print(f"  t={t['t']:>6}  {t['title']}")
        sys.exit(0)

    if args.list_topics:
        res = list_topics(args.list_topics, pages=args.pages, filters=args.filter)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"Найдено: {len(res)}")
            for r in res:
                print(f"  t={r['t']:>6}  {r['title']}")
        sys.exit(0)


    if args.batch:
        urls = [l.strip() for l in open(args.batch) if l.strip() and not l.startswith("#")]
    elif args.url:
        urls = [args.url]
    else:
        p.error("нужен URL или --batch")

    results = []
    for u in urls:
        try:
            r = process(u, all_posts=args.all_posts, author_only=args.author_only,
                        max_pages=args.max_pages)
            if args.max_body and r.get("body"):
                r["body"] = r["body"][:args.max_body]
            results.append(r)
        except Exception as e:
            results.append({"url": u, "error": str(e)})
        time.sleep(2)  # вежливость

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"\n{'='*80}")
            print(f"URL:    {r['url']}")
            if "error" in r:
                print(f"ERROR:  {r['error']}")
                continue
            print(f"TITLE:  {r.get('title','')}")
            print(f"AUTHOR: {r.get('author','')}")
            print(f"DATE:   {r.get('date','')}")
            if 'posts_total' in r:
                print(f"POSTS:  {r['posts_by_author']} из {r['posts_total']} (only author of first post)")
            else:
                print(f"SIZE:   {r.get('html_size','?')} bytes HTML, body {len(r.get('body',''))} chars")
            ap = r.get('author_profile') or {}
            if ap:
                interesting = ['Город', 'Возраст', 'Пол', 'Регистрация', 'Сообщения', 'Страны', 'Отчеты', 'Отчёты']
                pdata = [f"{k}={ap[k]}" for k in interesting if k in ap]
                print(f"PROFILE: {' | '.join(pdata) if pdata else ap}")
            print(f"--- BODY ---\n{r.get('body','')[:1500]}\n...")
