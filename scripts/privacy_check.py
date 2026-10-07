#!/usr/bin/env python3
"""Ищет в дереве токены, IP-адреса, почту, телефоны и — по личному списку — имена, каналы и ID. Код 1 — есть находки.

  python scripts/privacy_check.py [папка] [--exclude docs,.superpowers]

Личный список хранится ВНЕ репозитория (иначе он сам и есть утечка): файл из PRIVACY_DENY_FILE или
~/.config/redakciya-dev/privacy_deny.txt, по строке «регэксп<TAB>метка», # — комментарий. В CI — секрет PRIVACY_DENY.
"""
import os
import pathlib
import re
import sys

GENERIC = [
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "IP-адрес"),
    (r"vk1\.a\.[\w-]{40,}|\b\d{8,10}:AA[\w-]{30,}|gh[op]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9-]{20,}|EAA[A-Za-z0-9]{40,}",
     "токен"),
    (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "почта"),
    (r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b", "телефон"),
]
ALLOW = re.compile(r"^(127\.0\.0\.1|0\.0\.0\.0|[\w.+-]*@(example\.(com|ru|org)|users\.noreply\.github\.com)|noreply@[\w.-]+)$",
                   re.I)
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
SELF = {"privacy_check.py", "test_privacy_check.py"}
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".zip", ".pdf", ".webp"}


def personal() -> list[tuple[str, str]]:
    f = pathlib.Path(os.environ.get("PRIVACY_DENY_FILE") or
                     pathlib.Path.home() / ".config" / "redakciya-dev" / "privacy_deny.txt").expanduser()
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            pat, _, label = line.partition("\t")
            out.append((pat.strip(), label.strip() or "личное"))
    return out


def scan(root: pathlib.Path, exclude: set[str] = frozenset()) -> list[str]:
    patterns = GENERIC + personal()
    out = []
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if not f.is_file() or f.name in SELF or SKIP_DIRS & set(rel.parts) or (rel.parts and rel.parts[0] in exclude):
            continue
        if f.suffix.lower() in BINARY:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for pat, label in patterns:
                for m in re.finditer(pat, line, re.I):
                    if ALLOW.match(m.group(0)):
                        continue
                    out.append(f"{rel}:{n}: {label}: {m.group(0)[:40]}")
    return out


def main() -> int:
    args = sys.argv[1:]
    exclude: set[str] = set()
    if "--exclude" in args:
        i = args.index("--exclude")
        exclude = set(args[i + 1].split(","))
        del args[i:i + 2]
    root = pathlib.Path(args[0] if args else ".").resolve()
    found = scan(root, exclude)
    if not personal():
        print("(личного списка нет — проверены только токены, IP, почта и телефоны)", file=sys.stderr)
    print("\n".join(found) if found else "чисто")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
