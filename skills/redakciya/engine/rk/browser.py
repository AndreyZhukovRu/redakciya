"""Отдельный профиль Chrome для X, YouTube, VK, Threads, Дзена и Telegram Web. Личный Chrome не трогается."""
from __future__ import annotations

import contextlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

from rk import config


class BrowserBusy(RuntimeError):
    pass


def profile_dir() -> pathlib.Path:
    return config.secrets_dir() / "chrome"


def find_chrome() -> str | None:
    if sys.platform == "darwin":
        p = pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return str(p) if p.exists() else None
    if sys.platform.startswith("win"):
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base and (p := pathlib.Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe").exists():
                return str(p)
        for env in ("ProgramFiles(x86)", "ProgramFiles"):  # Edge есть в каждой Windows 11 — тот же Chromium
            base = os.environ.get(env)
            if base and (p := pathlib.Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe").exists():
                return str(p)
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def channel_of(exe: str) -> str | None:
    """Канал Playwright для найденного браузера; None — запускать по пути (chromium)."""
    name = pathlib.Path(exe).name.lower()
    return "msedge" if "msedge" in name else None if "chromium" in name else "chrome"


def is_busy_error(e: Exception) -> bool:
    return bool(re.search(r"ProcessSingleton|SingletonLock|already in use|profile.*in use|existing browser session",
                          str(e), re.I))


def open_login(urls: list[str]) -> None:
    """Обычный Chrome с профилем публикатора — человек сам входит в площадки и закрывает окно."""
    exe = find_chrome()
    if not exe:
        raise BrowserBusy("не найден ни Google Chrome, ни Microsoft Edge — установите Chrome "
                          "(Mac: google.com/chrome; Windows: winget install Google.Chrome)")
    profile_dir().mkdir(parents=True, exist_ok=True)
    kw = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
          if sys.platform.startswith("win") else {"start_new_session": True})  # окно живёт после выхода rk
    subprocess.Popen([exe, f"--user-data-dir={profile_dir()}", "--no-first-run", "--no-default-browser-check", *urls],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


@contextlib.contextmanager
def session(headless: bool = False):
    """Playwright с тем же профилем. Подключаться к открытому окну по CDP нельзя — зависает; окно входа закрыть."""
    from playwright.sync_api import sync_playwright
    profile_dir().mkdir(parents=True, exist_ok=True)
    kw = dict(headless=headless, locale="ru-RU",
              viewport={"width": 1440, "height": 900} if headless else None,
              args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                    "--no-default-browser-check", "--window-size=1440,960"],
              # без --use-mock-keychain Chrome читает куки, сохранённые при обычном входе (open_login)
              ignore_default_args=["--enable-automation", "--use-mock-keychain"])
    exe = find_chrome()
    if exe:
        ch = channel_of(exe)
        if ch:
            kw["channel"] = ch
        else:
            kw["executable_path"] = exe
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(str(profile_dir()), **kw)
        except Exception as e:  # noqa: BLE001
            if is_busy_error(e):
                raise BrowserBusy("профиль Chrome публикатора занят — закройте его окно и повторите") from None
            raise
        try:
            yield ctx
        finally:
            ctx.close()


def new_page(ctx):
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())  # «Покинуть сайт?» и подобное не должны вешать прогон
    page.set_default_timeout(30000)
    return page


def wait_js(page, expr: str, timeout: float, arg=None, tick=None):
    """Опрашивает выражение, пока оно не станет истинным. tick() — действие на каждом шаге."""
    end = time.time() + timeout
    while True:
        if tick:
            tick()
        v = page.evaluate(expr, arg)
        if v or time.time() > end:
            return v
        page.wait_for_timeout(700)


PASTE_TEXT_JS = """([sel, t]) => {
  const el = (sel && document.querySelector(sel)) || document.activeElement;
  if (!el) return -1;
  el.focus();
  const dt = new DataTransfer(); dt.setData('text/plain', t);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return (el.innerText || '').trim().length;
}"""

PASTE_HTML_JS = """([sel, h, t]) => {
  const el = document.querySelector(sel);
  if (!el) return -1;
  el.focus();
  const dt = new DataTransfer(); dt.setData('text/html', h); dt.setData('text/plain', t);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return (el.innerText || '').trim().length;
}"""
