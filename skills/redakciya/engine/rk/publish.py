"""rk publish <пакет>: все площадки по порядку config, без модели в цикле. Повторный запуск безопасен."""
from __future__ import annotations

import argparse
import contextlib
import os
import time

from rk import config, connectors, journal
from rk import post as P
from rk.cli import register
from rk.connectors.base import Fail


def site_link(d) -> str:
    """Ссылка для Threads/X: запись сайта, иначе пост Telegram."""
    j = journal.get(d)
    return (j.get("site") or j.get("tg") or {}).get("url", "")


def _log(bdir, line: str, echo: bool = True) -> None:
    with open(bdir / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if echo:
        print(line, flush=True)


def order_of(batch: str) -> list[str]:
    f = config.home() / "batches" / batch / "order.txt"
    slugs = [l.split("\t")[0].strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    return list(dict.fromkeys(slugs))  # повтор строки не должен давать второй пост


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) на Windows убил бы процесс
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _lock(bdir):
    """Один rk publish на пакет: второй запуск, пока идёт первый, задублировал бы все площадки."""
    f = bdir / ".lock"
    for _ in range(2):
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                pid = int(f.read_text(encoding="utf-8").strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if _alive(pid):
                raise Busy(f"выкладка этого пакета уже идёт (процесс {pid}) — дождитесь «ВСЁ» в run.log; "
                           f"если такого процесса нет, удалите {f}") from None
            f.unlink(missing_ok=True)
    else:
        raise Busy(f"не удалось взять замок {f}")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        f.unlink(missing_ok=True)


class Busy(RuntimeError):
    pass


# статусы из «Редакции» (rk pull пишет их в шапку post.md): такие новости не выкладываются
SKIP = {"hidden": "не публикуем", "draft": "не отмечена «готово»", "writing": "ещё пишется"}


def run(batch: str, only: list[str] | None, dry: bool, again: bool) -> int:
    bdir = config.home() / "batches" / batch
    try:
        with _lock(bdir):
            return _run(batch, bdir, only, dry, again)
    except Busy as e:
        print(f"✗ {e}", flush=True)  # не в run.log: там идёт первый запуск
        return 1


def _run(batch: str, bdir, only: list[str] | None, dry: bool, again: bool) -> int:
    cfg = config.load()
    rc = 0
    _log(bdir, f"=== {time.strftime('%d.%m %H:%M:%S')} пакет {batch}{' (проверка без отправки)' if dry else ''}")
    posts = []
    for s in order_of(batch):
        p = P.load(P.posts_dir() / s)
        why = SKIP.get(str(p.meta.get("status") or ""))
        if why:
            _log(bdir, f"· {p.slug}: {why}")
        else:
            posts.append(p)
    for key in [k for k in cfg.publish_order if k in cfg.platforms and (not only or k in only)]:
        conn = connectors.make(cfg, key)
        seq = list(reversed(posts)) if key in cfg.reverse_order else posts
        todo = [p for p in seq if key in (p.targets if p.targets is not None else cfg.defaults)
                and (dry or again or not journal.has(p.dir, key))]
        if not todo:
            continue
        retry = getattr(conn, "retry_safe", True)
        try:
            ctx = contextlib.nullcontext(None)
            if conn.uses_browser:  # и для --dry: форма заполняется в настоящем браузере
                from rk import browser
                ctx = browser.session()
            with ctx as bctx:
                for p in todo:
                    if not dry and not again and journal.has(p.dir, key):  # могло выйти, пока шли другие
                        continue
                    rc |= _one(bdir, conn, key, p, bctx, dry, retry)
        except Exception as e:  # noqa: BLE001  (браузер не открылся — пропускаем площадку, пакет идёт дальше)
            rc = 1
            _log(bdir, f"✗ {key}: {str(e).splitlines()[0] if str(e) else e.__class__.__name__}")
    _log(bdir, f"=== ВСЁ {time.strftime('%H:%M:%S')}")
    return rc


def _one(bdir, conn, key: str, p, bctx, dry: bool, retry: bool) -> int:
    link = site_link(p.dir)
    if conn.needs_site_link and not link:
        _log(bdir, f"… {p.slug} {key}: ждёт ссылку на сайт или Telegram")
        return 0
    for attempt in (1, 2):
        sent = []
        if not dry:
            conn.on_send = lambda: (sent.append(1), journal.put(p.dir, key, "", journal.AFTER_CLICK))
        page = None
        if bctx is not None:
            from rk import browser
            page = browser.new_page(bctx)
        try:
            res = conn.publish(p, dry, page=page, site_link=link)
            if dry:
                _log(bdir, f"◦ {p.slug} {key}: {res.note or 'готово к отправке'}")
                return 0
            journal.put(p.dir, key, res.url, res.note)
            _log(bdir, f"{'⚠' if res.note else '✓'} {p.slug} {key}: {res.url}" + (f" — {res.note}" if res.note else ""))
            return 1 if res.note else 0
        except Fail as e:
            _shot(page, p, key)
            if sent:
                _log(bdir, f"⚠ {p.slug} {key}: отправка начата, но не подтверждена: {e} — сверьте площадку глазами, "
                           "не вышел — уберите запись площадки из published.json этой новости и повторите")
                return 1
            if attempt == 2 or not retry:
                _log(bdir, f"✗ {p.slug} {key}: {e}")
                return 1
        except Exception as e:  # noqa: BLE001  (без автоповтора: кнопка могла уже сработать)
            _shot(page, p, key)
            why = f"{e.__class__.__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
            if sent:
                _log(bdir, f"⚠ {p.slug} {key}: отправка начата, потом сбой ({why}) — сверьте площадку глазами, "
                           "не вышел — уберите запись площадки из published.json этой новости и повторите")
            else:
                _log(bdir, f"✗ {p.slug} {key}: непредвиденная ошибка {why} — до отправки дело не дошло, можно повторить")
            return 1
        finally:
            conn.on_send = None
            if page is not None:
                with contextlib.suppress(Exception):
                    page.close()
    return 1


def _shot(page, p, key: str) -> None:
    if page is not None:
        with contextlib.suppress(Exception):
            page.screenshot(path=str(p.dir / f".web-{key}.png"))


def _setup(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("batch", help="имя папки в batches/")
    ap.add_argument("--only", help="только эти площадки, через запятую")
    ap.add_argument("--dry", action="store_true", help="всё заполнить и проверить, не отправлять")
    ap.add_argument("--again", action="store_true", help="перевыложить ВЕСЬ пакет туда, где уже вышло (для одной новости — уберите её запись из published.json)")


@register("publish", _setup)
def _cmd(a) -> int:
    return run(a.batch, a.only.split(",") if a.only else None, a.dry, a.again)
