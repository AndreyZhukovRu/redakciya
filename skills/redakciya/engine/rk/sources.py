"""Окно «Источники»: разбор вставленных ссылок, очистка меток, дубли с уже написанным."""
from __future__ import annotations

import re
import urllib.parse

from rk import config
from rk.cli import register

URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
TRACK = re.compile(r"^(utm_.*|fbclid|yclid|gclid|_openstat|vgo_ee|mc_cid|mc_eid)$", re.I)


def clean(url: str) -> str:
    u = urllib.parse.urlsplit(url.rstrip(".,;"))
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACK.match(k)]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ""))


def key(url: str) -> str:
    """Ключ для сравнения: без схемы, www и хвостового слеша."""
    return re.sub(r"^https?://(www\.)?", "", url.lower()).rstrip("/")


def parse(text: str) -> list[tuple[str, str]]:
    """Все ссылки из вставки; пометка — текст строки вне ссылок (общий для ссылок этой строки)."""
    out = []
    for line in text.splitlines():
        urls = URL.findall(line)
        if not urls:
            continue
        note = URL.sub(" ", line)
        note = re.sub(r"\s+", " ", note).strip(" —–-:;,()")
        out += [(clean(u), note) for u in urls]
    return out


def normalize(line: str) -> tuple[str, str] | None:
    items = parse(line)
    return items[0] if items else None


def dedupe(items, seen: set[str]):
    seen_keys = {key(u) for u in seen}
    new, dup, keys = [], [], set()
    for u, n in items:
        k = key(u)
        if k in seen_keys:
            dup.append((u, n))
        elif k not in keys:
            keys.add(k)
            new.append((u, n))
    return new, dup


def seen_urls() -> set[str]:
    """Адреса из research.md и sources.txt прошлых новостей — чтобы не писать одно и то же дважды."""
    out: set[str] = set()
    for f in list((config.home() / "posts").glob("*/research.md")) + list((config.home() / "posts").glob("*/sources.txt")):
        out |= {clean(u) for u in URL.findall(f.read_text(encoding="utf-8", errors="ignore"))}
    return out


def _check_setup(ap):
    ap.add_argument("file", nargs="?", help="файл со ссылками (без него — стандартный ввод)")


@register("sources-check", _check_setup)
def _check_cmd(a) -> int:
    """Ссылки из чата: какие новые, о каких уже писали (по research.md и sources.txt прошлых новостей)."""
    import sys
    text = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
    new, dup = dedupe(parse(text), seen_urls())
    for u, n in dup:
        print(f"уже писали: {u}")
    for u, n in new:
        print(f"новая: {u}" + (f" — {n}" if n else ""))
    return 0
