import json

from rk import style


def test_diff_sentences(tmp_path):
    b = tmp_path / "before"; a = tmp_path / "pull" / "posts"; b.mkdir(); a.mkdir(parents=True)
    (b / "s.json").write_text(json.dumps({"slug": "s", "body": "Заголовок\n\nДля нас с вами это важно. Цена $10."}), encoding="utf-8")
    (a / "s.json").write_text(json.dumps({"slug": "s", "body": "Заголовок\n\nЭто важно. Цена $10.", "editedBy": "u1"}), encoding="utf-8")
    out = style.diff(b, tmp_path / "pull")
    assert "− Для нас с вами это важно." in out and "+ Это важно." in out and "u1" in out


def test_diff_skips_unchanged_and_missing(tmp_path):
    b = tmp_path / "before"; a = tmp_path / "pull" / "posts"; b.mkdir(); a.mkdir(parents=True)
    (b / "same.json").write_text(json.dumps({"slug": "same", "body": "Т\n\nОдно."}), encoding="utf-8")
    (a / "same.json").write_text(json.dumps({"slug": "same", "body": "Т\n\nОдно."}), encoding="utf-8")
    (a / "new.json").write_text(json.dumps({"slug": "new", "body": "Т\n\nДругое."}), encoding="utf-8")
    out = style.diff(b, tmp_path / "pull")
    assert "same" not in out and "new" not in out
    assert "правок нет" in out


def test_parse_feed():
    html = '<div class="tgme_widget_message_wrap"><div data-post="c/5"><div class="tgme_widget_message_text">Т<br>x</div><time datetime="2026-10-01T00:00:00+00:00"></time></div></div>'
    assert style.parse_feed(html) == [{"id": 5, "date": "2026-10-01T00:00:00+00:00", "text": "Т\nx"}]


def test_parse_feed_strips_tags_and_skips_media_only():
    html = (
        '<div class="tgme_widget_message_wrap"><div data-post="c/7"><div class="tgme_widget_message_text">'
        '<b>Жирный</b> и <a href="https://e.com">ссылка</a> &amp; ещё</div><time datetime="d7"></time></div></div>'
        '<div class="tgme_widget_message_wrap"><div data-post="c/8"><time datetime="d8"></time></div></div>'
    )
    assert style.parse_feed(html) == [{"id": 7, "date": "d7", "text": "Жирный и ссылка & ещё"}]


def test_summary_counts():
    posts = [
        {"id": 1, "date": "", "text": "Заголовок\n\n— пункт\n— пункт"},
        {"id": 2, "date": "", "text": "Просто текст"},
    ]
    s = style.summary(posts, html={1: "<b>x</b>", 2: '<a href="u">y</a>'})
    assert s["posts"] == 2 and s["lists"] == 0.5 and s["bold"] == 0.5 and s["links"] == 0.5
    assert len(s["samples"]) == 2


def test_summary_counts_symbol_bullets():
    posts = [{"id": 1, "date": "", "text": "Что будет:\n⚬ чай\n⚬ настолки"}, {"id": 2, "date": "", "text": "Итог:\n▪️ раз\n▪️ два"}]
    assert style.summary(posts)["lists"] == 1.0
