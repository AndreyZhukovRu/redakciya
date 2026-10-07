from rk import sources


def test_normalize():
    assert sources.normalize("  https://ex.com/a?utm_source=x&id=5  про бесплатные аналоги ") == \
        ("https://ex.com/a?id=5", "про бесплатные аналоги")
    assert sources.normalize("просто текст") is None
    assert sources.normalize("") is None


def test_parse_many_urls_and_text_before():
    items = sources.parse("Travel Photographer of the Year 2026 — приём до 12 октября — https://www.tpoty.com/\n"
                          "https://a.com/1 https://b.com/2?fbclid=zzz\n\nмусор без ссылки\n")
    assert items == [("https://www.tpoty.com/", "Travel Photographer of the Year 2026 — приём до 12 октября"),
                     ("https://a.com/1", ""), ("https://b.com/2", "")]


def test_dedupe():
    new, dup = sources.dedupe([("https://a/1", ""), ("https://a/1/", ""), ("http://www.b/2", "")], {"https://b/2"})
    assert [u for u, _ in new] == ["https://a/1"] and [u for u, _ in dup] == ["http://www.b/2"]


def test_seen_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    d = tmp_path / "posts" / "s"
    d.mkdir(parents=True)
    (d / "research.md").write_text("Источник: https://ex.com/news/1 и ещё (https://ex.com/2).", encoding="utf-8")
    assert {"https://ex.com/news/1", "https://ex.com/2"} <= sources.seen_urls()


def test_sources_check_command(tmp_path, monkeypatch, capsys):
    from rk.cli import main
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "posts" / "old").mkdir(parents=True)
    (tmp_path / "posts" / "old" / "research.md").write_text("источник https://example.com/old-news\n", encoding="utf-8")
    f = tmp_path / "links.txt"
    f.write_text("https://www.example.com/old-news/?utm_source=x\nhttps://example.com/new — про новое\n"
                 "https://example.com/new/\n", encoding="utf-8")
    assert main(["sources-check", str(f)]) == 0
    out = capsys.readouterr().out
    assert "уже писали: https://www.example.com/old-news" in out and "новая: https://example.com/new" in out
    assert out.count("example.com/new") == 1
