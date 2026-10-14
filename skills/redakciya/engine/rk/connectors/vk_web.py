"""VK через браузер: VK-канал (vk.com/im/channels/…) и стена группы без своего приложения VK.

VK-канал проверен на практике: фото строго по одному (пачка встаёт в порядке завершения загрузки), сниппет «Ссылка»
после вставки текста убирается, отправка не раньше чем через 6 с (иначе откат: отрицательный cmid).
"""
from __future__ import annotations

import contextlib

from rk import browser, media, render
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result
from rk.connectors.telegram_web import media_of

CH_STATE = """() => ({
  items: document.querySelectorAll('.ComposerAttaches__item').length,
  tools: document.querySelectorAll('.ComposerAttachTools').length,
  loaders: document.querySelectorAll('.ComposerAttaches__loader').length,
})"""
CH_RETRY = """() => [...document.querySelectorAll('.Loader__button')]
    .filter(b => b.closest('.Loader--retry')).forEach(b => b.click())"""
CH_DROP_LINK = """() => { let n = 0;
  for (const it of document.querySelectorAll('.ComposerAttaches__item'))
    if (/Ссылка|Link/.test(it.innerText)) { const r = it.querySelector('.ComposerAttaches__remove'); if (r) { r.click(); n++; } }
  return n; }"""
CH_LAST = """() => { const a = [...document.querySelectorAll('.PostsList__item')]; const p = a[a.length - 1];
  return p ? {key: p.getAttribute('data-itemkey'), photos: p.querySelectorAll('.PhotoItem').length,
              text: p.innerText.slice(0, 300)} : null; }"""
CH_FIELD = ".ChannelComposer [contenteditable='true']"


def cmid_ok(key) -> bool:
    """Номер сообщения канала: отрицательный — отправка откатилась."""
    return bool(key) and str(key).isdigit()


def ch_clear(page) -> None:
    """Не оставлять черновик: VK хранит недописанный пост и вешает «Покинуть сайт?»."""
    try:
        for _ in range(40):
            n = page.evaluate("() => { const b = [...document.querySelectorAll('.ComposerAttaches__remove')]; "
                              "b.forEach(x => x.click()); return b.length; }")
            if not n:
                break
            page.wait_for_timeout(400)
        page.locator(CH_FIELD).last.click(timeout=5000)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Backspace")
    except Exception:  # noqa: BLE001
        pass


class VkChannel(Connector):
    key = "vkch"
    uses_browser = True
    login_urls = ["https://vk.com/"]

    def login_probe(self):
        return (self.opts["url"], ".ChannelComposer__fileInput") if self.opts.get("url") else None

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        url = self.opts.get("url")
        if not url:
            raise Fail("в config не задан platforms.vkch.url — адрес канала vk.com/im/channels/-<id>")
        text = render.plain(p.body, self.cfg.chat_link("vk"))
        photos = media.photos(media_of(p))
        page.goto(url, wait_until="domcontentloaded")
        inp = page.locator(".ChannelComposer__fileInput").first
        try:
            inp.wait_for(state="attached", timeout=45000)
        except Exception:  # noqa: BLE001
            raise Fail("нет композера канала — нет входа в VK или прав администратора (rk login vkch)") from None
        page.wait_for_timeout(2500)
        if page.evaluate(CH_STATE)["items"]:
            ch_clear(page)
            page.wait_for_timeout(1500)
        retry = lambda: page.evaluate(CH_RETRY)  # noqa: E731
        for i, ph in enumerate(photos, 1):
            for _ in range(2):
                page.evaluate("() => { const i = document.querySelector('.ChannelComposer__fileInput'); if (i) i.value = ''; }")
                inp.set_input_files(str(ph))
                ok = browser.wait_js(page, "n => { const s = (" + CH_STATE + ")(); return s.items >= n && s.tools >= n && !s.loaders; }",
                                     40, i, retry)
                if ok or page.evaluate(CH_STATE)["items"] >= i:
                    break
            else:
                raise Fail(f"фото {i} ({ph.name}) не встало")
        page.locator(CH_FIELD).last.click(timeout=10000)
        n = page.evaluate(browser.PASTE_TEXT_JS, [None, text])
        if n < min(100, len(text) // 2):
            raise Fail(f"текст не вставился ({n} зн.)")
        for pause in (7000, 3000):  # сниппет «Ссылка» появляется через 5–10 с после вставки
            page.wait_for_timeout(pause)
            page.evaluate(CH_DROP_LINK)
        page.wait_for_timeout(1500)
        st = page.evaluate(CH_STATE)
        if st["items"] != len(photos) or st["loaders"]:
            raise Fail(f"вложений {st['items']} вместо {len(photos)} (загружается ещё {st['loaders']})")
        if dry:
            ch_clear(page)
            return Result(url="", note=f"готово к отправке: {n} зн., {st['items']} фото")
        before = page.evaluate(CH_LAST)
        page.wait_for_timeout(6000)  # слишком ранняя отправка откатывается (cmid < 0)
        self.sending()
        page.locator('button[aria-label="Отправить сообщение"], button[aria-label="Send message"]').first.click()
        last = browser.wait_js(page, "([k, t]) => { const l = (" + CH_LAST + ")(); return l && l.key !== k && "
                               "/^[0-9]+$/.test(l.key) && l.text.includes(t) ? l : null; }",
                               40, [before["key"] if before else None, p.title[:40]])
        if not last or not cmid_ok(last.get("key")):
            return Result(url=url, note=f"{AFTER_CLICK}: пост не появился в ленте канала")
        return Result(url=f"{url}?cmid={last['key']}")


# Стена группы через браузер — для тех, кто не хочет заводить приложение VK. Новый интерфейс VK (окно «Новый пост»):
# метки сверены на живой странице группы 07.10.2026. Окно хранит черновики, поэтому --dry в форму ничего не вводит.
WALL = {  # сверены на живой стене 12–14.10.2026
    "create": "[data-testid='group_publish_create_button']",
    "post_item": "[data-testid='group_publish_post_menu_item']",
    "box": "[data-testid='posting_modal_box']",
    "file": "input[data-testid='posting_base_screen_download_from_device']",
    "any_file": "[data-testid='posting_modal_box'] input[type=file]",
    "field": "[data-testid='posting_base_screen_input_message']",
    "next": "[data-testid='posting_base_screen_next']",
    "submit": "[data-testid='posting_submit_button']",
    "close": "[data-testid='modal-close-button']",
}
WALL_STATE = """() => { const box = document.querySelector("[data-testid='posting_modal_box']");
  if (!box) return null;
  return {items: box.querySelectorAll("[data-testid='posting_attachment_item']").length,
          loaders: box.querySelectorAll('[class*=Spinner], [class*=spinner], [role=progressbar]').length,
          text: (box.querySelector("[data-testid='posting_base_screen_input_message']") || {}).innerText || ''}; }"""
WALL_HAS = "n => { const s = (" + WALL_STATE + ")(); return !!s && s.items >= n && !s.loaders; }"
# 12.10.2026: фото сначала встаёт, а через пару секунд VK пишет «Не удалось загрузить фото» и убирает его
WALL_TOAST_FAIL = """() => { const t = [...document.querySelectorAll('body *')].filter(e => e.children.length === 0
    && e.offsetParent && /Не удалось загрузить|Failed to upload/.test(e.textContent));
  t.forEach(e => { const c = e.closest('[role=alert], [class*=Snackbar], [class*=snackbar]'); if (c) c.remove(); });
  return t.length; }"""
WALL_REMOVE_ONE = """() => { const b = [...document.querySelectorAll("[data-testid='posting_modal_box'] [data-testid*=_item_remove], "
    + "[data-testid='posting_modal_box'] [data-testid*=attachment_remove]")];
  b.slice(0, 1).forEach(x => x.click()); return b.length; }"""
WALL_RESET_INPUTS = """() => document.querySelectorAll("[data-testid='posting_modal_box'] input[type=file]")
    .forEach(i => { i.value = ''; })"""
# сниппет ссылки, который VK сам добавляет к тексту, — убрать (как в канале)
WALL_DROP_LINK = """() => { let n = 0;
  for (const it of document.querySelectorAll("[data-testid='posting_modal_box'] [data-testid='posting_attachment_item']")) {
    if (it.querySelector('[data-sortable-id^=photo], [data-sortable-id^=video]')
        || it.closest('[data-sortable-id^=photo], [data-sortable-id^=video]')) continue;
    const r = it.querySelector('[data-testid*=remove]'); if (r) { r.click(); n++; } }
  return n; }"""
PUBLISH_BTN_JS = """() => { for (const b of document.querySelectorAll('button')) {
    const t = (b.innerText || '').trim(); if (b.offsetParent && /^(Опубликовать|Publish)$/.test(t)) { b.click(); return true; } }
  return false; }"""
WALL_TRIES = 3   # на файл; со второй попытки — копия 1600, потом 1280 px (VK молча отбрасывал отдельные JPEG)


class VkWall(Connector):
    key = "vk"
    uses_browser = True
    retry_safe = False   # «Опубликовать» могло сработать — повтор дал бы дубль
    login_urls = ["https://vk.com/"]

    def login_probe(self):
        gid = self.opts.get("group_id")
        return (f"https://vk.com/club{abs(int(gid))}", WALL["create"]) if gid else None

    def _open(self, page, gid):
        page.goto(f"https://vk.com/club{gid}", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        tc = self.opts.get("title_check")
        if tc and tc.lower() not in (page.title() or "").lower():
            raise Fail(f"открыто не то сообщество: «{(page.title() or '')[:60]}» — ничего не вставлено")
        if not page.locator(WALL["create"]).count():
            raise Fail("в группе нет кнопки «Создать» — нет входа в VK или прав редактора (rk login vk)")
        page.locator(WALL["create"]).first.scroll_into_view_if_needed()
        page.locator(WALL["create"]).first.click()
        page.wait_for_timeout(1200)
        if page.locator(WALL["post_item"]).count():
            page.locator(WALL["post_item"]).first.click()
        else:
            page.get_by_text("Пост", exact=True).first.click()
        page.locator(WALL["box"]).first.wait_for(state="visible", timeout=20000)
        page.wait_for_timeout(2500)
        st = page.evaluate(WALL_STATE) or {}
        if st.get("items") or st.get("text", "").strip():  # VK хранит недописанный пост — начинаем с чистого окна
            self._clear(page)

    def _clear(self, page) -> None:
        for _ in range(40):
            if not page.evaluate(WALL_REMOVE_ONE):
                break
            page.wait_for_timeout(500)
        f = page.locator(WALL["field"])
        if f.count():
            f.first.click()
            page.keyboard.press("ControlOrMeta+a")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(500)

    def _upload(self, page, files) -> None:
        """По одному файлу: пачка встаёт в порядке завершения загрузки, а отброшенное фото видно только так."""
        for i, f in enumerate(files, 1):
            video = str(f).lower().endswith(media.VIDEO)
            for attempt in range(WALL_TRIES):
                src = f if attempt == 0 or video else media.shrink(f, 1, 1600 if attempt == 1 else 1280)
                inp = page.locator(WALL["file"])
                if i > 1 or not inp.count():
                    inp = page.locator(WALL["any_file"])
                page.evaluate(WALL_RESET_INPUTS)
                inp.first.set_input_files(str(src))
                browser.wait_js(page, WALL_HAS, 900 if video else 40, i)
                page.wait_for_timeout(5000)
                failed = page.evaluate(WALL_TOAST_FAIL)
                have = (page.evaluate(WALL_STATE) or {}).get("items", 0)
                if have > i:
                    raise Fail(f"после файла {i} в окне {have} вложений — дубль, ничего не опубликовано")
                if have == i and failed:  # тост мог быть от этого файла, но он на месте — проверить ещё раз
                    page.wait_for_timeout(3000)
                    failed = (page.evaluate(WALL_STATE) or {}).get("items", 0) != i
                if have == i and not failed:
                    break
                print(f"  vk-web: {f.name}: попытка {attempt + 1} не удалась (в окне {have} вложений)", flush=True)
            else:
                raise Fail(f"файл {i} ({f.name}) не встал за {WALL_TRIES} попытки — ничего не опубликовано")
            page.wait_for_timeout(1500)

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        gid = abs(int(self.opts.get("group_id") or 0))
        if not gid:
            raise Fail("в config не задан platforms.vk.group_id")
        text = render.plain(p.body, self.cfg.chat_link("vk"))
        files = media_of(p)[:10]
        self._open(page, gid)
        try:
            self._upload(page, files)
            page.locator(WALL["field"]).first.click()
            n = page.evaluate(browser.PASTE_TEXT_JS, [WALL["field"], text])
            if n < min(100, len(text) // 2):
                raise Fail(f"текст не вставился ({n} зн.)")
            for pause in (6000, 3000):
                page.wait_for_timeout(pause)
                page.evaluate(WALL_DROP_LINK)
            st = page.evaluate(WALL_STATE) or {}
            if st.get("items") != len(files):
                raise Fail(f"в окне вложений {st.get('items')} вместо {len(files)} — ничего не опубликовано")
        except Exception:
            with contextlib.suppress(Exception):
                self._clear(page)  # не оставлять черновик с файлами: следующий пост начнётся с чистого окна
            raise
        if dry:
            self._clear(page)
            with contextlib.suppress(Exception):
                page.locator(WALL["close"]).first.click()
            return Result(url="", note=f"собрано и убрано: {len(text)} зн., {len(files)} медиа (стена через браузер)")
        page.locator(WALL["next"]).first.click()
        page.wait_for_timeout(2500)
        submit = page.locator(WALL["submit"])
        if not submit.count() and not browser.wait_js(page, PUBLISH_BTN_JS.replace("b.click(); return true", "return true"), 30):
            raise Fail("после «Далее» нет кнопки «Опубликовать» — VK сменил вёрстку, см. снимок")
        self.sending()
        if submit.count():
            submit.first.click()
        else:
            page.evaluate(PUBLISH_BTN_JS)
        page.wait_for_timeout(6000)
        href = page.evaluate("(t) => { for (const post of document.querySelectorAll('[data-testid=post]')) { "
                             "if (post.innerText.includes(t)) { const a = post.querySelector('a[href*=\"wall-\"]'); "
                             "if (a) return a.href; } } return null; }", p.title[:40])
        return Result(url=href or f"https://vk.com/club{gid}", note=None if href else f"{AFTER_CLICK}: ссылка на пост не найдена")
