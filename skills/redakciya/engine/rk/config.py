"""config.yaml пользователя: площадки, порядок, финал-блок. Секреты — отдельными файлами."""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

import yaml

KNOWN = ["tg", "max", "vk", "vkch", "fb", "threads", "x", "yt", "dzen", "site"]
ORDER = ["max", "vk", "fb", "yt", "vkch", "tg", "site", "dzen", "threads", "x"]


class ConfigError(RuntimeError):
    pass


def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("REDAKCIYA_HOME", pathlib.Path.home() / "Redakciya")).expanduser()


def secrets_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("REDAKCIYA_SECRETS", pathlib.Path.home() / ".config" / "redakciya")).expanduser()


@dataclass
class Config:
    author: str = ""
    language: str = "ru"
    editor_url: str = ""
    publish_order: list[str] = field(default_factory=lambda: list(ORDER))
    defaults: list[str] = field(default_factory=list)
    reverse_order: list[str] = field(default_factory=lambda: ["vkch"])
    platforms: dict[str, dict] = field(default_factory=dict)
    closing: dict = field(default_factory=dict)
    path: pathlib.Path | None = None

    @property
    def enabled(self) -> list[str]:
        return list(self.platforms)

    def secret(self, rel: str) -> str:
        p = pathlib.Path(rel).expanduser()
        p = p if p.is_absolute() else secrets_dir() / p
        if not p.exists():
            raise ConfigError(f"нет файла {p} — выполните: rk login <площадка>")
        return p.read_text(encoding="utf-8").strip()

    def chat_link(self, platform: str) -> str:
        return (self.closing.get("chat") or {}).get(platform, "")


def load(path: pathlib.Path | None = None) -> Config:
    path = path or home() / "config.yaml"
    if not path.exists():
        raise ConfigError(f"нет {path} — выполните: rk setup")
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    plats = d.get("platforms") or {}
    bad = [k for k in plats if k not in KNOWN]
    if bad:
        raise ConfigError(f"неизвестная площадка: {', '.join(bad)} (есть: {', '.join(KNOWN)})")
    return Config(author=d.get("author", ""), language=d.get("language", "ru"), editor_url=d.get("editor_url", ""),
                  publish_order=d.get("publish_order") or list(ORDER), defaults=d.get("defaults") or list(plats),
                  reverse_order=d.get("reverse_order", ["vkch"]), platforms=plats, closing=d.get("closing") or {},
                  path=path)
