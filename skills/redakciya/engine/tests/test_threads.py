import pytest

from rk.connectors.base import Fail
from rk.connectors.threads_api import ThreadsApi
from rk.connectors.threads_web import prepare


def test_link_and_limit():
    assert prepare("Новость\n\nПодробнее: {LINK}", "https://s/1").endswith("https://s/1")
    with pytest.raises(Fail, match="500"):
        prepare("x" * 501, "")


def test_api_needs_public_media(tmp_path):
    class Cfg:
        platforms = {"threads": {"mode": "api"}}

        def chat_link(self, k):
            return ""
    class P:
        dir = tmp_path
        media = [tmp_path / "a.jpg"]
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "threads.txt").write_text("Текст {LINK}", encoding="utf-8")
    with pytest.raises(Fail, match="mode: web"):
        ThreadsApi(cfg=Cfg(), opts={"key": "threads"})._media_urls(P())
