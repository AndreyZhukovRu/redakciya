"""Сайт на WordPress: REST API и пароль приложения (Пользователи → Профиль → Пароли приложений).
Файлы — в медиатеку, первый — обложка (featured_media), остальные — галерея в конце записи. Повтор по slug — без дубля.
"""
from __future__ import annotations

import mimetypes
import urllib.parse

import httpx

from rk.connectors.base import Connector, Fail, Result
from rk.connectors.site_api import body_html
from rk.connectors.telegram_web import media_of


def gallery_block(items: list[tuple[int, str]]) -> str:
    figs = "".join(f'<!-- wp:image {{"id":{i}}} --><figure class="wp-block-image"><img src="{u}" class="wp-image-{i}"/>'
                   f"</figure><!-- /wp:image -->" for i, u in items)
    return f'<!-- wp:gallery {{"linkTo":"none"}} --><figure class="wp-block-gallery has-nested-images">{figs}</figure><!-- /wp:gallery -->'


class SiteWordpress(Connector):
    key = "site"

    def _base(self) -> str:
        u = (self.opts.get("url") or "").rstrip("/")
        if not u:
            raise Fail("в config не задан platforms.site.url (корень сайта WordPress)")
        return u

    def _auth(self) -> tuple[str, str]:
        user = self.opts.get("user")
        if not user:
            raise Fail("в config не задан platforms.site.user (логин WordPress)")
        return user, self.cfg.secret(self.opts.get("app_password_file", "wp_app_password")).replace(" ", "")

    def check(self) -> str:
        r = httpx.get(f"{self._base()}/wp-json/wp/v2/users/me", auth=self._auth(), timeout=30)
        if r.status_code != 200:
            raise Fail(f"WordPress не пустил: {r.status_code} — проверьте логин и пароль приложения")
        return f"WordPress: вход как «{r.json().get('name')}»"

    def _existing(self, c: httpx.Client, auth, slug: str) -> str | None:
        r = c.get("/wp-json/wp/v2/posts", params={"slug": slug, "status": "publish,draft,future"}, auth=auth)
        items = r.json() if r.status_code == 200 else []
        return items[0]["link"] if items else None

    def _media(self, c: httpx.Client, auth, files) -> list[tuple[int, str]]:
        out = []
        for f in files:
            with open(f, "rb") as fh:
                r = c.post("/wp-json/wp/v2/media", auth=auth, content=fh.read(), headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(f.name)}",
                    "Content-Type": mimetypes.guess_type(str(f))[0] or "application/octet-stream"})
            if r.status_code not in (200, 201):
                raise Fail(f"WordPress не принял {f.name}: {r.status_code} {r.text[:200]}")
            d = r.json()
            out.append((d["id"], d["source_url"]))
        return out

    def upload_media(self, files) -> list[str]:
        with httpx.Client(base_url=self._base(), timeout=300) as c:
            return [u for _, u in self._media(c, self._auth(), files)]

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        files = media_of(p)
        if dry:
            return Result(url="", note=f"готово к отправке: «{p.title[:50]}», медиа {len(files)}")
        auth = self._auth()
        with httpx.Client(base_url=self._base(), timeout=600) as c:
            if (old := self._existing(c, auth, p.slug)):
                return Result(url=old, note="запись с таким slug уже была — не дублирую")
            items = self._media(c, auth, files)
            content = body_html(p, self.cfg.chat_link("site") or self.cfg.chat_link("tg"))
            if len(items) > 1:
                content += gallery_block(items[1:])
            data = {"title": p.title, "content": content, "slug": p.slug, "status": self.opts.get("status", "publish"),
                    "categories": p.meta.get("cats") or self.opts.get("category_ids") or []}
            if items:
                data["featured_media"] = items[0][0]
            r = c.post("/wp-json/wp/v2/posts", auth=auth, json=data)
            if r.status_code not in (200, 201):
                raise Fail(f"WordPress: {r.status_code} {r.text[:200]}")
            return Result(url=r.json()["link"])
