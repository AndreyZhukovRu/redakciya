from rk import journal


def test_put_get(tmp_path):
    journal.put(tmp_path, "tg", "https://t.me/c/1")
    assert journal.has(tmp_path, "tg") and journal.get(tmp_path)["tg"]["url"] == "https://t.me/c/1"
    assert not journal.has(tmp_path, "max")


def test_after_click_is_recorded_and_not_retried(tmp_path):
    journal.put(tmp_path, "x", "https://x.com/me", note=journal.AFTER_CLICK + ": лента не обновилась")
    assert journal.has(tmp_path, "x") and journal.needs_check(tmp_path, "x")
    assert not journal.needs_check(tmp_path, "tg")


def test_atomic_no_tmp_left(tmp_path):
    journal.put(tmp_path, "max", "u")
    journal.put(tmp_path, "vk", "v")
    assert [p.name for p in tmp_path.iterdir()] == ["published.json"]
    assert set(journal.get(tmp_path)) == {"max", "vk"}
