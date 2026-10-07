"""Threads через браузер: текст threads.txt (≤500) со ссылкой, до 10 фото. Без приложения Meta и хостинга картинок.

Селекторы — по ARIA-подписям (интерфейс на русском и английском); сверка — см. PLATFORMS.md, раздел Threads.
"""
from __future__ import annotations

from rk import browser, media, render
from rk import post as P
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result
from rk.connectors.telegram_web import media_of

SEL = {
    "create": "[aria-label='Создать'], [aria-label='Create'], [aria-label='Новая ветка'], [aria-label='New thread']",
    "dialog": "[role=dialog]",
    "field": "[role=dialog] [contenteditable='true']",
    "file": "[role=dialog] input[type=file]",
    "login": "a[href*='/login'], [href*='instagram.com/accounts/login']",
}
POST_BTN_JS = """(click) => { const d = document.querySelector('[role=dialog]'); if (!d) return false;
  for (const b of d.querySelectorAll('[role=button], button')) { const t = (b.innerText || '').trim();
    if (/^(Опубликовать|Post)$/.test(t) && b.getAttribute('aria-disabled') !== 'true') { if (click) b.click(); return true; } }
  return false; }"""
FIRST_POST_JS = """(t) => { for (const a of document.querySelectorAll('a[href*="/post/"]')) {
    const box = a.closest('[data-pressable-container], article, div[role=article]') || a.parentElement;
    if (box && box.innerText.includes(t)) return a.href; } return null; }"""


def prepare(text: str, link: str) -> str:
    out = render.short(text, link)
    if len(out) > render.LIMITS["threads"]:
        raise Fail(f"текст Threads {len(out)} из 500 — сократите threads.txt")
    return out


class ThreadsWeb(Connector):
    key = "threads"
    needs_site_link = True
    uses_browser = True
    login_urls = ["https://www.threads.com/login"]

    def login_probe(self):
        return "https://www.threads.com/", SEL["create"]

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        prof = (self.opts.get("profile") or "").lstrip("@")
        if not prof:
            raise Fail("в config не задан platforms.threads.profile")
        raw = P.short(p, "threads")
        if not raw:
            raise Fail("нет threads.txt у новости")
        text = prepare(raw, site_link)
        photos = media.photos(media_of(p))[:10]
        page.goto("https://www.threads.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if not page.locator(SEL["create"]).count():
            raise Fail("нет кнопки «Создать» — нет входа в Threads (rk login threads)")
        page.locator(SEL["create"]).first.click()
        page.locator(SEL["field"]).first.wait_for(state="visible", timeout=20000)
        page.locator(SEL["field"]).first.click()
        n = page.evaluate(browser.PASTE_TEXT_JS, [SEL["field"], text])
        if n < min(60, len(text) // 2):
            raise Fail(f"текст не вставился ({n} зн.)")
        if photos:
            page.locator(SEL["file"]).first.set_input_files([str(x) for x in photos])
            if not browser.wait_js(page, "n => document.querySelectorAll('[role=dialog] img[src^=\"blob:\"], "
                                         "[role=dialog] video').length >= n", 60, len(photos)):
                raise Fail("фото не прикрепились в окне Threads")
        if not browser.wait_js(page, POST_BTN_JS, 30, False):
            raise Fail("кнопка «Опубликовать» неактивна")
        if dry:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            for label in ("Не сохранять", "Don't save", "Удалить", "Discard"):
                b = page.get_by_role("button", name=label)
                if b.count():
                    b.first.click()
                    break
            return Result(url="", note=f"готово к отправке: {n} зн., {len(photos)} фото")
        self.sending()
        page.evaluate(POST_BTN_JS, True)
        page.wait_for_timeout(8000)
        page.goto(f"https://www.threads.com/@{prof}", wait_until="domcontentloaded")
        href = browser.wait_js(page, FIRST_POST_JS, 30, text.splitlines()[0][:40])
        return Result(url=href or f"https://www.threads.com/@{prof}",
                      note=None if href else f"{AFTER_CLICK}: пост на профиле не найден")
