import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).parent


def run(tmp: pathlib.Path, *extra, env=None) -> subprocess.CompletedProcess:
    import os
    e = {**os.environ, "PRIVACY_DENY_FILE": str(tmp / "нет-такого-файла")}
    e.update(env or {})
    return subprocess.run([sys.executable, str(HERE / "privacy_check.py"), str(tmp), *extra],
                          capture_output=True, text=True, env=e)


def deny(tmp: pathlib.Path) -> dict:
    f = tmp.parent / f"{tmp.name}-deny.txt"
    f.write_text("# личный список — вне репозитория\nиван\\w*\\s+петров\\w*\tимя\nivpetrov_chan|petrovfoto\tканалы\n"
                 "555000111\tID\n", encoding="utf-8")
    return {"PRIVACY_DENY_FILE": str(f)}


def test_clean(tmp_path):
    (tmp_path / "a.md").write_text("Канал: @my_channel, почта noreply@example.com\n", encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_generic_without_deny_list(tmp_path):
    (tmp_path / "b.py").write_text('TOKEN = "vk1.a.' + "x" * 60 + '"\nIP = "203.0.113.7"\n'
                                   'MAIL = "ivan.p@mail.ru"\nTEL = "+7 (999) 123-45-67"\n', encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 1
    for n in (1, 2, 3, 4):
        assert f"b.py:{n}" in r.stdout


def test_deny_list_from_file(tmp_path):
    (tmp_path / "a.md").write_text("Пишет Ивана Петрова в t.me/ivpetrov_chan\nGID = 555000111\n", encoding="utf-8")
    assert run(tmp_path).returncode == 0                       # без личного списка не видно
    r = run(tmp_path, env=deny(tmp_path))
    assert r.returncode == 1 and "a.md:1" in r.stdout and "a.md:2" in r.stdout


def test_script_itself_holds_no_personal_data():
    src = (HERE / "privacy_check.py").read_text(encoding="utf-8")
    import re
    sys.path.insert(0, str(HERE))
    import privacy_check
    assert not re.search(r"\d{6,}", src)          # ни одного ID группы, канала или приложения
    for pat, _ in privacy_check.personal():      # личный список (если он есть на этой машине) в скрипт не попал
        assert not re.search(pat, src, re.I), pat


def test_exclude(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "spec.md").write_text("канал ivpetrov_chan\n", encoding="utf-8")
    assert run(tmp_path, "--exclude", "docs", env=deny(tmp_path)).returncode == 0
