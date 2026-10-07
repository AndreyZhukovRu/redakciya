"""rk — движок навыка «Редакция». Команды регистрируются модулями через register()."""
from __future__ import annotations

import argparse
from typing import Callable

from rk import __version__

COMMANDS: dict[str, tuple[Callable[[argparse.ArgumentParser], None], Callable[[argparse.Namespace], int]]] = {}


def register(name: str, setup: Callable[[argparse.ArgumentParser], None]):
    def deco(fn: Callable[[argparse.Namespace], int]):
        COMMANDS[name] = (setup, fn)
        return fn
    return deco


def _load_commands() -> None:
    # модули с командами импортируются здесь, чтобы register() сработал
    for mod in ("setup", "publish", "report", "editor", "style", "sources", "connectors.tg_edit"):
        try:
            __import__(f"rk.{mod}")
        except ModuleNotFoundError as e:
            if e.name != f"rk.{mod}":
                raise


def main(argv: list[str]) -> int:
    _load_commands()
    ap = argparse.ArgumentParser(prog="rk", description="Движок навыка «Редакция»")
    ap.add_argument("--version", action="version", version=f"rk {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    for name, (setup, _) in COMMANDS.items():
        setup(sub.add_parser(name))
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    return COMMANDS[a.cmd][1](a)
