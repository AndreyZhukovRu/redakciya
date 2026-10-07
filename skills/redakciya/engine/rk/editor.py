"""«Редакция» (артефакт): rk docs — документы для загрузки (ArtifactData batch), rk pull — правки обратно в post.md."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re

import yaml

from rk import config
from rk import post as P
from rk.cli import register

NAMES = {"tg": "Telegram", "max": "MAX", "vk": "VK", "vkch": "VK-канал", "fb": "Facebook", "threads": "Threads", "x": "X",
         "yt": "YouTube", "dzen": "Дзен", "site": "Сайт"}


def media_note(p) -> str:
    vids = sum(1 for m in p.media if str(m).lower().endswith((".mp4", ".mov")))
    photos = len(p.media) - vids
    parts = (["видео" if vids == 1 else f"{vids} видео"] if vids else []) + ([f"{photos} фото"] if photos else [])
    return " + ".join(parts)


def docs(batch: str, assets_file: str | None) -> list[pathlib.Path]:
    cfg = config.load()
    assets = json.loads(pathlib.Path(assets_file).read_text(encoding="utf-8")) if assets_file else {}
    bdir = config.home() / "batches" / batch
    out_dir = bdir / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    slugs = [l.split("\t")[0].strip() for l in (bdir / "order.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for n, slug in enumerate(slugs, 1):
        d = P.posts_dir() / slug
        if not (d / "post.md").exists():
            continue
        p = P.load(d)
        doc = {"slug": slug, "batch": batch, "order": n, "title": p.title, "body": p.body.strip(),
               "threads": P.short(p, "threads"), "x": P.short(p, "x"), "status": "draft",
               "targets": p.targets if p.targets is not None else list(cfg.defaults),
               "mediaNote": media_note(p), "note": "", "createdAt": (now + dt.timedelta(seconds=n)).isoformat(),
               "updatedBy": "claude"}
        if (d / "checks.txt").exists():
            doc["checks"] = (d / "checks.txt").read_text(encoding="utf-8").strip()
        doc.update({k: v for k, v in (assets.get(slug) or {}).items() if k in ("cover", "sheet", "checks")})
        if not p.meta.get("status"):  # пока автор не нажал «Готово», новость не выйдет, даже если правки не стянулись
            _set_meta(d, status="draft")
        f = out_dir / f"{slug}.json"
        f.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(f)
    st = out_dir / "_settings.json"
    tg = cfg.platforms.get("tg") or {}
    album = 4096 if tg.get("premium") is True and tg.get("mode") != "bot" else 1024
    st.write_text(json.dumps({"enabled": cfg.enabled, "defaults": list(cfg.defaults),
                              "names": {k: NAMES[k] for k in cfg.enabled}, "limits": {"tg_album": album}},
                             ensure_ascii=False), encoding="utf-8")
    out.append(st)
    return out


def _set_meta(d: pathlib.Path, **kv) -> None:
    raw = (d / "post.md").read_text(encoding="utf-8")
    m = P.HEAD.match(raw)
    meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
    meta.update(kv)
    head = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=None).strip() + "\n---\n"
    (d / "post.md").write_text(head + (raw[m.end():] if m else raw), encoding="utf-8")


def pull(src: pathlib.Path) -> list[str]:
    lines = []
    for f in sorted(pathlib.Path(src).rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc = doc.get("data", doc)
        slug = doc.get("slug") or f.stem
        d = P.posts_dir() / slug
        if not (d / "post.md").exists():
            continue
        p = P.load(d)
        changed = []
        if doc.get("body") and doc["body"].strip() + "\n" != p.body:
            P.save_body(p, doc["body"])
            changed.append("пост")
        for k in ("threads", "x"):
            if doc.get(k) is not None and P.short(p, k) != doc[k].strip():
                (d / f"{k}.txt").write_text(doc[k].strip() + "\n", encoding="utf-8")
                changed.append(k)
        if isinstance(doc.get("targets"), list) and doc["targets"] != p.targets:
            _set_meta(d, to=doc["targets"])
            changed.append("площадки")
        if doc.get("status") and doc["status"] != p.meta.get("status"):
            _set_meta(d, status=doc["status"])
        note = (doc.get("note") or "").strip()
        lines.append(f"{doc.get('order', '?'):>2}. {slug}: {doc.get('status')}, правил {doc.get('updatedBy')}"
                     + (f", изменено: {', '.join(changed)}" if changed else "") + (f" | ЗАМЕТКА: {note}" if note else ""))
    return lines


def sheets(batch: str) -> list[pathlib.Path]:
    """Обложка (первый кадр альбома, до 1600 px) и контакт-лист каждой новости — для загрузки в «Редакцию»."""
    from PIL import Image

    from rk import media
    from rk import publish

    out = []
    for slug in publish.order_of(batch):
        p = P.load(P.posts_dir() / slug)
        files = [m for m in p.media if pathlib.Path(m).exists()]
        pics = media.photos(files)
        if pics:
            with Image.open(pics[0]) as im:
                im = im.convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(p.dir / "cover.jpg", "JPEG", quality=85)
            out.append(p.dir / "cover.jpg")
        if files:
            out.append(media.sheet(files, p.dir / "sheet.jpg"))
    return out


def _docs_setup(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("batch")
    ap.add_argument("assets", nargs="?")


@register("docs", _docs_setup)
def _docs_cmd(a) -> int:
    for f in docs(a.batch, a.assets):
        print(f)
    return 0


@register("pull", lambda ap: ap.add_argument("dir"))
def _pull_cmd(a) -> int:
    src = pathlib.Path(a.dir)
    got = {}
    for f in src.rglob("*.json") if src.exists() else []:
        if not f.name.startswith("_"):
            doc = json.loads(f.read_text(encoding="utf-8"))
            got[(doc.get("data", doc).get("slug")) or f.stem] = f
    print("\n".join(pull(src)) if got else f"в {src} нет документов «Редакции» — проверьте out_dir выгрузки")
    rc = 0 if got else 1
    batches = config.home() / "batches"
    for up in [src, *src.parents]:  # пакет — папка внутри batches/: сверяем, все ли новости пришли
        if up.parent == batches and (up / "order.txt").exists():
            from rk import publish
            miss = [s for s in publish.order_of(up.name) if s not in got]
            if miss:
                print("нет в выгрузке: " + ", ".join(miss) + " — их статусы и правки не стянуты, они не выйдут")
                rc = 1
            break
    return rc


@register("sheets", lambda ap: ap.add_argument("batch"))
def _sheets_cmd(a) -> int:
    for f in sheets(a.batch):
        print(f)
    return 0
