"""Страница Facebook по Graph API: альбом фото (загрузка без публикации → один пост в ленте) или одно видео.

Токен страницы, полученный из долгоживущего токена пользователя, не истекает — вход нужен один раз.
Личный профиль API не поддерживает (Meta закрыла это в 2018 году) — только страницы.
"""
from __future__ import annotations

import json

import httpx

from rk import config, media, render
from rk.connectors.base import Connector, Fail, Result

GRAPH = "https://graph.facebook.com"
VIDEO = "https://graph-video.facebook.com"
PHOTO_MAX = 8 * 1024 * 1024

LOGIN_HELP = """Facebook: публиковать можно только на страницу (не в личный профиль). Один раз:
 1. developers.facebook.com → «Мои приложения» → создайте приложение (или откройте то, что для Threads) и добавьте
    сценарий «Управление всем на странице» (Manage everything on your Page).
 2. «Настройки приложения → Основное»: App ID и App Secret — в файл {app}
    одной строкой JSON: {{"app_id": "…", "app_secret": "…"}}
 3. developers.facebook.com/tools/explorer: выберите приложение → «Get User Access Token» → права pages_show_list,
    pages_read_engagement, pages_manage_posts → Generate. Скопируйте токен в файл {user}
 4. Снова: rk login fb — движок обменяет его на бессрочный токен страницы {page_id}."""


def page_token_from_accounts(data: dict, page_id) -> tuple[str, str]:
    for acc in data.get("data") or []:
        if str(acc.get("id")) == str(page_id):
            return acc["access_token"], acc.get("name", "")
    have = ", ".join(f"{a.get('name', '?')} ({a.get('id')})" for a in data.get("data") or []) or "ни одной"
    raise Fail(f"Facebook: у токена нет доступа к странице {page_id}; доступны: {have}")


class FacebookApi(Connector):
    key = "fb"

    def _v(self) -> str:
        return self.opts.get("api_version", "v24.0")

    def _page(self) -> str:
        pid = self.opts.get("page_id")
        if not pid:
            raise Fail("в config не задан platforms.fb.page_id (число из адреса страницы или «Информация → ID»)")
        return str(pid)

    def _token(self) -> str:
        return self.cfg.secret(self.opts.get("token_file", "fb_page_token"))

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=300)

    @staticmethod
    def _ok(r: httpx.Response) -> dict:
        try:
            d = r.json()
        except ValueError:
            raise Fail(f"Facebook: HTTP {r.status_code}, ответ не JSON") from None
        err = d.get("error") if isinstance(d, dict) else None
        if err:
            code, msg = err.get("code"), err.get("message", "")
            if code in (102, 190):
                raise Fail(f"Facebook: токен недействителен ({msg}) — rk login fb")
            if code in (10, 200) or 200 <= (code or 0) < 300:
                raise Fail(f"Facebook: нет прав ({msg}) — нужен pages_manage_posts, rk login fb")
            raise Fail(f"Facebook: {msg} (код {code})")
        return d

    def message(self, p) -> str:
        return render.plain(p.body, self.cfg.chat_link("fb"))

    def login(self) -> None:
        sec = config.secrets_dir()
        app_f, user_f = sec / "fb_app.json", sec / "fb_user_token"
        if not app_f.exists() or not user_f.exists():
            print(LOGIN_HELP.format(app=app_f, user=user_f, page_id=self.opts.get("page_id", "")))
            return
        app = json.loads(app_f.read_text(encoding="utf-8"))
        with self._client() as c:
            long = self._ok(c.get(f"{GRAPH}/{self._v()}/oauth/access_token", params={
                "grant_type": "fb_exchange_token", "client_id": app["app_id"], "client_secret": app["app_secret"],
                "fb_exchange_token": user_f.read_text(encoding="utf-8").strip()}))["access_token"]
            accs = self._ok(c.get(f"{GRAPH}/{self._v()}/me/accounts",
                                  params={"fields": "id,name,access_token", "access_token": long}))
        tok, name = page_token_from_accounts(accs, self._page())
        out = sec / self.opts.get("token_file", "fb_page_token")
        out.write_text(tok, encoding="utf-8")
        print(f"Facebook: бессрочный токен страницы «{name}» сохранён в {out}. Файл {user_f.name} больше не нужен.")

    def check(self) -> str:
        with self._client() as c:
            me = self._ok(c.get(f"{GRAPH}/{self._v()}/me", params={"fields": "id,name", "access_token": self._token()}))
        if str(me.get("id")) != self._page():
            raise Fail(f"токен не от страницы {self._page()}, а от «{me.get('name')}» ({me.get('id')}) — rk login fb")
        return f"страница «{me.get('name')}», токен жив"

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = self.message(p)
        files = [m for m in p.media if m.exists()]
        missing = [m.name for m in p.media if not m.exists()]
        if missing:
            raise Fail(f"нет файлов: {', '.join(missing)}")
        pics, vids = media.photos(files), media.videos(files)
        skipped = "" if not (pics and vids) else f"видео в альбом Facebook не встают — вышли только фото ({len(vids)} видео пропущено)"
        if dry:
            what = f"{len(pics)} фото" if pics else (f"видео {vids[0].name}" if vids else "без медиа")
            return Result(url="", note=f"готово к отправке: {len(text)} зн., {what}" + (f"; {skipped}" if skipped else ""))
        if skipped:
            print(f"  fb: {skipped}", flush=True)
        tok, pid, v = self._token(), self._page(), self._v()
        with self._client() as c:
            if pics:
                ids = []
                for m in pics:
                    src = media.shrink(m, PHOTO_MAX)
                    with open(src, "rb") as f:
                        d = self._ok(c.post(f"{GRAPH}/{v}/{pid}/photos", data={"published": "false", "access_token": tok},
                                            files={"source": (src.name, f)}))
                    ids.append(d["id"])
                form = {"message": text, "access_token": tok}
                form.update({f"attached_media[{i}]": json.dumps({"media_fbid": x}) for i, x in enumerate(ids)})
                self.sending()
                post_id = self._ok(c.post(f"{GRAPH}/{v}/{pid}/feed", data=form))["id"]
            elif vids:
                self.sending()
                with open(vids[0], "rb") as f:
                    d = self._ok(c.post(f"{VIDEO}/{v}/{pid}/videos", data={"description": text, "access_token": tok},
                                        files={"source": (vids[0].name, f)}))
                if len(vids) > 1:
                    print(f"  fb: {len(vids) - 1} видео пропущено — Facebook берёт одно", flush=True)
                return Result(url=f"https://www.facebook.com/{pid}/videos/{d['id']}")
            else:
                self.sending()
                post_id = self._ok(c.post(f"{GRAPH}/{v}/{pid}/feed", data={"message": text, "access_token": tok}))["id"]
        return Result(url=f"https://www.facebook.com/{pid}/posts/{str(post_id).split('_')[-1]}")
