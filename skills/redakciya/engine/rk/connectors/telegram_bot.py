"""Telegram ботом (Bot API): бот — администратор канала. Подпись к медиа — не длиннее 1024 знаков."""
from __future__ import annotations

import json

import httpx

from rk import render
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of


class TelegramBot(Connector):
    key = "tg"

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = render.html(p.body, self.cfg.chat_link("tg"))
        n = render.visible_len(text, True)
        lim = render.LIMITS["tg_bot"] if p.media else render.LIMITS["tg"]
        if n > lim:
            raise Fail(f"текст {n} зн., бот может не больше {lim} (с фото) — выберите mode: web или telethon")
        if dry:
            return Result(url="", note=f"готово к отправке: {n} зн., медиа {len(p.media)}")
        ch = self.opts.get("channel", "")
        api = f"https://api.telegram.org/bot{self.cfg.secret(self.opts.get('token_file', 'tg_bot_token'))}"
        files_list = media_of(p)
        with httpx.Client(timeout=300) as c:
            self.sending()
            if not files_list:
                r = c.post(f"{api}/sendMessage", data={"chat_id": ch, "text": text, "parse_mode": "HTML",
                                                       "link_preview_options": json.dumps({"is_disabled": True})})
            elif len(files_list) == 1:
                kind = "video" if str(files_list[0]).lower().endswith((".mp4", ".mov")) else "photo"
                with open(files_list[0], "rb") as f:
                    data = {"chat_id": ch, "caption": text, "parse_mode": "HTML"}
                    if kind == "video":
                        data["supports_streaming"] = "true"
                    r = c.post(f"{api}/send{kind.title()}", data=data, files={kind: f})
            else:
                files, group = {}, []
                for i, m in enumerate(files_list):
                    kind = "video" if str(m).lower().endswith((".mp4", ".mov")) else "photo"
                    files[f"f{i}"] = open(m, "rb")
                    item = {"type": kind, "media": f"attach://f{i}"}
                    if i == 0:
                        item.update(caption=text, parse_mode="HTML")
                    group.append(item)
                r = c.post(f"{api}/sendMediaGroup", data={"chat_id": ch, "media": json.dumps(group)}, files=files)
            d = r.json()
        if not d.get("ok"):
            raise Fail(f"Telegram: {d.get('description', d)}")
        res = d["result"][0] if isinstance(d["result"], list) else d["result"]
        return Result(url=f"https://t.me/{ch.lstrip('@')}/{res['message_id']}")
