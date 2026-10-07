"""MAX через Bot API: бот — администратор канала (право писать). Текст — HTML, лимит 4000 по сырому HTML."""
from __future__ import annotations

import json
import mimetypes
import time

import httpx

from rk import render
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of

API = "https://botapi.max.ru"


def build_message(text: str, atts: list[dict]) -> dict:
    return {"text": text, "format": "html", "attachments": atts or None, "disable_link_preview": True}


class MaxBot(Connector):
    key = "max"

    def _headers(self) -> dict:
        return {"Authorization": self.cfg.secret(self.opts.get("token_file", "max_token"))}

    def login(self) -> None:
        print("MAX: создайте бота у @MasterBot в MAX, сохраните его токен одной строкой в файл "
              "~/.config/redakciya/max_token и добавьте бота администратором канала с правом публикации. "
              "ID канала — в config.platforms.max.channel_id (rk check покажет название канала).")

    def _check(self, c: httpx.Client, h: dict) -> str:
        me = c.get("/me", headers=h).json()
        ch = c.get(f"/chats/{self.opts['channel_id']}", headers=h).json()
        if "title" not in ch:
            raise Fail(f"канал {self.opts['channel_id']} недоступен боту: {ch}")
        return f"бот «{me.get('name')}», канал «{ch['title']}»"

    def check(self) -> str:
        with httpx.Client(base_url=self.opts.get("api", API), timeout=30) as c:
            return self._check(c, self._headers())

    def _post_message(self, c: httpx.Client, h: dict, body: dict, sleep=time.sleep) -> str:
        for attempt in range(20):  # видео MAX обрабатывает не мгновенно
            r = c.post("/messages", params={"chat_id": self.opts["channel_id"]}, headers=h, json=body)
            d = r.json()
            if r.status_code == 200 and "message" in d:
                return d["message"].get("url") or f'mid {d["message"]["body"]["mid"]}'
            if "not.ready" in json.dumps(d) or "not ready" in json.dumps(d).lower():
                sleep(3 + attempt)
                continue
            raise Fail(f"MAX: {r.status_code} {d}")
        raise Fail("MAX: вложение так и не обработалось")

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = render.html(p.body, self.cfg.chat_link("max"))
        if len(text) > render.LIMITS["max"]:
            raise Fail(f"MAX {len(text)} из {render.LIMITS['max']} (считается сырой HTML) — сократите текст")
        files = media_of(p)
        if dry:
            return Result(url="", note=f"готово к отправке: {len(text)} зн. HTML, медиа {len(files)}")
        h, atts = self._headers(), []
        with httpx.Client(base_url=self.opts.get("api", API), timeout=600) as c:
            for m in files:
                kind = "video" if str(m).lower().endswith((".mp4", ".mov")) else "image"
                up = c.post("/uploads", params={"type": kind}, headers=h).json()
                with open(m, "rb") as f:
                    r = c.post(up["url"], files={"data": (m.name, f, mimetypes.guess_type(str(m))[0] or "application/octet-stream")})
                if kind == "video":
                    atts.append({"type": "video", "payload": {"token": up["token"]}})
                else:
                    photos = r.json().get("photos", {})
                    atts.append({"type": "image", "payload": {"photos": photos} if photos else r.json()})
            self.sending()
            return Result(url=self._post_message(c, h, build_message(text, atts)))
