"""Стиль автора: корпус публичного канала Telegram и разбор правок по предложениям.

Движок даёт только данные. Правила в STYLE.md выводит Claude по SKILL.md.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import pathlib
import re
from html.parser import HTMLParser

from rk import config
from rk.cli import register

LIST_LINE = re.compile(r"^\s*(?:[—–\-•●▪◦⚬○■□▫►▸▶➤✓✔✅☑*]\ufe0f?|\d{1,2}[.)])\s+\S")
SENT_END = re.compile(r"(?<=[.!?…])\s+(?=\S)")


class _Feed(HTMLParser):
    """Разбор t.me/s/<канал>: текст поста, дата и отметки разметки (жирный, ссылки)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self.cur: dict | None = None
        self.depth = 0          # вложенность div внутри текущего поста
        self.text_depth = None  # уровень div с текстом поста
        self.reply_depth = None # цитата ответа — не текст поста
        self.emoji = 0          # <i class="emoji"><b>…</b></i> — не жирный

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and a.get("data-post"):
            pid = a["data-post"].rsplit("/", 1)[-1]
            self.cur = {"id": int(pid) if pid.isdigit() else pid, "date": "", "parts": [], "marks": "", "text": False}
            self.posts.append(self.cur)
            self.depth, self.text_depth, self.reply_depth = 1, None, None
            return
        if self.cur is None:
            return
        if tag == "div":
            self.depth += 1
            if "message_reply" in cls and self.reply_depth is None:
                self.reply_depth = self.depth
            elif ("tgme_widget_message_text" in cls and self.text_depth is None and self.reply_depth is None
                  and not self.cur["text"]):
                self.text_depth = self.depth
                self.cur["text"] = True
        elif tag == "a" and "message_reply" in cls and self.reply_depth is None:
            self.reply_depth = -1  # ответ оформлен ссылкой-блоком
        elif tag == "time" and not self.cur["date"] and a.get("datetime"):
            self.cur["date"] = a["datetime"]
        if self.text_depth is None:
            return
        if tag == "br":
            self.cur["parts"].append("\n")
        elif tag == "i" and "emoji" in cls:
            self.emoji += 1
        elif tag in ("b", "strong") and not self.emoji:
            self.cur["marks"] += "<b>"
        elif tag == "a":
            self.cur["marks"] += "<a>"

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == "i" and self.emoji:
            self.emoji -= 1
        elif tag == "a" and self.reply_depth == -1:
            self.reply_depth = None
        elif tag == "div":
            if self.text_depth == self.depth:
                self.text_depth = None
            if self.reply_depth == self.depth:
                self.reply_depth = None
            self.depth -= 1
            if self.depth == 0:
                self.cur = None

    def handle_data(self, data):
        if self.cur is not None and self.text_depth is not None:
            self.cur["parts"].append(data)


def _parse(html: str) -> tuple[list[dict], dict]:
    f = _Feed()
    f.feed(html)
    posts, marks = [], {}
    for p in f.posts:
        text = re.sub(r"\n{3,}", "\n\n", "".join(p["parts"])).strip()
        if not text:
            continue
        posts.append({"id": p["id"], "date": p["date"], "text": text})
        marks[p["id"]] = p["marks"]
    return posts, marks


def parse_feed(html: str) -> list[dict]:
    """Посты ленты t.me/s: [{id, date, text}] — посты без текста (только медиа) пропускаются."""
    return _parse(html)[0]


def _channel(name: str) -> str:
    name = name.strip().rstrip("/")
    name = re.sub(r"^(https?://)?(t\.me|telegram\.me)/(s/)?", "", name)
    return name.lstrip("@")


def fetch_channel(channel: str, limit: int = 150) -> list[dict]:
    """Скачивает последние посты публичного канала и пишет корпус в home()/corpus.json."""
    import httpx

    ch = _channel(channel)
    got: dict = {}
    marks: dict = {}
    before = None
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 rk-style"}) as c:
        while len(got) < limit:
            r = c.get(f"https://t.me/s/{ch}", params={"before": before} if before else None)
            r.raise_for_status()
            posts, m = _parse(r.text)
            fresh = [p for p in posts if p["id"] not in got]
            if not fresh:
                break
            for p in fresh:
                got[p["id"]] = p
            marks.update(m)
            ids = [p["id"] for p in posts if isinstance(p["id"], int)]
            if not ids or (before is not None and min(ids) >= before):
                break
            before = min(ids)
    posts = sorted(got.values(), key=lambda p: p["id"] if isinstance(p["id"], int) else 0, reverse=True)[:limit]
    out = {"channel": ch, "fetched": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "posts": posts, "marks": {str(p["id"]): marks.get(p["id"], "") for p in posts}}
    path = config.home() / "corpus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return posts


def summary(posts: list[dict], html: dict | None = None) -> dict:
    """Сводка корпуса: средняя длина, доли постов со списками, жирным, ссылками, до 5 образцов."""
    html = html or {}
    n = len(posts) or 1

    def share(pred) -> float:
        return round(sum(1 for p in posts if pred(p)) / n, 2)

    step = max(1, len(posts) // 5)
    return {
        "posts": len(posts),
        "avg_len": round(sum(len(p["text"]) for p in posts) / n),
        "lists": share(lambda p: sum(1 for l in p["text"].split("\n") if LIST_LINE.match(l)) >= 2),
        "bold": share(lambda p: "<b" in str(html.get(p["id"], html.get(str(p["id"]), "")))),
        "links": share(lambda p: "<a" in str(html.get(p["id"], html.get(str(p["id"]), ""))) or "http" in p["text"]),
        "samples": [p["text"] for p in posts[::step][:5]],
    }


def sents(text: str) -> list[str]:
    """Предложения по абзацам: заголовок и каждая строка абзаца — отдельно."""
    out = []
    for para in re.split(r"\n\s*\n", text or ""):
        for line in para.split("\n"):
            out += [s.strip() for s in SENT_END.split(line) if s.strip()]
    return out


def _docs(d: pathlib.Path) -> dict:
    res = {}
    for f in sorted(pathlib.Path(d).rglob("*.json")):
        if f.name.startswith("_"):
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        doc = doc.get("data", doc) if isinstance(doc, dict) else {}
        res[doc.get("slug") or f.stem] = doc
    return res


FIELDS = (("body", "Пост"), ("threads", "Threads"), ("x", "X"))


def diff(before_dir, pull_dir) -> str:
    """Markdown «− было / + стало» по предложениям для каждой правленой новости, по авторам правок."""
    before, after = _docs(pathlib.Path(before_dir)), _docs(pathlib.Path(pull_dir))
    groups: dict[str, list[str]] = {}
    for slug, a in after.items():
        b = before.get(slug)
        if not b:
            continue
        block = []
        for key, label in FIELDS:
            old, new = (b.get(key) or "").strip(), (a.get(key) or "").strip()
            if old == new:
                continue
            so, sn = sents(old), sents(new)
            lines = []
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=so, b=sn, autojunk=False).get_opcodes():
                if op != "equal":
                    lines += [f"− {s}" for s in so[i1:i2]] + [f"+ {s}" for s in sn[j1:j2]]
            if lines:
                block += [f"{label}:", *lines, ""]
        if block:
            who = a.get("editedBy") or a.get("updatedBy") or "автор"
            title = (a.get("title") or (a.get("body") or "").split("\n")[0] or slug).strip()
            groups.setdefault(str(who), []).append(f"### {title}\n`{slug}`\n\n" + "\n".join(block))
    if not groups:
        return "# Правки автора\n\nВ этом пакете правок нет — тексты совпали с черновиками.\n"
    md = ["# Правки автора", "",
          "Кто правил — id из Редакции; имя можно узнать через ArtifactData profiles.", ""]
    for who, items in groups.items():
        md += [f"## {who}", "", *items]
    return "\n".join(md).rstrip() + "\n"


def _init_setup(ap):
    ap.add_argument("channel", help="@канал или ссылка t.me")
    ap.add_argument("--limit", type=int, default=150)


@register("style-init", _init_setup)
def _init_cmd(a) -> int:
    posts = fetch_channel(a.channel, a.limit)
    corpus = json.loads((config.home() / "corpus.json").read_text(encoding="utf-8"))
    s = summary(posts, corpus.get("marks"))
    print(f"Постов: {s['posts']}, средняя длина: {s['avg_len']} знаков")
    print(f"Списки: {s['lists']:.0%}, жирный: {s['bold']:.0%}, ссылки: {s['links']:.0%}")
    print(f"Корпус: {config.home() / 'corpus.json'}")
    for i, t in enumerate(s["samples"], 1):
        print(f"\n--- образец {i} ---\n{t[:600]}")
    return 0 if posts else 1


@register("style-diff", lambda ap: ap.add_argument("batch"))
def _diff_cmd(a) -> int:
    bdir = config.home() / "batches" / a.batch
    before = bdir / "before" if (bdir / "before").exists() else bdir / "docs"
    if not (bdir / "pull").exists():
        print(f"Нет {bdir / 'pull'}: сначала выгрузите правки из Редакции (ArtifactData list с out_dir)")
        return 1
    out = diff(before, bdir / "pull")
    (bdir / "edits.md").write_text(out, encoding="utf-8")
    print(bdir / "edits.md")
    return 0
