"""Реестр площадок: ключ из config.platforms → класс по режиму (mode)."""
from __future__ import annotations

import importlib

TABLE = {
    "tg": {"web": ("telegram_web", "TelegramWeb"), "telethon": ("telegram_telethon", "TelegramTelethon"),
           "bot": ("telegram_bot", "TelegramBot")},
    "max": {"bot": ("max_bot", "MaxBot")},
    "vk": {"api": ("vk_api", "VkApi"), "web": ("vk_web", "VkWall")},
    "vkch": {"web": ("vk_web", "VkChannel")},
    "fb": {"api": ("facebook_api", "FacebookApi")},
    "threads": {"web": ("threads_web", "ThreadsWeb"), "api": ("threads_api", "ThreadsApi")},
    "x": {"web": ("x_web", "XWeb")},
    "yt": {"web": ("youtube_web", "YoutubeWeb")},
    "dzen": {"tg_import": ("dzen", "DzenTgImport"), "web": ("dzen", "DzenWeb")},
    "site": {"wordpress": ("site_wordpress", "SiteWordpress"), "api": ("site_api", "SiteApi")},
}
DEFAULT_MODE = {"tg": "web", "max": "bot", "vk": "api", "vkch": "web", "fb": "api", "threads": "web", "x": "web", "yt": "web",
                "dzen": "tg_import", "site": "api"}


def make(cfg, key: str):
    opts = dict(cfg.platforms.get(key) or {})
    mode = opts.get("mode", DEFAULT_MODE[key])
    if mode not in TABLE[key]:
        raise ValueError(f"{key}: неизвестный режим {mode!r} (есть: {', '.join(TABLE[key])})")
    mod, cls = TABLE[key][mode]
    return getattr(importlib.import_module(f"rk.connectors.{mod}"), cls)(cfg, {**opts, "key": key})
