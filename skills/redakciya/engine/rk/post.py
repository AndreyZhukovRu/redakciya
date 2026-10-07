"""post.md: шапка YAML между --- и текст новости. Первая строка текста — заголовок."""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

import yaml

from rk import config

HEAD = re.compile(r"^---\n(.*?)\n---\n", re.S)


@dataclass
class Post:
    slug: str
    dir: pathlib.Path
    title: str
    body: str
    media: list[pathlib.Path] = field(default_factory=list)
    targets: list[str] | None = None
    meta: dict = field(default_factory=dict)


def posts_dir() -> pathlib.Path:
    return config.home() / "posts"


def load(d: pathlib.Path) -> Post:
    raw = (d / "post.md").read_text(encoding="utf-8")
    meta: dict = {}
    m = HEAD.match(raw)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        raw = raw[m.end():]
    body = raw.strip() + "\n"
    media = [p if (p := pathlib.Path(x)).is_absolute() else d / x for x in meta.get("media") or []]
    return Post(slug=d.name, dir=d, title=body.split("\n", 1)[0].strip(), body=body,
                media=media, targets=meta.get("to"), meta=meta)


def save_body(p: Post, body: str) -> None:
    raw = (p.dir / "post.md").read_text(encoding="utf-8")
    m = HEAD.match(raw)
    (p.dir / "post.md").write_text((m.group(0) if m else "") + body.strip() + "\n", encoding="utf-8")
    p.body = body.strip() + "\n"
    p.title = p.body.split("\n", 1)[0].strip()


def short(p: Post, name: str) -> str:
    f = p.dir / f"{name}.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""
