import pathlib

import httpx
import pytest

from rk.connectors.base import Fail
from rk.connectors.vk_api import VkApi, auth_url, token_from_url
from rk.connectors.vk_web import cmid_ok


def test_auth_url():
    u = auth_url(123)
    assert "client_id=123" in u and "scope=wall,photos,video,groups,docs" in u and "response_type=token" in u


def test_auth_url_requires_app():
    with pytest.raises(Fail, match="app_id"):
        auth_url(0)


def test_token_from_url():
    assert token_from_url("https://oauth.vk.com/blank.html#access_token=vk1.a.T&expires_in=86400&user_id=1") == "vk1.a.T"
    assert token_from_url("https://oauth.vk.com/blank.html#error=access_denied") is None


def test_api_error_message():
    def handler(req):
        return httpx.Response(200, json={"error": {"error_code": 5, "error_msg": "User authorization failed"}})
    v = VkApi(cfg=None, opts={"key": "vk", "group_id": 1})
    with pytest.raises(Fail, match=r"\[5\]"):
        v._api(httpx.Client(transport=httpx.MockTransport(handler)), "users.get", "t")


def test_cmid():
    assert cmid_ok("417") and not cmid_ok("-3") and not cmid_ok(None)


def test_vk_group_id_with_minus_and_title_check(tmp_path, monkeypatch):
    from fakepage import FakePage
    from rk import config as C
    from rk.connectors import make
    from rk.connectors.base import Fail
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("platforms: {vk: {mode: web, group_id: -77, title_check: 'Моё сообщество'}}\n",
                                          encoding="utf-8")
    wall = make(C.load(), "vk")
    assert wall.login_probe()[0] == "https://vk.com/club77"
    page = FakePage(counts={"[data-testid='group_publish_create_button']": 1})
    page.title = lambda: "Чужая группа | ВКонтакте"
    with pytest.raises(Fail, match="не то сообщество"):
        wall._open(page, 77)
    assert not page.clicked("group_publish_create_button")


def _wall(tmp_path, monkeypatch, n_files, drop_first_try_of=None):
    from PIL import Image

    from fakepage import FakePage
    from rk import config as C
    from rk import post as P
    from rk.connectors import make, vk_web
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("platforms: {vk: {mode: web, group_id: 77}}\n", encoding="utf-8")
    d = tmp_path / "posts" / "s"
    d.mkdir(parents=True)
    names = [f"{i}.jpg" for i in range(1, n_files + 1)]
    for nm in names:
        Image.new("RGB", (40, 30), "red").save(d / nm)
    (d / "post.md").write_text(f"---\nmedia: [{', '.join(names)}]\n---\nЗаголовок\n\n" + "Текст новости. " * 20,
                               encoding="utf-8")
    page = FakePage(counts={vk_web.WALL["create"]: 1, vk_web.WALL["post_item"]: 1, vk_web.WALL["box"]: 1,
                            vk_web.WALL["file"]: 1, vk_web.WALL["field"]: 1})
    page.title = lambda: "Моё сообщество"
    st = {"items": 0, "dropped": False}

    def ev(js, arg):
        if js == vk_web.WALL_RESET_INPUTS:
            return None
        if "ClipboardEvent" in js:
            return 300
        if js == vk_web.WALL_TOAST_FAIL:
            last = str(page.uploaded[-1]) if page.uploaded else ""
            if drop_first_try_of and last.endswith(drop_first_try_of) and not st["dropped"]:
                st["dropped"] = True          # VK показал тост и убрал файл
                st["items"] -= 1
                return 1
            return 0
        if js == vk_web.WALL_STATE:
            return {"items": st["items"], "loaders": 0, "text": ""}
        if js == vk_web.WALL_HAS:
            st["items"] = len(page.uploaded) - (1 if st["dropped"] else 0)
            return True
        return 0
    page._eval = ev
    return make(C.load(), "vk"), page, P.load(d)


def test_wall_uploads_one_by_one_and_dry_leaves_no_draft(tmp_path, monkeypatch):
    wall, page, p = _wall(tmp_path, monkeypatch, 3)
    r = wall.publish(p, dry=True, page=page)
    assert [pathlib.Path(f).name for f in page.uploaded] == ["1.jpg", "2.jpg", "3.jpg"]   # строго по одному, по порядку
    assert "3 медиа" in r.note and not page.clicked(vk_web_sel("next"))


def test_wall_retries_dropped_photo_with_smaller_copy(tmp_path, monkeypatch):
    wall, page, p = _wall(tmp_path, monkeypatch, 2, drop_first_try_of="2.jpg")
    wall.publish(p, dry=True, page=page)
    names = [pathlib.Path(f).name for f in page.uploaded]
    assert names[:2] == ["1.jpg", "2.jpg"] and names[2].startswith("2-1600")


def vk_web_sel(k):
    from rk.connectors import vk_web
    return vk_web.WALL[k]
