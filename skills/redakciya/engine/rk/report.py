"""rk report <пакет>: где каждая новость вышла и чего не хватает — коротко, чтобы не читать журналы."""
from __future__ import annotations

from rk import config, journal, publish
from rk import post as P
from rk.cli import register


def report(batch: str) -> tuple[list[str], int, int]:
    cfg = config.load()
    order = publish.order_of(batch)
    lines, full, total = [], 0, 0
    for n, slug in enumerate(order, 1):
        d = P.posts_dir() / slug
        if not (d / "post.md").exists():
            lines.append(f"{n:2}. ✗ {slug} — нет post.md")
            total += 1
            continue
        p = P.load(d)
        why = publish.SKIP.get(str(p.meta.get("status") or ""))
        if why:
            lines.append(f"{n:2}. · {slug} — {why}")
            continue
        total += 1
        need = [k for k in cfg.publish_order if k in cfg.platforms
                and k in (p.targets if p.targets is not None else cfg.defaults)]
        log = journal.get(d)
        miss = [k for k in need if k not in log]
        notes = [(k, v["note"]) for k, v in log.items() if isinstance(v, dict) and v.get("note")]
        link = (log.get("site") or log.get("tg") or {}).get("url", "")
        if not miss and not notes:
            full += 1
            lines.append(f"{n:2}. ✓ {slug} {link}".rstrip())
            continue
        lines.append(f"{n:2}. ✗ {slug} {link}".rstrip() + (f" — нет: {', '.join(miss)}" if miss else ""))
        for k, note in notes:
            lines.append(f"      ⚠ {k}: {note}")
    lines.append(f"Итог: {full} из {total} новостей вышли везде, куда отмечены.")
    return lines, full, total


@register("report", lambda ap: ap.add_argument("batch"))
def _cmd(a) -> int:
    lines, full, total = report(a.batch)
    print("\n".join(lines))
    return 0 if full == total else 1
