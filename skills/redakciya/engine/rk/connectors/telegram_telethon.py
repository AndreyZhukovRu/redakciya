"""Telegram аккаунтом через Telethon (нужны api_id/api_hash с my.telegram.org). Жирный сохраняется, подпись до 4096."""
from __future__ import annotations

import asyncio
import json

from rk import config, render
from rk.connectors.base import Connector, Fail, Result
from rk.connectors.telegram_web import media_of


def entity_problem(ent, title_check: str) -> str | None:
    """Почему в этот чат публиковать нельзя (None — можно). Аккаунт умеет писать и в группы, и в личку."""
    if not getattr(ent, "broadcast", False):
        return f"«{getattr(ent, 'title', None) or getattr(ent, 'first_name', '?')}» — не канал (группа или человек)"
    if title_check.lower() not in (getattr(ent, "title", "") or "").lower():
        return f"не тот канал: «{ent.title}», а в config title_check «{title_check}»"
    return None


class TelegramTelethon(Connector):
    key = "tg"

    def _api(self) -> dict:
        return json.loads(self.cfg.secret(self.opts.get("api_file", "tg_api.json")))

    def _session(self) -> str:
        return str(config.secrets_dir() / self.opts.get("session", "tg_session"))

    def login(self) -> None:
        from telethon.sync import TelegramClient
        api = self._api()
        with TelegramClient(self._session(), api["api_id"], api["api_hash"]) as cl:
            print(f"вход выполнен: {cl.get_me().first_name}")

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        text = render.html(p.body, self.cfg.chat_link("tg"))
        if dry:
            return Result(url="", note=f"готово к отправке: {render.visible_len(text, True)} зн., медиа {len(p.media)}")
        try:
            from telethon import TelegramClient
        except ImportError:
            raise Fail("не установлен telethon — pip install 'rk[telethon]' или mode: web") from None
        title_check = self.opts.get("title_check")
        if not title_check:
            raise Fail("в config не задан platforms.tg.title_check — часть названия канала для проверки")
        api, ch, files = self._api(), self.opts.get("channel", ""), [str(f) for f in media_of(p)]

        async def go():
            async with TelegramClient(self._session(), api["api_id"], api["api_hash"]) as cl:
                ent = await cl.get_entity(ch)
                why = entity_problem(ent, title_check)
                if why:
                    raise Fail(f"{why} — ничего не отправлено")
                self.sending()
                if files:
                    msg = await cl.send_file(ent, files if len(files) > 1 else files[0], caption=text,
                                             parse_mode="html", supports_streaming=True)
                    msg = msg[0] if isinstance(msg, list) else msg
                else:
                    msg = await cl.send_message(ent, text, parse_mode="html", link_preview=False)
                return msg.id
        return Result(url=f"https://t.me/{ch.lstrip('@')}/{asyncio.run(go())}")
