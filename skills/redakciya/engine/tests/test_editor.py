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


# «Перенести» в «Редакции»: status=later + publishOn — строка новости уезжает в order.txt пакета того дня

def day_ws(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("platforms: {tg: {}}\ndefaults: [tg]\n", encoding="utf-8")
    for s in ("a", "b", "c"):
        d = tmp_path / "posts" / s
        d.mkdir(parents=True)
        (d / "post.md").write_text(f"---\nmedia: []\nstatus: draft\n---\nЗаголовок {s}\n\nТекст\n", encoding="utf-8")
    b = tmp_path / "batches" / "2026-10-13"
    b.mkdir(parents=True)
    (b / "order.txt").write_text("a\thttps://a\nb\thttps://b\nc\n", encoding="utf-8")
    return tmp_path


def pull_one(tmp_path, doc):
    src = tmp_path / "batches" / "2026-10-13" / "pull" / "posts"
    src.mkdir(parents=True, exist_ok=True)
    (src / f"{doc['slug']}.json").write_text(json.dumps({"batch": "2026-10-13", **doc}), encoding="utf-8")
    return editor.pull(src)


def rows(tmp_path, batch, name="order.txt"):
    f = tmp_path / "batches" / batch / name
    return [l.split("\t")[0] for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def test_pull_later_moves_post_to_that_day(tmp_path, monkeypatch):
    day_ws(tmp_path, monkeypatch)
    lines = pull_one(tmp_path, {"slug": "b", "status": "later", "publishOn": "2026-10-14"})
    assert rows(tmp_path, "2026-10-13") == ["a", "c"] and rows(tmp_path, "2026-10-14") == ["b"]
    assert (tmp_path / "batches" / "2026-10-14" / "order.txt").read_text(encoding="utf-8") == "b\thttps://b\n"
    assert rows(tmp_path, "2026-10-14", "moved.txt") == ["b"]
    meta = post.load(tmp_path / "posts" / "b").meta
    assert meta["status"] == "later" and meta["publish_on"] == "2026-10-14"
    assert "перенесена на 14.10" in lines[0]
    assert pull_one(tmp_path, {"slug": "b", "status": "later", "publishOn": "2026-10-14"})  # повтор ничего не двигает
    assert rows(tmp_path, "2026-10-14") == ["b"] and rows(tmp_path, "2026-10-13") == ["a", "c"]


def test_pull_later_changed_day_and_back(tmp_path, monkeypatch):
    day_ws(tmp_path, monkeypatch)
    pull_one(tmp_path, {"slug": "b", "status": "later", "publishOn": "2026-10-14"})
    pull_one(tmp_path, {"slug": "b", "status": "later", "publishOn": "2026-10-15"})
    assert rows(tmp_path, "2026-10-14") == [] and rows(tmp_path, "2026-10-15") == ["b"]
    assert rows(tmp_path, "2026-10-14", "moved.txt") == [] and rows(tmp_path, "2026-10-15", "moved.txt") == ["b"]
    lines = pull_one(tmp_path, {"slug": "b", "status": "draft", "publishOn": None})
    assert rows(tmp_path, "2026-10-13") == ["a", "c", "b"] and rows(tmp_path, "2026-10-15") == []
    assert "publish_on" not in post.load(tmp_path / "posts" / "b").meta
    assert "возвращена в пакет 2026-10-13" in lines[0]


def test_pull_does_not_pull_back_hand_moved_post(tmp_path, monkeypatch):
    day_ws(tmp_path, monkeypatch)
    nxt = tmp_path / "batches" / "2026-10-14"
    nxt.mkdir()
    (nxt / "order.txt").write_text("x\n", encoding="utf-8")   # перенесли руками, без кнопки
    (tmp_path / "posts" / "x").mkdir()
    (tmp_path / "posts" / "x" / "post.md").write_text("---\nmedia: []\n---\nX\n\nТекст\n", encoding="utf-8")
    pull_one(tmp_path, {"slug": "x", "status": "draft"})
    assert rows(tmp_path, "2026-10-14") == ["x"] and "x" not in rows(tmp_path, "2026-10-13")


def test_pull_later_with_bad_day_stays(tmp_path, monkeypatch):
    day_ws(tmp_path, monkeypatch)
    lines = pull_one(tmp_path, {"slug": "a", "status": "later", "publishOn": "2026-10-13"})
    assert rows(tmp_path, "2026-10-13") == ["a", "b", "c"] and "не понят" in lines[0]
    assert post.load(tmp_path / "posts" / "a").meta["status"] == "later"   # и всё равно не выйдет: rk publish пропустит


def test_docs_for_carried_post_is_update_not_set(tmp_path, monkeypatch):
    day_ws(tmp_path, monkeypatch)
    pull_one(tmp_path, {"slug": "b", "status": "later", "publishOn": "2026-10-14"})
    nxt = tmp_path / "batches" / "2026-10-14"
    (nxt / "order.txt").write_text("a2\n" + (nxt / "order.txt").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "posts" / "a2").mkdir()
    (tmp_path / "posts" / "a2" / "post.md").write_text("---\nmedia: []\n---\nНовая\n\nТекст\n", encoding="utf-8")
    editor.docs("2026-10-14", None)
    docs = nxt / "docs"
    assert (docs / "a2.json").exists() and not (docs / "b.json").exists()
    assert json.loads((docs / "moved" / "b.json").read_text(encoding="utf-8")) == {
        "batch": "2026-10-14", "order": 2, "status": "draft", "publishOn": None}
    meta = post.load(tmp_path / "posts" / "b").meta
    assert meta["status"] == "draft" and "publish_on" not in meta
