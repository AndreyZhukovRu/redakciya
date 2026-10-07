import httpx

from rk.connectors.max_bot import MaxBot, build_message


def test_build_message():
    m = build_message("<b>Т</b>", [{"type": "image", "payload": {"photos": {"a": 1}}}])
    assert m == {"text": "<b>Т</b>", "format": "html", "attachments": [{"type": "image", "payload": {"photos": {"a": 1}}}],
                 "disable_link_preview": True}
    assert build_message("т", [])["attachments"] is None


def test_not_ready_retries():
    calls = {"n": 0}

    def handler(req):
        if req.url.path == "/messages":
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(400, json={"code": "attachment.not.ready"})
            return httpx.Response(200, json={"message": {"url": "https://max.ru/c/1", "body": {"mid": "m"}}})
        return httpx.Response(404)
    m = MaxBot(cfg=None, opts={"key": "max", "channel_id": -1})
    url = m._post_message(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://botapi.max.ru"),
                          {"Authorization": "t"}, {"text": "x"}, sleep=lambda s: None)
    assert url == "https://max.ru/c/1" and calls["n"] == 3


def test_check_reports_channel():
    def handler(req):
        if req.url.path == "/me":
            return httpx.Response(200, json={"name": "Бот"})
        return httpx.Response(200, json={"title": "Мой канал", "type": "channel"})
    m = MaxBot(cfg=None, opts={"key": "max", "channel_id": -5})
    assert "Мой канал" in m._check(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://botapi.max.ru"), {})
