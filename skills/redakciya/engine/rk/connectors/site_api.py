"""Сайт: свой приём новостей по ключу (протокол из спецификации §9.1). Пример приёмника — examples/site_api_receiver.php.

POST <url>        Bearer <ключ>, multipart: title, html, excerpt, slug, tags[], categories[], media[] → {"id","url"}
POST <url>/media  Bearer <ключ>, multipart: file → {"url"}       (для Threads API: публичные адреса картинок)
GET  <url>/ping   → 200                                          (проверка ключа и адреса)
Повтор с тем же slug возвращает ту же запись — дублей нет.
"""
from __future__ import annotations

import mimetypes
import re

import httpx

from rk import render
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of


def form_fields(title: str, html: str, slug: str, tags=(), categories=(), excerpt: str = "") -> list[tuple[str, str]]:
    f = [("title", title), ("html", html), ("slug", slug), ("excerpt", excerpt)]
    f += [("tags[]", t) for t in tags] + [("categories[]", c) for c in categories]
    return f


def as_data(pairs: list[tuple[str, str]]) -> dict:
    """httpx принимает повторяющиеся поля формы как словарь со списками."""
    d: dict = {}
    for k, v in pairs:
        d.setdefault(k, []).append(v)
    return {k: (v if k.endswith("[]") else v[0]) for k, v in d.items()}


def body_html(p, chat: str) -> str:
    """Тело записи сайта: текст без первой строки (она — заголовок), абзацы в <p>."""
    rest = p.body.split("\n", 1)[1] if "\n" in p.body else ""
    html = render.html(rest.strip(), chat)
    return "".join(f"<p>{para.replace(chr(10), '<br>')}</p>" for para in re.split(r"\n{2,}", html) if para.strip())


class SiteApi(Connector):
    key = "site"

    def _url(self) -> str:
        u = (self.opts.get("url") or "").rstrip("/")
        if not u:
            raise Fail("в config не задан platforms.site.url")
        return u

    def _key(self) -> str:
        return self.cfg.secret(self.opts.get("key_file", "site_key"))

    def check(self) -> str:
        r = httpx.get(f"{self._url()}/ping", headers={"Authorization": f"Bearer {self._key()}"}, timeout=30)
        if r.status_code != 200:
            raise Fail(f"сайт ответил {r.status_code} на /ping — проверьте адрес и ключ")
        return f"сайт {self._url()} принимает новости"

    def _upload(self, c: httpx.Client, key: str, files) -> list[str]:
        out = []
        for f in files:
            with open(f, "rb") as fh:
                r = c.post(f"{self._url()}/media", headers={"Authorization": f"Bearer {key}"},
                           files={"file": (f.name, fh, mimetypes.guess_type(str(f))[0] or "application/octet-stream")})
            if r.status_code not in (200, 201):
                raise Fail(f"сайт не принял файл {f.name}: {r.status_code} {r.text[:200]}")
            out.append(r.json()["url"])
        return out

    def upload_media(self, files) -> list[str]:
        with httpx.Client(timeout=300) as c:
            return self._upload(c, self._key(), files)

    def _send(self, c: httpx.Client, key: str, fields: dict, files) -> str:
        handles = [("media[]", (f.name, open(f, "rb"), mimetypes.guess_type(str(f))[0] or "application/octet-stream"))
                   for f in files]
        try:
            r = c.post(self._url(), headers={"Authorization": f"Bearer {key}"},
                       data=as_data(form_fields(fields["title"], fields["html"], fields["slug"], fields.get("tags", ()),
                                                fields.get("categories", ()), fields.get("excerpt", ""))),
                       files=handles)
        finally:
            for _, (_, fh, _) in handles:
                fh.close()
        if r.status_code not in (200, 201):
            raise Fail(f"сайт ответил {r.status_code}: {r.text[:200]}")
        return r.json()["url"]

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        fields = {"title": p.title, "html": body_html(p, self.cfg.chat_link("site") or self.cfg.chat_link("tg")),
                  "slug": p.slug, "tags": p.meta.get("tags") or [], "categories": p.meta.get("cats") or [],
                  "excerpt": (p.body.split("\n\n")[1] if p.body.count("\n\n") else "")[:300]}
        files = media_of(p)
        if dry:
            return Result(url="", note=f"готово к отправке: «{p.title[:50]}», медиа {len(files)}")
        with httpx.Client(timeout=600) as c:
            return Result(url=self._send(c, self._key(), fields, files))
