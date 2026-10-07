"""Мастер настройки (rk setup), вход на площадки (rk login), проверка входа (rk check) и новости (rk check-post)."""
from __future__ import annotations

import argparse
import dataclasses
import html as _html
import os
import pathlib
import re
import sys

import yaml

from rk import config, connectors, media, publish, render
from rk import post as P
from rk.cli import register

PLATFORMS = {
    "tg": ("Telegram-канал", {"mode": "web", "channel": "@my_channel", "title_check": "Название канала",
                              "premium": False}),
    "max": ("MAX-канал (через бота MAX)", {"channel_id": 0, "token_file": "max_token"}),
    "vk": ("Сообщество VK (стена)", {"mode": "api", "group_id": 0, "app_id": 0,
                                    "group_token_file": "vk_group_token", "user_token_file": "vk_user_token"}),
    "vkch": ("VK-канал в мессенджере", {"url": "https://vk.com/im/channels/-0"}),
    "fb": ("Страница Facebook (Graph API)", {"mode": "api", "page_id": 0, "token_file": "fb_page_token"}),
    "threads": ("Threads", {"mode": "web", "profile": "@my_profile"}),
    "x": ("X (Twitter)", {"profile": "@my_profile"}),
    "yt": ("YouTube: посты сообщества", {"channel": "@my_channel"}),
    "dzen": ("Дзен (импорт из Telegram или вручную)", {"mode": "tg_import", "channel": "my_channel"}),
    "site": ("Свой сайт (API или WordPress)", {"mode": "api", "url": "https://example.ru/api/news", "key_file": "site_key"}),
}
# что спрашивать у человека по каждой площадке — остальное берётся по умолчанию
ASK = {"tg": [("channel", "Адрес канала, например @my_channel"), ("title_check", "Часть названия канала (для проверки)"),
              ("premium", "Есть ли Telegram Premium у аккаунта, с которого публикуете (да/нет)")],
       "max": [("channel_id", "id канала MAX (число, бот подскажет после входа)")],
       "vk": [("group_id", "id сообщества VK (число)")],
       "vkch": [("url", "Ссылка на VK-канал (vk.com/im/channels/…)")],
       "fb": [("page_id", "ID страницы Facebook (страница → «Информация» → ID страницы)")],
       "threads": [("profile", "Профиль Threads, например @name")],
       "x": [("profile", "Профиль X, например @name")],
       "yt": [("channel", "Канал YouTube, например @name")],
       "dzen": [("channel", "Канал Дзена (имя из адреса dzen.ru/…)")],
       "site": [("url", "Адрес API сайта, например https://example.ru/api/news")]}
CHAT_PLATFORMS = ("tg", "max", "vk", "fb")


# поля, где ждём число, да/нет или список; всё остальное — строка как есть («Иван: фото», «2024», «Yes»)
TYPED = {"page_id", "group_id", "channel_id", "app_id", "premium", "category_ids", "defaults", "publish_order",
         "reverse_order"}
YES = {"да", "д", "yes", "y", "true", "1", "есть"}


def _value(v: str, field: str = ""):
    if field not in TYPED:
        return v
    if field == "premium":
        return str(v).strip().lower() in YES
    try:
        return yaml.safe_load(v)
    except yaml.YAMLError:
        return v


def _apply_set(cfg: dict, item: str) -> None:
    if "=" not in item:
        raise SystemExit(f"--set ждёт путь=значение, получено: {item}")
    path, v = item.split("=", 1)
    keys = path.strip().split(".")
    root = cfg if keys[0] in ("author", "closing", "defaults", "language", "editor_url") else cfg["platforms"]
    if root is cfg["platforms"] and keys[0] not in cfg["platforms"]:
        raise SystemExit(f"--set {path}: площадка {keys[0]} не выбрана (--platforms)")
    cur = root
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = _value(v, keys[-1])


def _ask(prompt: str, default=None) -> str:
    tail = f" [{default}]" if default not in (None, "") else ""
    try:
        got = input(f"{prompt}{tail}: ").strip()
    except EOFError:
        got = ""
    return got or ("" if default is None else str(default))


def _setup_setup(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--yes", action="store_true", help="не задавать вопросов")
    ap.add_argument("--force", action="store_true", help="перезаписать существующий config.yaml")
    ap.add_argument("--platforms", help="площадки через запятую: " + ",".join(config.KNOWN))
    ap.add_argument("--author", default=None)
    ap.add_argument("--set", action="append", default=[], metavar="ПУТЬ=ЗНАЧЕНИЕ",
                    help="поле настроек, например tg.channel=@my_channel или closing.chat.tg=https://t.me/…")


@register("setup", _setup_setup)
def _setup_cmd(a) -> int:
    home = config.home()
    path = home / "config.yaml"
    if path.exists() and not a.force:
        print(f"{path} уже есть — не трогаю. Перезаписать: rk setup --force")
        return 1
    if a.platforms:
        plats = [x.strip() for x in a.platforms.split(",") if x.strip()]
    elif a.yes:
        plats = ["tg"]
    else:
        print("Площадки:")
        for k in config.KNOWN:
            print(f"  {k:8} — {PLATFORMS[k][0]}")
        plats = [x.strip() for x in _ask("Куда публиковать (через запятую)", "tg,vk,max").split(",") if x.strip()]
    bad = [k for k in plats if k not in config.KNOWN]
    if bad or not plats:
        print(f"неизвестная площадка: {', '.join(bad) or '—'} (есть: {', '.join(config.KNOWN)})")
        return 1
    author = a.author if a.author is not None else ("" if a.yes else _ask("Имя автора (подпись в навыке)"))
    cfg = {"author": author, "language": "ru", "editor_url": "",
           "publish_order": [k for k in config.ORDER if k in plats], "defaults": list(plats),
           "reverse_order": ["vkch"] if "vkch" in plats else [],
           "platforms": {k: dict(PLATFORMS[k][1]) for k in plats},
           "closing": {"text": "", "chat": {}}}
    if not a.yes:
        for k in plats:
            for field, prompt in ASK.get(k, []):
                default = ("да" if cfg["platforms"][k][field] else "нет") if field == "premium" else cfg["platforms"][k][field]
                cfg["platforms"][k][field] = _value(_ask(f"{PLATFORMS[k][0]}: {prompt}", default), field)
        for k in [k for k in CHAT_PLATFORMS if k in plats]:
            link = _ask(f"Ссылка на ваш чат для {k} (Enter — без чата)")
            if link:
                cfg["closing"]["chat"][k] = link
        if cfg["closing"]["chat"]:
            cfg["closing"]["text"] = _ask("Финал каждой новости", "Обсудить новость — в [нашем чате]({{CHAT}}).")
    for item in a.set:
        _apply_set(cfg, item)
    if path.exists():  # --force: старый config — в .bak, адрес «Редакции» не теряем
        old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        path.with_name("config.yaml.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        if old.get("editor_url") and not cfg["editor_url"]:
            cfg["editor_url"] = old["editor_url"]
    for d in (home, home / "posts", home / "batches"):
        d.mkdir(parents=True, exist_ok=True)
    sec = config.secrets_dir()
    sec.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(sec, 0o700)
    head = ("# Настройки навыка «Редакция». Токенов здесь нет — только имена файлов с ними в "
            f"{sec}.\n# Править можно руками; проверка: rk check\n")
    path.write_text(head + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=None),
                    encoding="utf-8")
    print(f"Готово: {path}")
    print("Дальше:")
    for k in plats:
        print(f"  rk login {k:8} — вход: {PLATFORMS[k][0]}")
    print("  rk check          — проверить все входы")
    print("  «Редакцию» (окно правки) опубликует Claude: скажите ему «опубликуй редакцию».")
    return 0


@register("login", lambda ap: ap.add_argument("platform", choices=config.KNOWN))
def _login_cmd(a) -> int:
    cfg = config.load()
    if a.platform not in cfg.platforms:
        print(f"{a.platform} не включена в {cfg.path} — добавьте её: rk setup --force или руками в platforms")
        return 1
    connectors.make(cfg, a.platform).login()
    return 0


def placeholders(k: str, opts: dict) -> list[str]:
    """Поля, где остались образцы из мастера (@my_channel, 0, «Название канала»…)."""
    defaults = PLATFORMS.get(k, ("", {}))[1]
    return [f"platforms.{k}.{f}" for f, _ in ASK.get(k, []) if f != "premium"
            and (opts.get(f) in (None, "", 0) or opts.get(f) == defaults.get(f))]


@register("check", lambda ap: ap.add_argument("platforms", nargs="*"))
def _check_cmd(a) -> int:
    cfg = config.load()
    rc, probes = 0, []
    for k in a.platforms or cfg.enabled:
        if k not in cfg.platforms:
            print(f"✗ {k}: не включена в config.yaml")
            rc = 1
            continue
        stub = placeholders(k, cfg.platforms.get(k) or {})
        if stub:
            print(f"✗ {k}: не заполнено: {', '.join(stub)} — rk setup --force --set … или правка {cfg.path}", flush=True)
            rc = 1
            continue
        try:
            conn = connectors.make(cfg, k)
            msg = conn.check()
        except Exception as e:  # noqa: BLE001
            print(f"✗ {k}: {str(e).splitlines()[0] if str(e) else e.__class__.__name__} — rk login {k}", flush=True)
            rc = 1
            continue
        probe = conn.login_probe() if getattr(conn, "uses_browser", False) and hasattr(conn, "login_probe") else None
        if probe:
            probes.append((k, probe))
        else:
            print(f"✓ {k}: {msg}", flush=True)
    if probes:  # вход в браузерные площадки: открыть страницу публикации и дождаться поля ввода
        from rk import browser
        try:
            with browser.session() as ctx:
                for k, (url, sel) in probes:
                    page = browser.new_page(ctx)
                    try:
                        page.goto(url, wait_until="domcontentloaded")
                        page.locator(sel).first.wait_for(state="attached", timeout=30000)
                        print(f"✓ {k}: вход есть", flush=True)
                    except Exception:  # noqa: BLE001
                        print(f"✗ {k}: нет входа или страница изменилась — rk login {k}", flush=True)
                        rc = 1
                    finally:
                        page.close()
        except Exception as e:  # noqa: BLE001
            print(f"✗ браузер: {str(e).splitlines()[0] if str(e) else e.__class__.__name__}", flush=True)
            rc = 1
    return rc


# ------------------------------------------------------------------ проверка новости перед выкладкой

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"


def check_url(url: str, client) -> tuple[bool, str]:
    try:
        r = client.get(url, headers={"User-Agent": UA})
        if "t.me/" in url and r.status_code == 200:
            ok = "tgme_page_title" in r.text or "tgme_channel_info" in r.text
            t = re.search(r'og:title" content="([^"]*)', r.text)
            return ok, (f'HTTP 200, «{_html.unescape(t.group(1)) if t else "?"}»' if ok else "t.me: такого чата или канала нет")
        if r.status_code in (401, 403, 429):
            return True, f"HTTP {r.status_code} — сайт не пускает роботов, живость не доказана"
        return r.status_code < 400, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, f"ошибка: {e.__class__.__name__}: {e}"


def targets_of(p, cfg) -> list[str]:
    t = p.targets if p.targets is not None else cfg.defaults
    return [k for k in t if k in cfg.platforms]


def check_post(p, cfg, client=None) -> tuple[list[str], list[str]]:
    """(проблемы, заметки). Проблемы — то, что сорвёт выкладку; заметки — к сведению."""
    probs, notes = [], []
    targets = targets_of(p, cfg)
    if not targets:
        notes.append("площадки не выбраны — новость никуда не уйдёт")
    view = dataclasses.replace(cfg, platforms={k: v for k, v in cfg.platforms.items() if k in targets})
    probs += [f"длина: {x}" for x in render.check_limits(p, view)]
    if "{{CHAT}}" in p.body:
        probs += [f"в тексте {{{{CHAT}}}}, а в config нет closing.chat.{k}" for k in CHAT_PLATFORMS
                  if k in targets and not cfg.chat_link(k)]
    for m in p.media:
        if not pathlib.Path(m).exists():
            probs.append(f"нет файла альбома: {pathlib.Path(m).name}")
        elif str(m).lower().endswith(media.VIDEO):
            try:
                if not media.has_audio(pathlib.Path(m)):
                    notes.append(f"{pathlib.Path(m).name}: без звука — при выкладке добавится тихая дорожка")
            except media.MediaError as e:
                probs.append(str(e))
    for name in ("threads", "x"):
        if name in targets and not (p.dir / f"{name}.txt").exists():
            probs.append(f"нет короткой версии {name}.txt")
    if client is not None:
        urls = [_html.unescape(u) for u in re.findall(r'href="([^"]+)"', render.html(p.body, cfg.chat_link("tg")))]
        urls += [cfg.chat_link(k) for k in CHAT_PLATFORMS if k in targets and cfg.chat_link(k)]
        for u in dict.fromkeys(x for x in urls if x.startswith("http")):
            ok, why = check_url(u, client)
            (notes if ok else probs).append(f"{'ссылка' if ok else 'битая ссылка'} {u}: {why}")
    return probs, notes


def _check_post_setup(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("what", help="slug новости или имя пакета")
    ap.add_argument("--offline", action="store_true", help="без проверки ссылок")


@register("check-post", _check_post_setup)
def _check_post_cmd(a) -> int:
    cfg = config.load()
    batch_order = config.home() / "batches" / a.what / "order.txt"
    slugs = publish.order_of(a.what) if batch_order.exists() else [a.what]
    client = None
    if not a.offline:
        import httpx
        client = httpx.Client(timeout=20, follow_redirects=True)
    bad = 0
    for slug in slugs:
        d = P.posts_dir() / slug
        if not (d / "post.md").exists():
            print(f"✗ {slug}: нет {d / 'post.md'}")
            bad += 1
            continue
        probs, notes = check_post(P.load(d), cfg, client)
        print(f"{'✗' if probs else '✓'} {slug}")
        for x in probs:
            print(f"    ✗ {x}")
        for x in notes:
            print(f"    · {x}")
        bad += bool(probs)
    print("ИТОГ: всё в порядке" if not bad else f"ИТОГ: проблемы в {bad} из {len(slugs)}")
    sys.stdout.flush()
    return 1 if bad else 0
