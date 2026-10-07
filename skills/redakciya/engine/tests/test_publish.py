import pytest

from rk import connectors, journal, publish
from rk.connectors.base import Connector, Fail, Result

CALLS = []


class Fake(Connector):
    fail_once: set = set()
    fail_always: set = set()

    def publish(self, p, dry, page=None, site_link=""):
        CALLS.append((self.key, p.slug, site_link))
        if (self.key, p.slug) in Fake.fail_always:
            raise Fail("всегда сбой")
        if (self.key, p.slug) in Fake.fail_once:
            Fake.fail_once.discard((self.key, p.slug))
            raise Fail("сбой")
        return Result(url=f"https://{self.key}/{p.slug}")


class FakeLink(Fake):
    needs_site_link = True


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("REDAKCIYA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "platforms: {max: {}, tg: {mode: web}, x: {}, vkch: {}}\npublish_order: [max, vkch, tg, x]\n", encoding="utf-8")
    for s, to in (("a", "[max, tg, x, vkch]"), ("b", "[max, x, vkch]")):
        d = tmp_path / "posts" / s
        d.mkdir(parents=True)
        (d / "post.md").write_text(f"---\nmedia: []\nto: {to}\n---\nЗаголовок {s}\n\nТекст\n", encoding="utf-8")
    (tmp_path / "batches" / "B").mkdir(parents=True)
    (tmp_path / "batches" / "B" / "order.txt").write_text("a\nb\n", encoding="utf-8")
    monkeypatch.setattr(connectors, "make", lambda cfg, k: (FakeLink if k == "x" else Fake)(cfg, {"key": k}))
    CALLS.clear()
    Fake.fail_once, Fake.fail_always = set(), set()
    return tmp_path


def test_order_targets_reverse_and_links(ws):
    assert publish.run("B", None, False, False) == 0
    assert [(k, s) for k, s, _ in CALLS] == [("max", "a"), ("max", "b"), ("vkch", "b"), ("vkch", "a"),
                                             ("tg", "a"), ("x", "a")]
    assert ("x", "a", "https://tg/a") in CALLS


def test_rerun_no_duplicates_and_retry(ws):
    Fake.fail_once = {("max", "a")}
    publish.run("B", None, False, False)
    assert journal.has(ws / "posts" / "a", "max")
    first = len(CALLS)
    publish.run("B", None, False, False)
    assert len(CALLS) == first


def test_x_without_link_waits(ws):
    publish.run("B", None, False, False)
    assert not journal.has(ws / "posts" / "b", "x")
    assert "ждёт ссылку" in (ws / "batches" / "B" / "run.log").read_text(encoding="utf-8")


def test_persistent_failure_reported_not_journaled(ws):
    Fake.fail_always = {("tg", "a")}
    assert publish.run("B", None, False, False) == 1
    assert not journal.has(ws / "posts" / "a", "tg")
    assert "✗ a tg: всегда сбой" in (ws / "batches" / "B" / "run.log").read_text(encoding="utf-8")


def test_only_and_dry(ws):
    publish.run("B", ["max"], True, False)
    assert {k for k, _, _ in CALLS} == {"max"}
    assert not journal.has(ws / "posts" / "a", "max")


def test_unexpected_error_does_not_abort_batch(ws, tmp_path):
    class Boom(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            if self.key == "max" and p.slug == "a":
                CALLS.append((self.key, p.slug, site_link))
                raise RuntimeError("нет ffmpeg")
            return super().publish(p, dry, page, site_link)
    connectors.make = lambda cfg, k: (FakeLink if k == "x" else Boom)(cfg, {"key": k})
    assert publish.run("B", None, False, False) == 1
    log = (tmp_path / "batches" / "B" / "run.log").read_text(encoding="utf-8")
    assert "✗ a max" in log and "нет ffmpeg" in log and "=== ВСЁ" in log
    assert CALLS.count(("max", "a", "")) == 1                     # без автоповтора: могли уже нажать «опубликовать»
    assert journal.has(tmp_path / "posts" / "b", "max") and not journal.has(tmp_path / "posts" / "a", "max")


def test_hidden_and_draft_not_published(ws, tmp_path):
    for s, st in (("a", "hidden"), ("b", "draft")):
        f = tmp_path / "posts" / s / "post.md"
        f.write_text(f.read_text(encoding="utf-8").replace("---\nmedia", f"---\nstatus: {st}\nmedia", 1), encoding="utf-8")
    assert publish.run("B", None, False, False) == 0
    assert CALLS == []
    log = (tmp_path / "batches" / "B" / "run.log").read_text(encoding="utf-8")
    assert "· a: не публикуем" in log and "· b: не отмечена «готово»" in log


def test_no_auto_retry_when_connector_not_retry_safe(ws, tmp_path):
    class Once(Fake):
        retry_safe = False
    connectors.make = lambda cfg, k: (FakeLink if k == "x" else Once)(cfg, {"key": k})
    Fake.fail_once = {("max", "a")}
    publish.run("B", ["max"], False, False)
    assert CALLS.count(("max", "a", "")) == 1


def test_browser_busy_skips_platform_not_batch(ws, tmp_path, monkeypatch):
    from rk import browser

    class Web(Fake):
        uses_browser = True

    def busy(headless=False):
        raise browser.BrowserBusy("профиль занят")
    monkeypatch.setattr(browser, "session", busy)
    connectors.make = lambda cfg, k: (Web if k == "vkch" else FakeLink if k == "x" else Fake)(cfg, {"key": k})
    assert publish.run("B", None, False, False) == 1
    log = (tmp_path / "batches" / "B" / "run.log").read_text(encoding="utf-8")
    assert "✗ vkch: профиль занят" in log and "=== ВСЁ" in log
    assert journal.has(tmp_path / "posts" / "a", "tg")


def test_crash_after_send_mark_is_journaled_and_not_repeated(ws, tmp_path):
    class Crash(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            if self.key == "max" and p.slug == "a":
                CALLS.append((self.key, p.slug, site_link))
                self.sending()                       # «нажали опубликовать»
                raise TimeoutError("страница не ответила")
            return super().publish(p, dry, page, site_link)
    connectors.make = lambda cfg, k: (FakeLink if k == "x" else Crash)(cfg, {"key": k})
    assert publish.run("B", ["max"], False, False) == 1
    rec = journal.get(tmp_path / "posts" / "a")["max"]
    assert journal.AFTER_CLICK in rec["note"]
    publish.run("B", ["max"], False, False)
    assert CALLS.count(("max", "a", "")) == 1                  # второй запуск не шлёт ещё раз


def test_fail_after_send_mark_is_not_retried(ws, tmp_path):
    class LateFail(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            CALLS.append((self.key, p.slug, site_link))
            self.sending()
            raise Fail("не нашёл пост после отправки")
    connectors.make = lambda cfg, k: LateFail(cfg, {"key": k})
    publish.run("B", ["max"], False, False)
    assert CALLS.count(("max", "a", "")) == 1 and journal.needs_check(tmp_path / "posts" / "a", "max")


def test_after_click_result_journaled_and_skipped_next_time(ws, tmp_path):
    class Unsure(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            CALLS.append((self.key, p.slug, site_link))
            return Result(url="https://max/?", note=journal.AFTER_CLICK)
    connectors.make = lambda cfg, k: Unsure(cfg, {"key": k})
    assert publish.run("B", ["max"], False, False) == 1
    publish.run("B", ["max"], False, False)
    assert CALLS.count(("max", "a", "")) == 1 and journal.needs_check(tmp_path / "posts" / "a", "max")


def test_sending_mark_ignored_in_dry(ws, tmp_path):
    class DryMark(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            self.sending()
            return Result(url="", note="готово к отправке")
    connectors.make = lambda cfg, k: DryMark(cfg, {"key": k})
    publish.run("B", ["max"], True, False)
    assert not journal.has(tmp_path / "posts" / "a", "max")


def test_duplicate_order_lines_publish_once(ws, tmp_path):
    (tmp_path / "batches" / "B" / "order.txt").write_text("a\na\nb\n", encoding="utf-8")
    publish.run("B", ["max"], False, False)
    assert CALLS.count(("max", "a", "")) == 1


def test_second_run_while_first_running_refused(ws, tmp_path, capsys):
    import os
    (tmp_path / "batches" / "B" / ".lock").write_text(str(os.getpid()), encoding="utf-8")
    assert publish.run("B", None, False, False) == 1
    assert CALLS == [] and "уже идёт" in capsys.readouterr().out
    (tmp_path / "batches" / "B" / ".lock").write_text("999999", encoding="utf-8")   # процесса нет — замок старый
    assert publish.run("B", ["max"], False, False) == 0
    assert not (tmp_path / "batches" / "B" / ".lock").exists()


def test_journal_rechecked_right_before_send(ws, tmp_path):
    class Parallel(Fake):
        def publish(self, p, dry, page=None, site_link=""):
            if p.slug == "a":   # «другой процесс» успел выложить b
                journal.put(tmp_path / "posts" / "b", self.key, "https://max/b-other")
            return super().publish(p, dry, page, site_link)
    connectors.make = lambda cfg, k: Parallel(cfg, {"key": k})
    publish.run("B", ["max"], False, False)
    assert ("max", "b", "") not in CALLS
