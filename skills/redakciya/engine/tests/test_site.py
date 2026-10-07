import json

import httpx

from rk.connectors.site_api import SiteApi, form_fields
from rk.connectors.site_wordpress import SiteWordpress, gallery_block


def test_form_fields():
    f = form_fields(title="Т", html="<p>x</p>", slug="s", tags=["a"], categories=["c"])
    assert ("tags[]", "a") in f and ("categories[]", "c") in f and ("slug", "s") in f and ("title", "Т") in f


def test_gallery_block():
    b = gallery_block([(1, "https://s/1.jpg"), (2, "https://s/2.jpg")])
    assert b.startswith("<!-- wp:gallery") and "wp-image-2" in b and b.rstrip().endswith("<!-- /wp:gallery -->")


def test_site_api_post_and_upload(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    seen = {}

    def handler(req):
        seen[req.url.path] = req.headers.get("authorization")
        if req.url.path.endswith("/media"):
            return httpx.Response(201, json={"url": "https://s/u/a.jpg"})
        return httpx.Response(201, json={"id": "7", "url": "https://s/news/s"})
    s = SiteApi(cfg=None, opts={"key": "site", "url": "https://s/api/news"})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert s._upload(c, "k", [img]) == ["https://s/u/a.jpg"]
    assert s._send(c, "k", {"title": "Т", "html": "<p>x</p>", "slug": "s"}, [img]) == "https://s/news/s"
    assert seen["/api/news"] == "Bearer k"


def test_wordpress_existing_slug_is_idempotent():
    def handler(req):
        if req.url.path == "/wp-json/wp/v2/posts" and req.method == "GET":
            return httpx.Response(200, json=[{"id": 5, "link": "https://s/old"}])
        raise AssertionError("не должен создавать дубль")
    w = SiteWordpress(cfg=None, opts={"key": "site", "url": "https://s"})
    assert w._existing(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://s"), ("u", "p"), "slug") == "https://s/old"
