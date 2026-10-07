"""rk tg-edit <id>:<slug>… — исправить подпись уже вышедшего поста Telegram текстом из post.md (Telegram Web).

Опыт 07.10.2026 (22 поста): в Web K data-mid сообщения канала = 2^32 + номер поста; переход к посту по
#?tgaddr=… срабатывает только при загрузке страницы; пункт «Edit» ищется по последней строке текста (перед словом —
символ иконки); t.me показывает & в адресах как &amp;amp; у всех каналов — раскодируем дважды.
"""
from __future__ import annotations

import argparse
import html as _html
import re
import time
import urllib.parse
import urllib.request

from rk import browser, config, render
from rk import post as P
from rk.cli import register
from rk.connectors.base import Fail
from rk.connectors.telegram_web import SEL, href_fix


def links_from_embed(s: str) -> tuple[list[tuple[str, str]], int]:
    t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', s, re.S)
    b = t.group(1) if t else ""
    links = [(_html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip(), _html.unescape(_html.unescape(m.group(1))))
             for m in re.finditer(r'<a href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)]
    return links, b.count("<b>")


def blank_lines_from_embed(s: str) -> int:
    """Пустые строки между абзацами в подписи по t.me/<канал>/<id>?embed=1; -1 — поста в ответе нет."""
    t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', s, re.S)
    return len(re.findall(r"<br\s*/?>\s*<br\s*/?>", t.group(1))) if t else -1


def blank_lines(channel: str, pid: int) -> int:
    url = f"https://t.me/{channel}/{pid}?embed=1&mode=tme&_={int(time.time())}"
    try:
        s = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    except Exception:  # noqa: BLE001
        return -1
    return blank_lines_from_embed(s.decode("utf-8", "ignore"))


def expected(p, chat: str):
    rich = render.html(p.body, chat)
    links = [(_html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip(), _html.unescape(m.group(1)))
             for m in re.finditer(r'<a href="([^"]+)">(.*?)</a>', rich, re.S)]
    plain = _html.unescape(re.sub(r"<[^>]+>", "", rich))
    return href_fix(rich).replace("\n", "<br>"), plain, links


def published(channel: str, pid: int):
    url = f"https://t.me/{channel}/{pid}?embed=1&mode=tme&_={int(time.time())}"
    s = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
    return links_from_embed(s.decode("utf-8", "ignore"))


def edit(page, channel: str, pid: int, p, chat: str, dry: bool) -> str:
    rich, plain, links = expected(p, chat)
    addr = urllib.parse.quote(f"tg://resolve?domain={channel}&post={pid}", safe="")
    page.goto(f"https://web.telegram.org/k/#?tgaddr={addr}", wait_until="domcontentloaded")
    sel = f'.bubble[data-mid="{2 ** 32 + pid}"]'
    for _ in range(40):
        if page.locator(sel).count():
            break
        page.wait_for_timeout(700)
    else:
        raise Fail(f"пост {pid} не найден на странице")
    page.locator(sel).first.scroll_into_view_if_needed()
    page.wait_for_timeout(800)
    old_first = (page.locator(sel).first.locator(".message").first.inner_text() or "").strip().split("\n")[0][:30]
    page.locator(sel).first.locator(".message").first.click(button="right", position={"x": 20, "y": 10})
    page.wait_for_timeout(700)
    ok = page.evaluate("""() => { for (const e of document.querySelectorAll('.btn-menu-item')) {
        if (!e.offsetParent) continue;
        const last = e.innerText.trim().split('\\n').pop().trim();
        if (last === 'Edit' || last === 'Изменить') { e.click(); return true; } } return false; }""")
    if not ok:
        raise Fail("в меню поста нет пункта «Edit»")
    page.wait_for_timeout(1200)
    box = page.locator(SEL["input"]).first
    cur = (box.inner_text() or "").strip()
    if not old_first or not cur.startswith(old_first):  # иначе «отправить» создаст новый пост вместо правки
        raise Fail("режим правки не включился (в поле нет текста поста) — ничего не отправлено")
    box.click()
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(400)
    page.evaluate(browser.PASTE_HTML_JS, [SEL["input"], rich, plain])
    page.wait_for_timeout(1500)
    st = page.evaluate("""(sel) => { const e = document.querySelector(sel); const t = e.innerText;
        return {len: t.trim().length, first: t.trim().split('\\n')[0], a: e.querySelectorAll('a').length}; }""",
                       SEL["input"])
    if st["first"].strip() != p.title or st["len"] < len(plain.strip()) * 0.95:
        raise Fail(f"текст вставился не так: {st}")
    if dry:
        page.keyboard.press("Escape")
        return f"проверка: {st['len']} зн., ссылок {st['a']} из {len(links)}"
    page.locator(".chat-input .btn-send").first.click()
    end = time.time() + 60
    got: list = []
    while time.time() < end:
        page.wait_for_timeout(4000)
        got, nb = published(channel, pid)
        if got == links:
            return f"исправлено: ссылок {len(got)}, жирного {nb}"
    raise Fail(f"после сохранения ссылки не совпали: {got} ≠ {links}")


def _setup(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("items", nargs="+", help="<номер поста>:<slug>")
    ap.add_argument("--dry", action="store_true")


@register("tg-edit", _setup)
def _cmd(a) -> int:
    cfg = config.load()
    channel = (cfg.platforms.get("tg") or {}).get("channel", "").lstrip("@")
    rc = 0
    with browser.session() as ctx:
        for it in a.items:
            pid, slug = it.split(":", 1)
            p = P.load(P.posts_dir() / slug)
            page = browser.new_page(ctx)  # tgaddr срабатывает только при загрузке страницы
            try:
                print(f"✓ {pid} {slug}: {edit(page, channel, int(pid), p, cfg.chat_link('tg'), a.dry)}", flush=True)
            except Exception as e:  # noqa: BLE001
                rc = 1
                try:
                    page.screenshot(path=str(p.dir / ".tg-edit.png"))
                except Exception:  # noqa: BLE001
                    pass
                print(f"✗ {pid} {slug}: {str(e).splitlines()[0][:200]}", flush=True)
            finally:
                page.close()
    return rc
