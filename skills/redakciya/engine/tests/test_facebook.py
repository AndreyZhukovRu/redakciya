import json
import urllib.parse

import httpx
import pytest
from PIL import Image

from rk import config, post
from rk.connectors import make
from rk.connectors.base import Fail
from rk.connectors.facebook_api import FacebookApi, page_token_from_accounts


def ws(tmp_path, monkeypatch, media="[]"):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path / "W"))
    monkeypatch.setenv("REDAKCIYA_SECRETS", str(tmp_path / "S"))
    (tmp_path / "W").mkdir()
    (tmp_path / "S").mkdir()
    (tmp_path / "S" / "fb_page_token").write_text("PAGE-TOKEN\n", encoding="utf-8")
    (tmp_path / "W" / "config.yaml").write_text(
        "platforms: {fb: {page_id: 123}}\nclosing: {chat: {fb: 'https://m.me/j/chat'}}\n", encoding="utf-8")
    d = tmp_path / "W" / "posts" / "s"
    d.mkdir(parents=True)
    (d / "post.md").write_text(f"---\nmedia: {media}\n---\nЗаголовок\n\n**Жирный** и [текст](https://e.com). "
                               "Обсудить — [в чате]({{CHAT}})\n", encoding="utf-8")
    return config.load(), d


def fake(calls, replies):
    def handler(req: httpx.Request):
        body = req.content.decode("utf-8", "ignore")
        calls.append((req.method, req.url.path, body))
        return httpx.Response(200, json=replies.pop(0))
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registered_and_text_is_plain(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    conn = make(cfg, "fb")
    assert isinstance(conn, FacebookApi)
    assert conn.message(post.load(d)) == ("Заголовок\n\nЖирный и текст (https://e.com). "
                                          "Обсудить — в чате (https://m.me/j/chat)")


def test_page_token_from_accounts():
    data = {"data": [{"id": "9", "access_token": "A"}, {"id": "123", "name": "Стр", "access_token": "B"}]}
    assert page_token_from_accounts(data, 123) == ("B", "Стр")
    with pytest.raises(Fail, match="123"):
        page_token_from_accounts({"data": []}, 123)


def test_album_uploads_unpublished_then_feed(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch, media="[a.jpg, b.jpg]")
    for n in ("a", "b"):
        Image.new("RGB", (40, 30), "red").save(d / f"{n}.jpg")
    calls = []
    conn = make(cfg, "fb")
    monkeypatch.setattr(conn, "_client", lambda: fake(calls, [{"id": "p1"}, {"id": "p2"}, {"id": "123_777"}]))
    conn.on_send = lambda: calls.append(("MARK", "", ""))       # отметка «отправка начата» — после фото, до ленты
    r = conn.publish(post.load(d), dry=False)
    assert [c[0] for c in calls] == ["POST", "POST", "MARK", "POST"]
    calls.remove(("MARK", "", ""))
    assert r.url == "https://www.facebook.com/123/posts/777" and r.note is None
    assert [c[1] for c in calls] == ["/v24.0/123/photos", "/v24.0/123/photos", "/v24.0/123/feed"]
    assert "published" in calls[0][2] and "false" in calls[0][2] and "PAGE-TOKEN" in calls[0][2]
    feed = urllib.parse.parse_qs(calls[2][2])
    assert json.loads(feed["attached_media[0]"][0]) == {"media_fbid": "p1"}
    assert json.loads(feed["attached_media[1]"][0]) == {"media_fbid": "p2"}
    assert feed["message"][0].startswith("Заголовок")


def test_text_only_and_expired_token(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    conn = make(cfg, "fb")
    calls = []
    monkeypatch.setattr(conn, "_client", lambda: fake(calls, [{"id": "123_5"}]))
    assert conn.publish(post.load(d), dry=False).url == "https://www.facebook.com/123/posts/5"
    assert calls[0][1] == "/v24.0/123/feed"
    monkeypatch.setattr(conn, "_client", lambda: fake([], [{"error": {"message": "Session has expired", "code": 190}}]))
    with pytest.raises(Fail, match="rk login fb"):
        conn.publish(post.load(d), dry=False)


def test_dry_does_not_call_network(tmp_path, monkeypatch):
    cfg, d = ws(tmp_path, monkeypatch)
    conn = make(cfg, "fb")
    monkeypatch.setattr(conn, "_client", lambda: (_ for _ in ()).throw(AssertionError("сеть в --dry")))
    assert "готово к отправке" in conn.publish(post.load(d), dry=True).note
