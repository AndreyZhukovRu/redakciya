from rk import post


def make(tmp, head, body):
    d = tmp / "Папка с пробелом" / "2026-10-07-test"
    (d / "album").mkdir(parents=True)
    (d / "album" / "01 обложка.jpg").write_bytes(b"x")
    (d / "post.md").write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return d


def test_load(tmp_path):
    d = make(tmp_path, "media: [album/01 обложка.jpg]\nto: [tg, max]", "Заголовок новости\n\nТекст **жирный**.\n")
    p = post.load(d)
    assert p.slug == "2026-10-07-test" and p.title == "Заголовок новости"
    assert p.media == [d / "album" / "01 обложка.jpg"] and p.targets == ["tg", "max"]
    assert p.body.startswith("Заголовок новости\n\nТекст")


def test_save_body_keeps_head(tmp_path):
    d = make(tmp_path, "media: []", "Старый\n")
    p = post.load(d)
    post.save_body(p, "Новый заголовок\n\nНовый текст\n")
    raw = (d / "post.md").read_text(encoding="utf-8")
    assert raw.startswith("---\nmedia: []\n---\nНовый заголовок")
    assert p.title == "Новый заголовок"


def test_no_targets_means_none(tmp_path):
    assert post.load(make(tmp_path, "media: []", "Т\n")).targets is None


def test_short_versions(tmp_path):
    d = make(tmp_path, "media: []", "Т\n")
    (d / "x.txt").write_text(" Коротко {LINK} \n", encoding="utf-8")
    p = post.load(d)
    assert post.short(p, "x") == "Коротко {LINK}" and post.short(p, "threads") == ""
