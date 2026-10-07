"""Дзен: (1) tg_import — Дзен сам забирает посты Telegram-канала (настройка в Дзен Студии), публиковать нечего;
(2) web — пост в студии Дзена через браузер (бета: селекторы по текстам кнопок, сверка — PLATFORMS.md).
"""
from __future__ import annotations

from rk import browser, journal, media, render
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result
from rk.connectors.telegram_web import media_of


class DzenTgImport(Connector):
    key = "dzen"

    def check(self) -> str:
        return ("Дзен импортирует посты из Telegram сам: Дзен Студия → Настройки канала → «Импорт из Telegram» "
                "(один раз, см. PLATFORMS.md)")

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        if not journal.has(p.dir, "tg"):
            raise Fail("Дзен импортирует из Telegram — сначала должна выйти публикация tg")
        return Result(url=f"https://dzen.ru/{self.opts.get('channel', '')}".rstrip("/"))


CLICK_TEXT_JS = """(names) => { for (const e of document.querySelectorAll('button, [role=button], a')) {
    const t = (e.innerText || e.getAttribute('aria-label') || '').trim();
    if (e.offsetParent && names.includes(t)) { e.click(); return t; } } return null; }"""


class DzenWeb(Connector):
    key = "dzen"
    uses_browser = True
    login_urls = ["https://dzen.ru/"]

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        ch = self.opts.get("channel")
        if not ch:
            raise Fail("в config не задан platforms.dzen.channel")
        text = render.plain(p.body, self.cfg.chat_link("dzen") or self.cfg.chat_link("tg"))
        photos = media.photos(media_of(p))[:10]
        page.goto("https://dzen.ru/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if page.evaluate("() => [...document.querySelectorAll('button, a')].some(e => e.offsetParent && "
                         "(e.innerText || '').trim() === 'Войти')"):
            raise Fail("нет входа в Дзен (rk login dzen)")
        if not page.evaluate(CLICK_TEXT_JS, ["Создать", "Написать", "Опубликовать"]):
            raise Fail("нет кнопки «Создать» — откройте Дзен Студию вручную и сверьте PLATFORMS.md")
        page.wait_for_timeout(1500)
        if not page.evaluate(CLICK_TEXT_JS, ["Пост", "Написать пост", "Новый пост"]):
            raise Fail("в меню «Создать» нет пункта «Пост»")
        field = page.locator("[contenteditable='true']").first
        field.wait_for(state="visible", timeout=20000)
        field.click()
        n = page.evaluate(browser.PASTE_TEXT_JS, [None, text])
        if n < min(100, len(text) // 2):
            raise Fail(f"текст не вставился ({n} зн.)")
        if photos:
            page.locator("input[type=file]").first.set_input_files([str(x) for x in photos])
            page.wait_for_timeout(3000 + 1500 * len(photos))
        if dry:
            page.keyboard.press("Escape")
            return Result(url="", note=f"готово к отправке: {n} зн., {len(photos)} фото (Дзен через браузер, бета)")
        if not page.evaluate(CLICK_TEXT_JS.replace("e.click(); return t", "return t"), ["Опубликовать"]):
            raise Fail("нет кнопки «Опубликовать»")
        self.sending()
        page.evaluate(CLICK_TEXT_JS, ["Опубликовать"])
        page.wait_for_timeout(8000)
        return Result(url=f"https://dzen.ru/{ch}", note=f"{AFTER_CLICK}: ссылку на пост Дзена сверить в канале")
