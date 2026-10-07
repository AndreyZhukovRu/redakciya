"""Защита от публикации не туда и дублей: Telegram Web, правка поста, Telethon, VK API, смешанный альбом."""
import types

import pytest
from PIL import Image

from fakepage import FakePage
from rk import config, media, post
from rk.connectors import make, tg_edit
from rk.connectors.base import Fail
from rk.connectors.telegram_telethon import entity_problem
from rk.connectors.telegram_web import SEL, media_of


def ws(tmp_path, monkeypatch, plats="{tg: {mode: web, channel: '@chan', title_check: 'Пример канала'}}", media_="[]"):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    monkeypatch.setenv("REDAKCIYA_SECRETS", str(tmp_path / "S"))
    (tmp_path / "W").mkdir(exist_ok=True)
    (tmp_path / "W" / "config.yaml").write_text(f"platforms: {plats}\n", encoding="utf-8")
    d = tmp_path / "W" / "posts" / "s"
    d.mkdir(parents=True, exist_ok=True)
    (d / "post.md").write_text(f"---\nmedia: {media_}\n---\nЗаголовок\n\nТекст новости.\n", encoding="utf-8")
    return config.load(), d


def state(n, first="Заголовок"):
    return lambda js, arg: ({"len": n, "first": first, "links": 0, "bold": 0, "a": 0}
                            if "querySelectorAll('a')" in js else 1)


def test_wrong_chat_nothing_pasted(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    tw = make(cfg, "tg")
    monkeypatch.setattr(tw, "last_post", lambda: (5, "x"))
    page = FakePage(counts={SEL["input"]: 1}, texts={SEL["peer_title"]: "Чат обсуждений"})
    with pytest.raises(Fail, match="не тот чат"):
        tw.publish(post.load(d), dry=False, page=page)
    assert not page.pasted() and not any(e[0] == "click" for e in page.log)


def test_no_login_nothing_pasted(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    tw = make(cfg, "tg")
    monkeypatch.setattr(tw, "last_post", lambda: (5, "x"))
    page = FakePage(counts={SEL["qr"]: 1})
    with pytest.raises(Fail, match="нет входа"):
        tw.publish(post.load(d), dry=False, page=page)
    assert not page.pasted()


def test_text_post_clears_field_and_rejects_leftover(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    tw = make(cfg, "tg")
    monkeypatch.setattr(tw, "last_post", lambda: (5, "x"))
    page = FakePage(counts={SEL["input"]: 1}, texts={SEL["peer_title"]: "Пример канала"}, evaluate=state(60))
    with pytest.raises(Fail, match="лишн"):                     # в поле был старый черновик — текст задвоился
        tw.publish(post.load(d), dry=False, page=page)
    keys = [e[1] for e in page.log if e[0] == "key"]
    assert keys[:2] == ["ControlOrMeta+a", "Backspace"]          # поле очищено до вставки
    assert not page.clicked("btn-send")


def test_text_post_dry_leaves_no_draft(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    tw = make(cfg, "tg")
    monkeypatch.setattr(tw, "last_post", lambda: (5, "x"))
    page = FakePage(counts={SEL["input"]: 1}, texts={SEL["peer_title"]: "Пример канала"}, evaluate=state(24))
    assert "готово к отправке" in tw.publish(post.load(d), dry=True, page=page).note
    keys = [e[1] for e in page.log if e[0] == "key"]
    assert keys[-2:] == ["ControlOrMeta+a", "Backspace"] and not page.clicked("btn-send")


def test_edit_requires_edit_mode(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    bubble = f'.bubble[data-mid="{2 ** 32 + 7}"]'
    texts = {f"{bubble} .message": "Старый заголовок\n\nТекст", SEL["input"]: ""}
    page = FakePage(counts={bubble: 1}, texts=texts, evaluate=lambda js, arg: True)
    with pytest.raises(Fail, match="режим правки"):
        tg_edit.edit(page, "chan", 7, post.load(d), "", False)
    assert not page.pasted() and not page.clicked("btn-send")
    texts[SEL["input"]] = "Старый заголовок\n\nТекст"            # режим правки включился — идём дальше
    page = FakePage(counts={bubble: 1}, texts=texts, evaluate=state(24))
    assert tg_edit.edit(page, "chan", 7, post.load(d), "", True).startswith("проверка")


def test_telethon_checks_entity():
    ch = types.SimpleNamespace(broadcast=True, title="Пример канала")
    assert entity_problem(ch, "Пример канала") is None
    assert "не канал" in entity_problem(types.SimpleNamespace(broadcast=False, megagroup=True, title="Пример канала"),
                                        "Пример канала")
    assert "не тот" in entity_problem(types.SimpleNamespace(broadcast=True, title="Другое"), "Пример канала")
    assert "не канал" in entity_problem(types.SimpleNamespace(first_name="Иван"), "Пример канала")


def test_vk_api_photo_lost_fails_before_wall_post(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch, plats="{vk: {mode: api, group_id: 5}}", media_="[a.jpg]")
    Image.new("RGB", (40, 30), "red").save(d / "a.jpg")
    vk = make(cfg, "vk")
    calls = []
    monkeypatch.setattr(vk, "_tokens", lambda c: ("U", "G"))
    monkeypatch.setattr(vk, "_api", lambda c, m, tok, **kw: calls.append(m) or {"upload_url": "u"})
    monkeypatch.setattr(vk, "_upload", lambda c, url, field, path: {"photo": "[]"})
    with pytest.raises(Fail, match="a.jpg"):
        vk.publish(post.load(d), dry=False)
    assert "wall.post" not in calls


def test_mixed_album_keeps_order_and_adds_audio(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch, media_="[a.jpg, v.mp4, b.jpg]")
    for n in ("a.jpg", "v.mp4", "b.jpg"):
        (d / n).write_bytes(b"x")
    monkeypatch.setattr(media, "ensure_audio", lambda p: p.with_name(p.stem + "-audio.mp4"))
    assert [x.name for x in media_of(post.load(d))] == ["a.jpg", "v-audio.mp4", "b.jpg"]
