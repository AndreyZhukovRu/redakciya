"""Поддельная страница Playwright: записывает клики, нажатия и вызовы evaluate, отвечает заданными значениями."""
from __future__ import annotations

import contextlib


class Loc:
    def __init__(self, page: "FakePage", sel: str):
        self.page, self.sel = page, sel
        self.first = self

    def count(self) -> int:
        return self.page.counts.get(self.sel, 0)

    def locator(self, sub: str) -> "Loc":
        return Loc(self.page, f"{self.sel} {sub}")

    def inner_text(self, timeout=None) -> str:
        v = self.page.texts.get(self.sel, "")
        return v() if callable(v) else v

    def click(self, **kw) -> None:
        self.page.log.append(("click", self.sel))

    def scroll_into_view_if_needed(self) -> None:
        pass

    def wait_for(self, **kw) -> None:
        if not self.count():
            raise TimeoutError(self.sel)


class Keyboard:
    def __init__(self, page: "FakePage"):
        self.page = page

    def press(self, key: str) -> None:
        self.page.log.append(("key", key))


class FakePage:
    def __init__(self, counts=None, texts=None, evaluate=None):
        self.counts, self.texts, self.log = dict(counts or {}), dict(texts or {}), []
        self._eval = evaluate or (lambda js, arg: None)
        self.keyboard = Keyboard(self)

    def goto(self, url, **kw) -> None:
        self.log.append(("goto", url))

    def wait_for_timeout(self, ms) -> None:
        pass

    def locator(self, sel: str) -> Loc:
        return Loc(self, sel)

    def evaluate(self, js: str, arg=None):
        self.log.append(("eval", js, arg))
        return self._eval(js, arg)

    @contextlib.contextmanager
    def expect_file_chooser(self, timeout=None):
        class FC:
            class value:
                @staticmethod
                def set_files(files):
                    self.log.append(("files", files))
        yield FC

    def pasted(self) -> bool:
        return any(e[0] == "eval" and "ClipboardEvent" in e[1] for e in self.log)

    def clicked(self, part: str) -> bool:
        return any(e[0] == "click" and part in e[1] for e in self.log)
