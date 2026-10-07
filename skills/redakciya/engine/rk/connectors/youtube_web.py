"""YouTube — записи сообщества канала через браузер (вход владельца канала). Фото только 2:5…5:2."""
from __future__ import annotations

from rk import browser, media, render
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result
from rk.connectors.telegram_web import media_of

DLG = "ytd-backstage-post-dialog-renderer"
STATE = """() => {
  const sel = document.querySelector('#image-select');
  const err = [...document.querySelectorAll('ytd-backstage-post-dialog-renderer *')].find(e =>
      e.offsetParent && !e.children.length && /не соответству|doesn.t meet/i.test(e.textContent)
      && !e.closest('#contenteditable-root'));
  return {open: !!sel && !sel.hidden,
          imgs: document.querySelectorAll('#thumbnail-drag-drop-area > * img').length,
          err: err ? err.textContent.trim() : ''};
}"""
IMAGE_BTN = """() => {
  const b = [...document.querySelectorAll('ytd-backstage-post-dialog-renderer button, ytd-backstage-post-dialog-renderer [role=button]')]
      .find(b => b.offsetParent && /^\\s*(Изображение|Image)\\s*$/.test(b.innerText));
  if (b) b.click();
  return !!b;
}"""
TEXT = """(t) => {
  const el = document.querySelector('ytd-backstage-post-dialog-renderer #contenteditable-root')
          || document.querySelector('#contenteditable-root');
  if (!el) return -1;
  el.focus(); document.execCommand('selectAll'); document.execCommand('insertText', false, t);
  return el.innerText.trim().length;
}"""
SUBMIT = """(click) => {
  const b = [...document.querySelectorAll('ytd-backstage-post-dialog-renderer button, ytd-backstage-post-dialog-renderer [role=button]')]
      .find(b => b.offsetParent && /^\\s*(Опубликовать|Post)\\s*$/.test(b.innerText));
  const ok = !!b && !b.disabled && b.getAttribute('aria-disabled') !== 'true';
  if (ok && click) b.click();
  return ok;
}"""
FIRST = """() => {
  const p = document.querySelector('ytd-backstage-post-thread-renderer');
  if (!p) return null;
  const a = p.querySelector('a[href*="/post/"]');
  return {text: p.innerText.slice(0, 400), href: a ? a.href : '',
          imgs: p.querySelectorAll('#image-container img, ytd-backstage-image-renderer img').length};
}"""


def split_by_aspect(paths):
    """YouTube отвергает ВСЮ пачку, если хоть одна картинка вне 2:5…5:2."""
    ok = [x for x in paths if media.aspect_ok(x)]
    return ok, [x for x in paths if x not in ok]


class YoutubeWeb(Connector):
    key = "yt"
    uses_browser = True
    login_urls = ["https://accounts.google.com/ServiceLogin?continue=https://www.youtube.com/"]

    def login_probe(self):
        ch = self.opts.get("channel") or ""
        if not ch:
            return None
        # окно записи сообщества видит только владелец канала
        return f"https://www.youtube.com/{ch if ch.startswith('@') else '@' + ch}/posts", DLG

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        ch = self.opts.get("channel")
        if not ch:
            raise Fail("в config не задан platforms.yt.channel (@имя канала)")
        url = f"https://www.youtube.com/{ch if ch.startswith('@') else '@' + ch}/posts"
        text = render.plain(p.body, self.cfg.chat_link("yt") or self.cfg.chat_link("tg"))
        photos, skipped = split_by_aspect(media.photos(media_of(p)))
        photos = [media.shrink(x, 15_000_000, 4096) for x in photos]
        page.on("filechooser", lambda fc: fc.set_files([str(x) for x in photos]))
        page.goto(url, wait_until="domcontentloaded")
        dlg = page.locator(DLG).first
        try:
            dlg.wait_for(state="attached", timeout=45000)
        except Exception:  # noqa: BLE001
            raise Fail("нет окна записи — нет входа владельца канала в YouTube (rk login yt)") from None
        page.wait_for_timeout(4000)

        def yt_input():
            for sel in ("ytd-backstage-multi-image-select-renderer input[type=file][multiple]",
                        "ytd-backstage-multi-image-select-renderer input[type=file]"):
                if page.locator(sel).count():
                    return page.locator(sel).first
            return None
        inp = yt_input() if photos else None
        if inp:  # проверенный порядок: сначала файлы в скрытый input, потом композер и «Изображение»
            inp.set_input_files([str(x) for x in photos])
        try:
            dlg.locator("#contenteditable-root").first.click(timeout=8000)
        except Exception:  # noqa: BLE001
            dlg.click(position={"x": 80, "y": 40})
        page.wait_for_timeout(1500)
        if photos:
            if not page.evaluate(STATE)["open"]:
                page.evaluate(IMAGE_BTN)
            if not browser.wait_js(page, "() => (" + STATE + ")().imgs > 0", 8):
                inp = yt_input()
                if inp:
                    inp.set_input_files([str(x) for x in photos])
            st = browser.wait_js(page, "n => { const s = (" + STATE + ")(); return (s.err || (s.open && s.imgs >= n)) ? s : null; }",
                                 90, len(photos)) or page.evaluate(STATE)
            if st["err"]:
                raise Fail(f"YouTube не принял фото: {st['err']}")
            if not st["open"] or st["imgs"] < len(photos):
                raise Fail(f"фото {st['imgs']} из {len(photos)}")
        n = page.evaluate(TEXT, text)
        if n < min(100, len(text) // 2):
            raise Fail(f"текст не вставился ({n} зн.)")
        if not browser.wait_js(page, SUBMIT, 120, False):
            raise Fail("кнопка «Опубликовать» так и не стала активной")
        skip = f"; пропущены по соотношению сторон: {', '.join(x.name for x in skipped)}" if skipped else ""
        if dry:
            page.evaluate("() => { const el = document.querySelector('#contenteditable-root'); if (el) { el.focus(); "
                          "document.execCommand('selectAll'); document.execCommand('delete'); } }")
            return Result(url="", note=f"готово к отправке: {n} зн., {len(photos)} фото{skip}")
        self.sending()
        page.evaluate(SUBMIT, True)
        got = browser.wait_js(page, "(t) => { const f = (" + FIRST + ")(); return f && f.text.includes(t) ? f : null; }",
                              60, text.splitlines()[0][:40])
        if not got:
            return Result(url=url, note=f"{AFTER_CLICK}: запись не появилась в ленте за минуту")
        note = None if got["imgs"] >= len(photos) else f"в записи {got['imgs']} фото из {len(photos)} — сверить"
        return Result(url=got["href"] or url, note=note)
