"""VK стена группы по API. Два токена (проверено на практике):
  • ключ сообщества (управление, фото, стена; бессрочный) — wall.post, но не загрузка фото/видео;
  • токен пользователя своего standalone-приложения VK (scope wall,photos,video,groups,docs; живёт 24 часа) —
    загрузка фото и видео. Обновляется сам: rk login vk открывает разрешение в профиле публикатора.
"""
from __future__ import annotations

import re
import urllib.parse

import httpx

from rk import config, media, render
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of

V = "5.199"


def auth_url(app_id: int) -> str:
    if not app_id:
        raise Fail("для VK API нужен app_id своего приложения VK (vk.com/editapp?act=create, тип Standalone) "
                   "— или mode: web без приложения")
    return (f"https://oauth.vk.com/authorize?client_id={app_id}&scope=wall,photos,video,groups,docs"
            "&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token&v=" + V)


def token_from_url(url: str) -> str | None:
    m = re.search(r"access_token=([^&]+)", url)
    return m.group(1) if m else None


class VkApi(Connector):
    key = "vk"

    def _api(self, c: httpx.Client, method: str, tok: str, **params):
        params.update(access_token=tok, v=V)
        d = c.post(f"https://api.vk.com/method/{method}", data=params).json()
        if "error" in d:
            e = d["error"]
            raise Fail(f"VK {method}: [{e.get('error_code')}] {e.get('error_msg')}")
        return d["response"]

    def _gid(self) -> int:
        return abs(int(self.opts["group_id"]))  # из адреса wall-123_45 часто копируют с минусом

    def login(self) -> None:
        """Токен пользователя: открыть разрешение в профиле публикатора и забрать access_token из адреса."""
        from rk import browser
        url = auth_url(int(self.opts.get("app_id") or 0))
        with browser.session() as ctx:
            page = browser.new_page(ctx)
            page.goto(url, wait_until="domcontentloaded")
            print("Если VK спросит — войдите и разрешите доступ в открывшемся окне (до 3 минут).")
            page.wait_for_url(re.compile(r"blank\.html#.*access_token="), timeout=180000)
            tok = token_from_url(page.url)
        f = config.secrets_dir() / self.opts.get("user_token_file", "vk_user_token")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(tok, encoding="utf-8")
        print(f"токен VK сохранён в {f}; ключ сообщества положите в "
              f"{config.secrets_dir() / self.opts.get('group_token_file', 'vk_group_token')}")

    def _tokens(self, c: httpx.Client) -> tuple[str, str]:
        user = self.cfg.secret(self.opts.get("user_token_file", "vk_user_token"))
        group = self.cfg.secret(self.opts.get("group_token_file", "vk_group_token"))
        try:
            self._api(c, "users.get", user)
        except Fail:
            raise Fail("токен пользователя VK истёк (живёт сутки) — выполните: rk login vk") from None
        return user, group

    def check(self) -> str:
        with httpx.Client(timeout=30) as c:
            user, group = self._tokens(c)
            g = self._api(c, "groups.getById", group, group_id=self._gid())
        name = (g.get("groups") or g)[0].get("name") if isinstance(g, (list, dict)) else "?"
        return f"группа «{name}», токены живы"

    def _upload(self, c: httpx.Client, url: str, field: str, path) -> dict:
        with open(path, "rb") as f:
            return c.post(url, files={field: (path.name, f)}, timeout=1800).json()

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = render.plain(p.body, self.cfg.chat_link("vk"))
        files = media_of(p)
        if dry:
            return Result(url="", note=f"готово к отправке: {len(text)} зн., медиа {len(files)}")
        gid, title = self._gid(), p.title
        desc = "\n\n".join(text.split("\n\n")[:2])
        atts = []
        with httpx.Client(timeout=120) as c:
            user, group = self._tokens(c)
            for m in files:
                if str(m).lower().endswith(media.VIDEO):
                    s = self._api(c, "video.save", user, group_id=gid, name=title[:128], description=desc[:5000], wallpost=0)
                    up = self._upload(c, s["upload_url"], "video_file", m)
                    atts.append(f"video-{gid}_{up.get('video_id', s['video_id'])}")
                    continue
                ph = None
                for attempt in range(5):  # VK иногда отдаёт пустой photo — повтор, с 4-й попытки копия 1600 px
                    src = media.shrink(m, 1, 1600) if attempt >= 3 else m
                    try:
                        s = self._api(c, "photos.getWallUploadServer", user, group_id=gid)
                        up = self._upload(c, s["upload_url"], "photo", src)
                        if not up.get("photo") or up.get("photo") == "[]":
                            raise Fail(f"пустой ответ загрузки: {str(up)[:120]}")
                        ph = self._api(c, "photos.saveWallPhoto", user, group_id=gid, photo=up["photo"],
                                       server=up["server"], hash=up["hash"])
                        break
                    except (Fail, ValueError, KeyError) as e:
                        print(f"  vk: {m.name}: попытка {attempt + 1}: {e}")
                if not ph:  # пост без фото — не то, что автор видел в «Редакции»; до wall.post повтор безопасен
                    raise Fail(f"VK не принял фото {m.name} за 5 попыток — пост не опубликован")
                atts.append(f"photo{ph[0]['owner_id']}_{ph[0]['id']}")
            self.sending()
            r = self._api(c, "wall.post", group, owner_id=-gid, from_group=1, message=text, attachments=",".join(atts))
        return Result(url=f"https://vk.com/wall-{gid}_{r['post_id']}")
