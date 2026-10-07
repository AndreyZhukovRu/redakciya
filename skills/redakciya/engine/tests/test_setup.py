import yaml

from rk import config, journal
from rk.cli import main


def _post(home, slug, body="Заголовок\n\nТекст.", media="[]", to=None):
    d = home / "posts" / slug
    d.mkdir(parents=True)
    head = f"media: {media}\n" + (f"to: {to}\n" if to else "")
    (d / "post.md").write_text(f"---\n{head}---\n{body}\n", encoding="utf-8")
    return d


def test_setup_creates(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    assert main(["setup", "--yes", "--platforms", "tg,max", "--author", "Автор"]) == 0
    c = config.load()
    assert c.author == "Автор" and c.enabled == ["tg", "max"]
    assert (tmp_path / "W" / "posts").is_dir()
    assert main(["setup", "--yes", "--platforms", "tg"]) == 1   # уже есть, без --force не трогаем


def test_setup_set_fields_and_unknown_platform(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    assert main(["setup", "--yes", "--platforms", "tg,site", "--set", "tg.channel=@chan",
                 "--set", "site.url=https://e.ru/api/news", "--set", "closing.chat.tg=https://t.me/chat"]) == 0
    raw = yaml.safe_load((tmp_path / "W" / "config.yaml").read_text(encoding="utf-8"))
    assert raw["platforms"]["tg"]["channel"] == "@chan" and raw["platforms"]["site"]["url"] == "https://e.ru/api/news"
    assert config.load().chat_link("tg") == "https://t.me/chat"
    assert main(["setup", "--yes", "--force", "--platforms", "tg,myspace"]) == 1


def test_check_post_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    main(["setup", "--yes", "--platforms", "max", "--author", "А"])
    d = tmp_path / "W" / "posts" / "s"; d.mkdir(parents=True)
    (d / "post.md").write_text("---\nmedia: []\n---\nЗаголовок\n\n" + "я" * 4100 + "\n", encoding="utf-8")
    assert main(["check-post", "s", "--offline"]) == 1      # MAX 4000 превышен; --offline — без проверки ссылок


def test_check_post_missing_media_and_ok(tmp_path, monkeypatch, capsys):
    home = tmp_path / "W"
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    main(["setup", "--yes", "--platforms", "tg", "--author", "А"])
    _post(home, "bad", media="[a.jpg]")
    _post(home, "good")
    assert main(["check-post", "bad", "--offline"]) == 1
    assert "a.jpg" in capsys.readouterr().out
    assert main(["check-post", "good", "--offline"]) == 0
    assert "ИТОГ: всё в порядке" in capsys.readouterr().out


def test_check_post_chat_placeholder_without_link(tmp_path, monkeypatch, capsys):
    home = tmp_path / "W"
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    main(["setup", "--yes", "--platforms", "tg", "--author", "А"])
    _post(home, "c", body="Заголовок\n\nОбсудить — [в чате]({{CHAT}})")
    assert main(["check-post", "c", "--offline"]) == 1
    assert "closing.chat.tg" in capsys.readouterr().out


def test_report_respects_targets_and_after_click(tmp_path, monkeypatch, capsys):
    home = tmp_path / "W"
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    main(["setup", "--yes", "--platforms", "tg,max,x", "--author", "А"])
    a = _post(home, "a", to="[tg]")
    b = _post(home, "b")
    (home / "batches" / "p1").mkdir(parents=True)
    (home / "batches" / "p1" / "order.txt").write_text("a\nb\n", encoding="utf-8")
    journal.put(a, "tg", "https://t.me/c/1")
    journal.put(b, "tg", "https://t.me/c/2")
    journal.put(b, "max", "", note=journal.AFTER_CLICK)
    assert main(["report", "p1"]) == 1
    out = capsys.readouterr().out
    assert "✓ a" in out and "✗ b" in out and "нет: x" in out and "⚠ max" in out
    assert "Итог: 1 из 2" in out


def test_check_reports_each_platform(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    main(["setup", "--yes", "--platforms", "tg,max", "--author", "А", "--set", "tg.channel=@c",
          "--set", "tg.title_check=К", "--set", "max.channel_id=-5"])

    class Ok:
        def check(self):
            return "вход есть"

    class Bad:
        def check(self):
            raise RuntimeError("нет входа")

    from rk import connectors
    monkeypatch.setattr(connectors, "make", lambda cfg, key: Ok() if key == "tg" else Bad())
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "✓ tg: вход есть" in out and "✗ max: нет входа — rk login max" in out


def test_check_opens_browser_for_login(tmp_path, monkeypatch, capsys):
    import contextlib

    from rk import browser, connectors
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    main(["setup", "--yes", "--platforms", "tg,x,max", "--author", "А", "--set", "tg.channel=@c",
          "--set", "tg.title_check=К", "--set", "max.channel_id=-5", "--set", "x.profile=@p"])

    class Web:
        uses_browser = True

        def __init__(self, sel):
            self.sel = sel

        def check(self):
            return "настроено"

        def login_probe(self):
            return ("https://example.test/", self.sel)

    class Api:
        uses_browser = False

        def check(self):
            return "бот жив"

    made = {"tg": Web("#ok"), "x": Web("#missing"), "max": Api()}
    monkeypatch.setattr(connectors, "make", lambda cfg, key: made[key])
    visited = []

    class Loc:
        def __init__(self, sel):
            self.sel, self.first = sel, self

        def wait_for(self, state, timeout):
            if self.sel != "#ok":
                raise TimeoutError(self.sel)

    class Page:
        def goto(self, url, wait_until=None):
            visited.append(url)

        def locator(self, sel):
            return Loc(sel)

        def close(self):
            pass

    opened = []
    monkeypatch.setattr(browser, "session", lambda headless=False: (opened.append(1), contextlib.nullcontext(object()))[1])
    monkeypatch.setattr(browser, "new_page", lambda ctx: Page())
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "✓ tg: вход есть" in out and "✗ x: нет входа" in out and "rk login x" in out and "✓ max: бот жив" in out
    assert len(opened) == 1 and len(visited) == 2      # один браузер на все площадки


def test_set_keeps_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    assert main(["setup", "--yes", "--platforms", "tg,vk", "--author", "2024", "--set", "tg.title_check=Иван: фото",
                 "--set", "vk.group_id=123", "--set", "tg.premium=yes", "--set", "tg.channel=Yes"]) == 0
    raw = yaml.safe_load((tmp_path / "W" / "config.yaml").read_text(encoding="utf-8"))
    assert raw["author"] == "2024" and raw["platforms"]["tg"]["title_check"] == "Иван: фото"
    assert raw["platforms"]["tg"]["channel"] == "Yes" and raw["platforms"]["vk"]["group_id"] == 123
    assert raw["platforms"]["tg"]["premium"] is True


def test_check_flags_placeholders(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    main(["setup", "--yes", "--platforms", "tg", "--author", "А"])
    assert main(["check"]) == 1
    assert "не заполнено: platforms.tg.channel" in capsys.readouterr().out


def test_force_keeps_editor_url_and_backup(tmp_path, monkeypatch):
    home = tmp_path / "W"
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    main(["setup", "--yes", "--platforms", "tg", "--author", "А"])
    f = home / "config.yaml"
    f.write_text(f.read_text(encoding="utf-8").replace("editor_url: ''", "editor_url: https://claude.ai/artifact/x"),
                 encoding="utf-8")
    assert main(["setup", "--yes", "--force", "--platforms", "tg,max", "--author", "А"]) == 0
    assert config.load().editor_url == "https://claude.ai/artifact/x"
    assert (home / "config.yaml.bak").exists()


def test_report_marks_hidden(tmp_path, monkeypatch, capsys):
    home = tmp_path / "W"
    monkeypatch.setenv("REDAKCIYA_HOME", str(home))
    main(["setup", "--yes", "--platforms", "tg", "--author", "А"])
    a = _post(home, "a")
    h = home / "posts" / "h"
    h.mkdir(parents=True)
    (h / "post.md").write_text("---\nstatus: hidden\nmedia: []\n---\nЗ\n\nТ\n", encoding="utf-8")
    (home / "batches" / "p").mkdir(parents=True)
    (home / "batches" / "p" / "order.txt").write_text("a\nh\n", encoding="utf-8")
    journal.put(a, "tg", "https://t.me/c/1")
    assert main(["report", "p"]) == 0
    out = capsys.readouterr().out
    assert "· h — не публикуем" in out and "Итог: 1 из 1" in out


def test_cli_survives_cp1251_console(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "REDAKCIYA_HOME": str(tmp_path / "W"), "PYTHONIOENCODING": "cp1251"}
    env.pop("PYTHONUTF8", None)
    run = lambda *a: subprocess.run([sys.executable, "-m", "rk", *a], env=env, capture_output=True)
    run("setup", "--yes", "--platforms", "tg", "--author", "А", "--set", "tg.channel=@c")
    d = tmp_path / "W" / "posts" / "s"
    d.mkdir(parents=True)
    (d / "post.md").write_text("---\nmedia: []\n---\nЗ\n\nТ\n", encoding="utf-8")
    r = run("check-post", "s", "--offline")
    assert b"UnicodeEncodeError" not in r.stderr and r.returncode == 0
