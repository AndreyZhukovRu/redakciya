"""Тексты площадок из одного post.md: HTML (Telegram, MAX), простой текст (VK, YouTube, VK-канал), короткие версии."""
from __future__ import annotations

import html as _html
import re

LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
LIMITS = {"tg_bot": 1024, "tg": 4096, "max": 4000, "x": 280, "threads": 500}


def html(body: str, chat: str) -> str:
    """**жирный** → <b>, [текст](url) → <a href>, {{CHAT}} → ссылка на чат площадки."""
    body = body.replace("{{CHAT}}", chat)
    links: list[tuple[str, str]] = []

    def stash(m):
        links.append((m.group(1), m.group(2)))
        return f"\x00{len(links) - 1}\x00"
    tmp = _html.escape(LINK.sub(stash, body), quote=False)
    tmp = BOLD.sub(r"<b>\1</b>", tmp)

    def unstash(m):
        text, url = links[int(m.group(1))]
        text = BOLD.sub(r"<b>\1</b>", _html.escape(text, quote=False))
        return f'<a href="{_html.escape(url)}">{text}</a>'
    return re.sub(r"\x00(\d+)\x00", unstash, tmp).strip()


def plain(body: str, chat: str) -> str:
    """Для площадок без скрытых ссылок: «текст (url)», жирный снят."""
    body = body.replace("{{CHAT}}", chat)

    def rep(m):
        text, url = m.group(1), m.group(2)
        bare = re.sub(r"^https?://", "", url).rstrip("/")
        return url if text.strip().rstrip("/") in (url, bare) else f"{text} ({url})"
    return BOLD.sub(r"\1", LINK.sub(rep, body)).strip()


def visible_len(s: str, is_html: bool) -> int:
    """Длина так, как её считает Telegram: видимый текст в UTF-16."""
    if is_html:
        s = _html.unescape(re.sub(r"<[^>]+>", "", s))
    return len(s.encode("utf-16-le")) // 2


def short(text: str, link: str) -> str:
    return text.replace("{LINK}", link).strip()


def check_limits(p, cfg) -> list[str]:
    out = []
    plats = cfg.platforms
    if "tg" in plats:
        tg = plats.get("tg") or {}
        premium = tg.get("premium") is True and tg.get("mode") != "bot"
        lim = LIMITS["tg"] if premium or not p.media else LIMITS["tg_bot"]
        if (n := visible_len(html(p.body, cfg.chat_link("tg")), True)) > lim:
            out.append(f"Telegram {n} из {lim}" + ("" if lim == LIMITS["tg"] or tg.get("mode") == "bot" else
                       " — без Premium подпись к альбому до 1024; есть Premium — platforms.tg.premium: true"))
    if "max" in plats and (n := len(html(p.body, cfg.chat_link("max")))) > LIMITS["max"]:
        out.append(f"MAX {n} из {LIMITS['max']} (MAX считает сырой HTML)")
    for name, link_len in (("threads", 27), ("x", 23)):
        f = p.dir / f"{name}.txt"
        if name in plats and f.exists():
            raw = f.read_text(encoding="utf-8").strip()
            n = len(raw.replace("{LINK}", "")) + (link_len if "{LINK}" in raw else 0)
            if n > LIMITS[name]:
                out.append(f"{name} {n} из {LIMITS[name]}")
    return out
