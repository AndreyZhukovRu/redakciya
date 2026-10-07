from rk import render

BODY = "Заголовок\n\nТекст с **жирным** и [ссылкой](https://ex.com/a?x=1&y=2). Чат: [наш чат]({{CHAT}}).\n"


def test_html():
    h = render.html(BODY, "https://t.me/c")
    assert "<b>жирным</b>" in h
    assert '<a href="https://ex.com/a?x=1&amp;y=2">ссылкой</a>' in h
    assert '<a href="https://t.me/c">наш чат</a>' in h


def test_html_escapes_text():
    assert render.html("a < b & c", "") == "a &lt; b &amp; c"


def test_plain():
    t = render.plain(BODY, "https://vk.me/c")
    assert "ссылкой (https://ex.com/a?x=1&y=2)" in t and "**" not in t and "наш чат (https://vk.me/c)" in t


def test_plain_bare_url_not_doubled():
    assert render.plain("[https://ex.com](https://ex.com)", "") == "https://ex.com"


def test_len_utf16():
    assert render.visible_len("<b>ёж</b> 😀", True) == 5


def test_short():
    assert render.short("Новость {LINK}", "https://s/1") == "Новость https://s/1"


def test_check_limits(tmp_path):
    from rk import config, post
    (tmp_path / "config.yaml").write_text("platforms: {max: {}, x: {}, tg: {mode: bot}}\n", encoding="utf-8")
    cfg = config.load(tmp_path / "config.yaml")
    d = tmp_path / "s"; d.mkdir()
    (d / "post.md").write_text("---\nmedia: [a.jpg]\n---\nЗ\n\n" + "я" * 4100 + "\n", encoding="utf-8")
    (d / "x.txt").write_text("я" * 260 + " {LINK}", encoding="utf-8")
    probs = render.check_limits(post.load(d), cfg)
    assert any(s.startswith("MAX") for s in probs)
    assert any(s.startswith("Telegram") and "1024" in s for s in probs)   # бот с медиа — 1024
    assert any(s.startswith("x ") for s in probs)                          # 261 + 23 > 280


def test_check_limits_premium(tmp_path):
    from rk import config, post
    d = tmp_path / "s"; d.mkdir()
    (d / "post.md").write_text("---\nmedia: [a.jpg]\n---\nЗ\n\n" + "я" * 2000 + "\n", encoding="utf-8")
    for plat, bad in (("{tg: {mode: web}}", True), ("{tg: {mode: web, premium: true}}", False)):
        (tmp_path / "config.yaml").write_text(f"platforms: {plat}\n", encoding="utf-8")
        probs = render.check_limits(post.load(d), config.load(tmp_path / "config.yaml"))
        assert any("1024" in s for s in probs) == bad      # без Premium подпись к альбому — до 1024
