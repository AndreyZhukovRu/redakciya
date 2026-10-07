from rk.connectors.x_web import pick_tweet
from rk.connectors.youtube_web import split_by_aspect


def test_pick_by_text():
    feed = [{"href": "https://x.com/me/status/2", "text": "Другая новость"},
            {"href": "https://x.com/me/status/1", "text": "Наша новость про Sigma и ещё"}]
    assert pick_tweet(feed, "Наша новость про Sigma и ещё текст") == "https://x.com/me/status/1"
    assert pick_tweet(feed, "Не было такой") is None


def test_split_by_aspect(tmp_path):
    from PIL import Image
    ok, bad = tmp_path / "ok.jpg", tmp_path / "bad.jpg"
    Image.new("RGB", (1200, 800)).save(ok)
    Image.new("RGB", (3000, 1000)).save(bad)
    assert split_by_aspect([ok, bad]) == ([ok], [bad])
