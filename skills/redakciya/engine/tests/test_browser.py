import sys

from rk import browser


def test_find_chrome_windows(tmp_path, monkeypatch):
    exe = tmp_path / "Пользователь" / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Пользователь"))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert browser.find_chrome() == str(exe)


def test_find_chrome_windows_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    for v in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.setenv(v, str(tmp_path / "нет"))
    assert browser.find_chrome() is None


def test_profile_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("REDAKCIYA_SECRETS", str(tmp_path))
    assert browser.profile_dir() == tmp_path / "chrome"


def test_busy_message():
    assert browser.is_busy_error(Exception("ProcessSingleton: profile in use"))
    assert not browser.is_busy_error(Exception("net::ERR_NAME_NOT_RESOLVED"))


def test_find_edge_on_windows_without_chrome(tmp_path, monkeypatch):
    exe = tmp_path / "PF86" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "PF86"))
    for v in ("LOCALAPPDATA", "ProgramFiles"):
        monkeypatch.setenv(v, str(tmp_path / "нет"))
    assert browser.find_chrome() == str(exe)
    assert browser.channel_of(str(exe)) == "msedge"


def test_busy_message_windows():
    assert browser.is_busy_error(Exception("Opening in existing browser session."))
