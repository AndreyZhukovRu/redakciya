"""X (Twitter) через браузер: текст x.txt со ссылкой на сайт/Telegram, до 4 фото.

Ссылка на вышедший твит берётся по совпадению текста в ленте профиля, а не «самый свежий» — лента запаздывает,
и при серии постов ссылки съезжали на соседний твит (проверено 07.10.2026).
"""
from __future__ import annotations

from rk import browser, media, render
from rk import post as P
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result
from rk.connectors.telegram_web import media_of

X_STATE = """() => {
  const el = document.querySelector('[data-testid=tweetTextarea_0]');
  const b = document.querySelector('[data-testid=tweetButtonInline]');
  return {len: el ? el.innerText.trim().length : 0,
          imgs: document.querySelectorAll('[data-testid=attachments] img').length,
          disabled: !b || b.disabled || b.getAttribute('aria-disabled') === 'true'};
}"""
X_FEED = """() => [...document.querySelectorAll('article')].map(a => {
  const t = a.querySelector('time'); const l = t && t.closest('a'); const x = a.querySelector('[data-testid=tweetText]');
  return {href: l ? l.href : '', text: x ? x.innerText : ''}; }).filter(x => x.href)"""


def pick_tweet(feed: list[dict], text: str) -> str | None:
    """Твит, чьё начало совпадает с нашим текстом (по общей длине, но не меньше 15 знаков и не больше 40)."""
    ours = text.strip()
    for t in feed:
        theirs = t.get("text", "").strip()
        n = min(40, len(ours), len(theirs))
        if n >= 15 and theirs[:n] == ours[:n]:
            return t["href"]
    return None


class XWeb(Connector):
    key = "x"
    needs_site_link = True
    uses_browser = True
    login_urls = ["https://x.com/login"]

    def login_probe(self):
        return "https://x.com/home", '[data-testid="tweetTextarea_0"]'

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        prof = (self.opts.get("profile") or "").lstrip("@")
        if not prof:
            raise Fail("в config не задан platforms.x.profile")
        raw = P.short(p, "x")
        if not raw:
            raise Fail("нет x.txt у новости")
        text = render.short(raw, site_link)
        photos = [media.shrink(x, 4_800_000) for x in media.photos(media_of(p))[:4]]
        page.goto("https://x.com/home", wait_until="domcontentloaded")
        box = page.locator('[data-testid="tweetTextarea_0"]').first
        try:
            box.wait_for(state="visible", timeout=45000)
        except Exception:  # noqa: BLE001
            raise Fail("нет поля твита — нет входа в X (rk login x)") from None
        page.wait_for_timeout(1500)
        if photos:
            inp = page.locator('input[data-testid="fileInput"]')
            if not inp.count():
                inp = page.locator('input[type="file"][accept*="image"]')
            inp.first.set_input_files([str(x) for x in photos])
            if not browser.wait_js(page, "n => document.querySelectorAll('[data-testid=attachments] img').length >= n",
                                   90, len(photos)):
                raise Fail(f"фото не прикрепились ({page.evaluate(X_STATE)['imgs']} из {len(photos)})")
        box.click()
        page.evaluate(browser.PASTE_TEXT_JS, ['[data-testid="tweetTextarea_0"]', text])
        page.wait_for_timeout(3000)
        st = page.evaluate(X_STATE)
        if st["len"] < min(40, len(text) // 2):
            raise Fail(f"текст не вставился ({st['len']} зн.)")
        if st["disabled"]:
            raise Fail("кнопка «Опубликовать» неактивна — текст длиннее 280?")
        if dry:
            page.locator('[data-testid="tweetTextarea_0"]').first.click()
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Backspace")
            return Result(url="", note=f"готово к отправке: {st['len']} зн., {st['imgs']} фото")
        self.sending()
        page.locator('[data-testid="tweetButtonInline"]').click()
        if not browser.wait_js(page, "() => { const el = document.querySelector('[data-testid=tweetTextarea_0]');"
                                     " return !el || el.innerText.trim().length < 2; }", 60):
            return Result(url=f"https://x.com/{prof}", note=f"{AFTER_CLICK}: поле не очистилось")
        for _ in range(5):  # свежий пост на профиле иногда появляется только со второй загрузки
            page.wait_for_timeout(3000)
            page.goto(f"https://x.com/{prof}", wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            href = pick_tweet(page.evaluate(X_FEED), text)
            if href:
                return Result(url=href)
        return Result(url=f"https://x.com/{prof}", note=f"{AFTER_CLICK}: твит с этим текстом на профиле не найден")
