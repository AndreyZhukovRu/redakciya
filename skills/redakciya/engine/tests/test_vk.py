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
