"""Контракт площадки. Оркестратор (rk.publish) знает только эти методы."""
from __future__ import annotations

from dataclasses import dataclass

from rk.journal import AFTER_CLICK  # noqa: F401  (реэкспорт для площадок)


class Fail(RuntimeError):
    pass


@dataclass
class Result:
    url: str
    note: str | None = None


class Connector:
    key = ""
    needs_site_link = False    # в тексте нужна ссылка на запись сайта (или пост Telegram)
    uses_browser = False       # работает через профиль Chrome публикатора
    retry_safe = True          # можно ли сразу повторить после Fail (до нажатия «опубликовать»)
    login_urls: list[str] = []

    def __init__(self, cfg, opts: dict):
        self.cfg, self.opts = cfg, opts
        self.on_send = None
        if not self.key:
            self.key = opts.get("key", "")

    def sending(self) -> None:
        """Вызывать прямо перед необратимым действием (клик «Опубликовать», запрос публикации).
        Оркестратор пишет в журнал «отправка начата»: упади что-то дальше — повторный запуск сюда не пойдёт."""
        if self.on_send:
            self.on_send()

    def login(self) -> None:
        if self.login_urls:
            from rk import browser
            browser.open_login(self.login_urls)
            print("Войдите в открывшемся окне браузера и закройте его (Mac: Cmd+Q; Windows: крестиком окна), потом скажите об этом Claude.")

    def check(self) -> str:
        return "настроено"

    def login_probe(self) -> tuple[str, str] | None:
        """Для браузерных площадок: (адрес, селектор), который виден только после входа. rk check ждёт его."""
        return None

    def publish(self, p, dry: bool, page=None, site_link: str = "") -> Result:
        raise NotImplementedError
