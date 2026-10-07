"""Telegram через Telegram Web (web.telegram.org/k) в профиле публикатора — без api_id, вход по QR.

Проверено на канале 07.10.2026: альбом через file chooser в порядке post.md (фото и видео), подпись — вставка HTML;
жирный, ссылки и пустые строки сохраняются, подпись до 4096 зн. при Telegram Premium. Перед вставкой проверяется
название канала — в чужой чат ничего не уходит.
"""
from __future__ import annotations

import html as _html
import re
import time
import urllib.request

from rk import browser, media, render
from rk.connectors.base import AFTER_CLICK, Connector, Fail, Result

SEL = {  # сверены на живой странице 07.10.2026 (интерфейс Web K на английском)
    "input": '.chat-input .input-message-input:not(.input-field-input-fake)[contenteditable="true"]',
    "peer_title": ".chat-info .peer-title",
    "qr": ".page-signQR, .page-sign",
    "attach": ".attach-file",
    "attach_media": ".btn-menu-item:has(.tgico-image), .btn-menu-item:has-text('Фото'), .btn-menu-item:has-text('Photo')",
    "popup": ".popup-new-media",
    "caption": '.popup-new-media .input-message-input[contenteditable="true"]',
    "popup_send": ".popup-new-media .btn-primary",
}

STATE_JS = """() => {
  const pop = document.querySelector('.popup-new-media');
  const cap = pop && pop.querySelector('.input-message-input[contenteditable="true"]');
  return {popup: !!pop,
          len: cap ? cap.innerText.trim().length : 0,
          bold: cap ? cap.querySelectorAll('b, strong, [data-markup="markup-bold"]').length : 0,
          links: cap ? cap.querySelectorAll('a').length : 0,
          first: cap ? cap.innerText.trim().split('\\n')[0] : ''};
}"""


def chat_ok(header: str, expected: str) -> bool:
    return bool(header.strip()) and expected.lower() in header.lower()


def href_fix(rich: str) -> str:
    """Telegram Web берёт адрес из href как есть: &amp; внутри href надо вернуть в &."""
    return re.sub(r'href="([^"]+)"', lambda m: 'href="' + m.group(1).replace("&amp;", "&") + '"', rich)


def last_post_from_html(s: str) -> tuple[int, str]:
    best = (0, "")
    for m in re.finditer(r'data-post="[^"/]+/(\d+)"(.*?)(?=data-post=|\Z)', s, re.S):
        pid = int(m.group(1))
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', m.group(2), re.S)
        if t and pid > best[0]:
            txt = re.sub(r"<br\s*/?>", "\n", t.group(1))
            best = (pid, _html.unescape(re.sub(r"<[^>]+>", "", txt)).strip().split("\n")[0])
    return best


def media_of(p) -> list:
    files = list(p.media)[:10]
    missing = [str(m) for m in files if not m.exists()]
    if missing:
        raise Fail(f"нет файлов: {', '.join(missing)}")
    return [media.ensure_audio(m) if str(m).lower().endswith(media.VIDEO) else m for m in files]


class TelegramWeb(Connector):
    key = "tg"
    uses_browser = True
    login_urls = ["https://web.telegram.org/k/"]

    def _channel(self) -> str:
        ch = re.sub(r"^(https?://)?(t\.me|telegram\.me)/(s/)?", "", str(self.opts.get("channel") or "").strip())
        ch = ch.strip("/").lstrip("@")
        if not ch:
            raise Fail("в config не задан platforms.tg.channel")
        return ch

    def _title(self) -> str:
        t = self.opts.get("title_check")
        if not t:
            raise Fail("в config не задан platforms.tg.title_check — часть названия канала для проверки")
        return t

    def last_post(self) -> tuple[int, str]:
        req = urllib.request.Request(f"https://t.me/s/{self._channel()}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            return last_post_from_html(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore"))
        except OSError as e:  # URLError, HTTPError, таймаут
            raise Fail(f"лента t.me/s/{self._channel()} не открылась ({e}) — нужен публичный канал с @username "
                       "и доступ к t.me") from None

    def check(self) -> str:
        ch, tc = self._channel(), self._title()
        req = urllib.request.Request(f"https://t.me/s/{ch}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            s = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        except OSError as e:
            raise Fail(f"t.me/s/{ch} не открылась ({e}) — нужен публичный канал с @username") from None
        m = re.search(r'og:title" content="([^"]*)', s)
        name = _html.unescape(m.group(1)) if m else ""
        if "tgme_channel_info" not in s or not name:
            raise Fail(f"@{ch}: публичной ленты нет — нужен публичный канал с @username и включённым превью")
        if tc.lower() not in name.lower():
            raise Fail(f"название канала «{name}» не совпало с title_check «{tc}» — поправьте config")
        return f"канал @{ch} «{name}»"

    def login_probe(self):
        return f"https://web.telegram.org/k/#@{self._channel()}", SEL["input"]

    def _keep_blank_lines(self, page, ch: str, pid: int, p, plain: str) -> Result:
        """07.10.2026: новый пост в канале Web K отправляет без пустых строк между абзацами (в «Избранном» и в поле
        подписи перед отправкой они целы). Правка поста их сохраняет — поэтому сразу переписываем подпись через «Изменить»."""
        from rk.connectors import tg_edit

        url = f"https://t.me/{ch}/{pid}"
        if "\n\n" not in plain or tg_edit.blank_lines(ch, pid) != 0:
            return Result(url=url)
        try:
            tg_edit.edit(page, ch, pid, p, self.cfg.chat_link("tg"), False)
        except Exception as e:  # noqa: BLE001
            return Result(url=url, note=f"пустые строки между абзацами потерялись, правка не удалась: {str(e)[:200]}")
        if tg_edit.blank_lines(ch, pid) == 0:
            return Result(url=url, note="пустые строки между абзацами потерялись и после правки — rk tg-edit")
        return Result(url=url)

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        title_check, ch = self._title(), self._channel()
        rich = href_fix(render.html(p.body, self.cfg.chat_link("tg"))).replace("\n", "<br>")
        plain = _html.unescape(re.sub(r"<[^>]+>", "", rich.replace("<br>", "\n")))
        files = media_of(p)
        before = self.last_post()[0]
        page.goto(f"https://web.telegram.org/k/#@{ch}", wait_until="domcontentloaded")
        for _ in range(60):
            if page.locator(SEL["input"]).count():
                break
            if page.locator(SEL["qr"]).count():
                raise Fail("нет входа в Telegram Web — выполните: rk login tg")
            page.wait_for_timeout(1000)
        else:
            raise Fail("поле ввода канала не появилось за минуту (нет прав писать в канал?)")
        page.wait_for_timeout(2500)
        head = page.locator(SEL["peer_title"]).first.inner_text(timeout=15000)
        if not chat_ok(head, title_check):
            raise Fail(f"открыт не тот чат: «{head.strip()[:60]}» — ничего не вставлено")
        if files:
            with page.expect_file_chooser(timeout=20000) as fc:
                page.locator(SEL["attach"]).first.click()
                page.locator(SEL["attach_media"]).first.click()
            fc.value.set_files([str(f) for f in files])
            page.locator(SEL["popup"]).first.wait_for(state="visible", timeout=60000)
            page.wait_for_timeout(2000)
            field, send = SEL["caption"], SEL["popup_send"]
        else:
            field, send = SEL["input"], ".chat-input .btn-send"
        page.locator(field).first.click()
        page.keyboard.press("ControlOrMeta+a")  # в поле мог остаться черновик — иначе текст задвоится
        page.keyboard.press("Backspace")
        page.evaluate(browser.PASTE_HTML_JS, [field, rich, plain])
        page.wait_for_timeout(2500)
        st = page.evaluate("""(sel) => { const e = document.querySelector(sel); const t = (e && e.innerText || '').trim();
            return {len: t.length, first: t.split('\\n')[0], links: e ? e.querySelectorAll('a').length : 0,
                    bold: e ? e.querySelectorAll('b, strong, [data-markup="markup-bold"]').length : 0}; }""", field)
        if st["len"] < len(plain.strip()) * 0.9:
            raise Fail(f"подпись не вставилась целиком ({st['len']} из {len(plain.strip())} зн.)")
        if st["len"] > len(plain.strip()) * 1.1 + 5:
            raise Fail(f"в поле лишний текст ({st['len']} зн. вместо {len(plain.strip())}) — ничего не отправлено")
        if st["first"].strip() != p.title:
            raise Fail(f"первая строка подписи не совпала с заголовком: «{st['first'][:60]}»")
        note = f"{st['len']} зн., жирного {st['bold']}, ссылок {st['links']}, медиа {len(files)}"
        if dry:
            if files:
                page.keyboard.press("Escape")
            else:  # текст без медиа лежит в основном поле — убрать, чтобы не остался черновик
                page.keyboard.press("ControlOrMeta+a")
                page.keyboard.press("Backspace")
            return Result(url="", note=f"готово к отправке: {note}")
        self.sending()
        page.locator(send).first.click()
        end = time.time() + 180
        while time.time() < end:
            page.wait_for_timeout(5000)
            try:
                pid, first = self.last_post()
            except Exception:  # noqa: BLE001
                continue
            if pid > before and first.strip() == p.title:
                return self._keep_blank_lines(page, ch, pid, p, plain)
        return Result(url=f"https://t.me/s/{ch}", note=f"{AFTER_CLICK}: пост не найден в t.me/s за 3 мин ({note})")
