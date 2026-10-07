"""Threads по официальному API (токен Meta, 60 дней, продлевается сам). Картинки Threads забирает только по
публичному адресу — их выкладывает площадка «сайт» (WordPress или свой API: upload_media). Без сайта — mode: web.
"""
from __future__ import annotations

import time

import httpx

from rk import config, connectors
from rk import post as P
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of
from rk.connectors.threads_web import prepare

API = "https://graph.threads.net/v1.0"


class ThreadsApi(Connector):
    key = "threads"
    needs_site_link = True

    def _token(self, c: httpx.Client) -> str:
        f = config.secrets_dir() / self.opts.get("token_file", "threads_token")
        tok = self.cfg.secret(str(f))
        if time.time() - f.stat().st_mtime > 7 * 86400:
            r = c.get("https://graph.threads.net/refresh_access_token",
                      params={"grant_type": "th_refresh_token", "access_token": tok}).json()
            tok = r["access_token"]
            f.write_text(tok, encoding="utf-8")
        return tok

    def _media_urls(self, p) -> list[str]:
        files = media_of(p)
        if not files:
            return []
        if "site" not in (self.cfg.platforms or {}):
            raise Fail("для Threads API нужен публичный адрес картинок: включите площадку site "
                       "(WordPress или свой API) — или используйте mode: web")
        return connectors.make(self.cfg, "site").upload_media(files)

    def _wait(self, c, cid, tok):
        for _ in range(60):
            s = c.get(f"{API}/{cid}", params={"fields": "status,error_message", "access_token": tok}).json()
            if s.get("status") == "FINISHED":
                return
            if s.get("status") in ("ERROR", "EXPIRED"):
                raise Fail(f"Threads: контейнер {cid}: {s}")
            time.sleep(5)
        raise Fail(f"Threads: контейнер {cid} не готов за 5 минут")

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = prepare(P.short(p, "threads"), site_link)
        if dry:
            return Result(url="", note=f"готово к отправке: {len(text)} зн., медиа {len(p.media)}")
        urls = self._media_urls(p)
        with httpx.Client(timeout=120) as c:
            tok = self._token(c)

            def item(u, **extra):
                kind = "VIDEO" if u.lower().endswith((".mp4", ".mov")) else "IMAGE"
                key = "video_url" if kind == "VIDEO" else "image_url"
                return c.post(f"{API}/me/threads", data={"media_type": kind, key: u, "access_token": tok, **extra}).json()["id"]
            if not urls:
                cid = c.post(f"{API}/me/threads", data={"media_type": "TEXT", "text": text, "access_token": tok}).json()["id"]
            elif len(urls) == 1:
                cid = item(urls[0], text=text)
            else:
                kids = [item(u, is_carousel_item="true") for u in urls[:20]]
                for k in kids:
                    self._wait(c, k, tok)
                cid = c.post(f"{API}/me/threads", data={"media_type": "CAROUSEL", "children": ",".join(kids),
                                                         "text": text, "access_token": tok}).json()["id"]
            self._wait(c, cid, tok)
            self.sending()
            pid = c.post(f"{API}/me/threads_publish", data={"creation_id": cid, "access_token": tok}).json()["id"]
            link = c.get(f"{API}/{pid}", params={"fields": "permalink", "access_token": tok}).json().get("permalink")
        return Result(url=link or pid)
