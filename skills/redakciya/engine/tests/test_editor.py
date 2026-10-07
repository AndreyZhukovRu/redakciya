import json

from rk import editor, post


def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("platforms: {tg: {}, vk: {}, x: {}}\ndefaults: [tg, vk]\n", encoding="utf-8")
    d = tmp_path / "posts" / "s"
    d.mkdir(parents=True)
    (d / "post.md").write_text("---\nmedia: []\n---\nСтарый\n\nТекст\n", encoding="utf-8")
    (tmp_path / "batches" / "B").mkdir(parents=True)
    (tmp_path / "batches" / "B" / "order.txt").write_text("s\n", encoding="utf-8")
    return d


def test_docs_have_targets_and_settings(tmp_path, monkeypatch):
    ws(tmp_path, monkeypatch)
    out = editor.docs("B", None)
    doc = json.loads((tmp_path / "batches" / "B" / "docs" / "s.json").read_text(encoding="utf-8"))
    assert doc["title"] == "Старый" and doc["targets"] == ["tg", "vk"] and doc["status"] == "draft"
    st = json.loads((tmp_path / "batches" / "B" / "docs" / "_settings.json").read_text(encoding="utf-8"))
    assert st["enabled"] == ["tg", "vk", "x"] and st["defaults"] == ["tg", "vk"] and st["names"]["x"] == "X"
    assert len(out) == 2


def test_pull_writes_targets(tmp_path, monkeypatch):
    d = ws(tmp_path, monkeypatch)
    src = tmp_path / "pull" / "posts"
    src.mkdir(parents=True)
    (src / "s.json").write_text(json.dumps({"slug": "s", "body": "Новый\n\nТекст", "threads": "Т {LINK}", "x": "",
                                            "status": "ready", "targets": ["tg", "vk"], "updatedBy": "u_1"}),
                                encoding="utf-8")
    lines = editor.pull(tmp_path / "pull")
    p = post.load(d)
    assert p.title == "Новый" and p.targets == ["tg", "vk"]
    assert (d / "threads.txt").read_text(encoding="utf-8").strip() == "Т {LINK}"
    assert "ready" in lines[0]


def test_sheets_make_cover_and_contact_sheet(tmp_path, monkeypatch):
    from PIL import Image
    d = ws(tmp_path, monkeypatch)
    (d / "album").mkdir()
    for i, c in enumerate(("red", "blue"), 1):
        Image.new("RGB", (3000, 2000), c).save(d / "album" / f"0{i}.jpg")
    (d / "post.md").write_text("---\nmedia: [album/01.jpg, album/02.jpg]\n---\nСтарый\n\nТекст\n", encoding="utf-8")
    files = editor.sheets("B")
    assert files == [d / "cover.jpg", d / "sheet.jpg"]
    with Image.open(d / "cover.jpg") as im:
        assert max(im.size) <= 1600 and im.getpixel((10, 10))[0] > 200   # обложка — первый кадр альбома


def test_docs_take_checks_from_file(tmp_path, monkeypatch):
    d = ws(tmp_path, monkeypatch)
    (d / "checks.txt").write_text("Цена в евро — сверить.\n", encoding="utf-8")
    editor.docs("B", None)
    doc = json.loads((tmp_path / "batches" / "B" / "docs" / "s.json").read_text(encoding="utf-8"))
    assert doc["checks"] == "Цена в евро — сверить."


def test_pull_writes_status(tmp_path, monkeypatch):
    d = ws(tmp_path, monkeypatch)
    src = tmp_path / "pull2" / "posts"
    src.mkdir(parents=True)
    (src / "s.json").write_text(json.dumps({"slug": "s", "status": "hidden"}), encoding="utf-8")
    editor.pull(src)
    assert post.load(d).meta["status"] == "hidden"


def test_docs_mark_posts_draft_and_pass_limits(tmp_path, monkeypatch):
    d = ws(tmp_path, monkeypatch)
    editor.docs("B", None)
    assert post.load(d).meta["status"] == "draft"        # без «Готово» из «Редакции» новость не выйдет
    st = json.loads((tmp_path / "batches" / "B" / "docs" / "_settings.json").read_text(encoding="utf-8"))
    assert st["limits"]["tg_album"] == 1024               # tg: {} — без Premium


def test_pull_empty_or_incomplete_is_error(tmp_path, monkeypatch, capsys):
    from rk.cli import main
    ws(tmp_path, monkeypatch)
    empty = tmp_path / "batches" / "B" / "pull"
    empty.mkdir(parents=True)
    assert main(["pull", str(empty)]) == 1
    assert "нет в выгрузке: s" in capsys.readouterr().out
