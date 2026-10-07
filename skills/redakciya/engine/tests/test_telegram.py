import pytest

from rk.connectors.base import Fail
from rk.connectors.telegram_bot import TelegramBot
from rk.connectors.telegram_web import TelegramWeb, chat_ok, href_fix, last_post_from_html, media_of
from rk.connectors.tg_edit import blank_lines_from_embed, links_from_embed

FEED = ('<div class="tgme_widget_message_wrap"><div data-post="chan/10"><div class="tgme_widget_message_text">Старый<br>т</div></div></div>'
        '<div class="tgme_widget_message_wrap"><div data-post="chan/12"><div class="tgme_widget_message_text">Новый &amp; свежий<br>т</div></div></div>')


class P:
    pass


def test_chat_check():
    assert chat_ok("ПРИМЕР КАНАЛА\n1 234 subscribers", "ПРИМЕР КАНАЛА")
    assert not chat_ok("Другой — чат", "ПРИМЕР КАНАЛА")
    assert not chat_ok("", "ПРИМЕР КАНАЛА")


def test_requires_title_check():
    c = TelegramWeb(cfg=None, opts={"key": "tg", "channel": "@x"})
    with pytest.raises(Fail, match="title_check"):
        c._title()


def test_last_post_from_html():
    assert last_post_from_html(FEED) == (12, "Новый & свежий")


def test_href_fix():
    assert href_fix('<a href="https://a/?x=1&amp;y=2">t</a> &amp;') == '<a href="https://a/?x=1&y=2">t</a> &amp;'


def test_media_of(tmp_path):
    p = P()
    p.media = [tmp_path / f"{i}.jpg" for i in range(12)]
    for m in p.media:
        m.write_bytes(b"x")
    assert len(media_of(p)) == 10
    p.media.append(tmp_path / "нет.jpg")
    p.media = p.media[-1:]
    with pytest.raises(Fail, match="нет файлов"):
        media_of(p)


def test_bot_caption_limit(tmp_path):
    p = P()
    p.body = "З\n\n" + "я" * 1100
    p.media = [tmp_path / "a.jpg"]
    p.media[0].write_bytes(b"x")

    class Cfg:
        def chat_link(self, k):
            return ""
    with pytest.raises(Fail, match="1024"):
        TelegramBot(cfg=Cfg(), opts={"key": "tg", "channel": "@x"}).publish(p, dry=True)


def test_links_from_embed_double_unescape():
    html = '<div class="tgme_widget_message_text">т <a href="https://a/?x=1&amp;amp;y=2">ссылка</a> <b>ж</b></div>'
    assert links_from_embed(html) == ([("ссылка", "https://a/?x=1&y=2")], 1)


def test_blank_lines_from_embed():
    # 07.10.2026: новые посты в канале уходили из Web K без пустых строк — их надо замечать по t.me
    ok = '<div class="tgme_widget_message_text js-message_text">Заголовок<br/><br/>Абзац<br>строка<br /> <br/>Ещё</div>'
    lost = '<div class="tgme_widget_message_text js-message_text">Заголовок<br/>Абзац<br/>Ещё</div>'
    assert blank_lines_from_embed(ok) == 2
    assert blank_lines_from_embed(lost) == 0
    assert blank_lines_from_embed("<html>нет поста</html>") == -1


def test_channel_from_link_and_feed_error_is_fail(monkeypatch):
    import urllib.request
    cfg = P()
    cfg.platforms = {}
    tw = TelegramWeb(cfg, {"key": "tg", "channel": "https://t.me/s/my_chan/", "title_check": "x"})
    assert tw._channel() == "my_chan"

    def down(*a, **k):
        raise urllib.error.URLError("нет сети")
    monkeypatch.setattr(urllib.request, "urlopen", down)
    with pytest.raises(Fail, match="публичн"):
        tw.last_post()


def test_check_reads_public_feed_title(monkeypatch):
    import io
    import urllib.request
    cfg = P()
    cfg.platforms = {}
    tw = TelegramWeb(cfg, {"key": "tg", "channel": "@my_chan", "title_check": "Пример канала"})
    page = '<meta property="og:title" content="Пример канала"><div class="tgme_channel_info">'
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(page.encode()))
    assert "Пример канала" in tw.check()
    tw.opts["title_check"] = "Другое"
    with pytest.raises(Fail, match="не совпало"):
        tw.check()
