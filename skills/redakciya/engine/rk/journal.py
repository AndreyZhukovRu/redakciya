"""published.json: что где вышло. Пишется сразу после успеха площадки — повтор без --again не публикует."""
from __future__ import annotations

import json
import os
import pathlib
import time

AFTER_CLICK = "кнопка нажата, но проверка не прошла — сверить вручную, повторно НЕ публиковать"


def _f(d) -> pathlib.Path:
    return pathlib.Path(d) / "published.json"


def get(d) -> dict:
    f = _f(d)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def has(d, key: str) -> bool:
    return key in get(d)


def needs_check(d, key: str) -> bool:
    return AFTER_CLICK in (get(d).get(key) or {}).get("note", "")


def put(d, key: str, url: str, note: str | None = None) -> None:
    data = get(d)
    rec = {"url": url, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if note:
        rec["note"] = note
    data[key] = rec
    tmp = _f(d).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _f(d))
