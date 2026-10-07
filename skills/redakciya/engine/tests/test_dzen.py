import pytest

from rk import journal
from rk.connectors.base import Fail
from rk.connectors.dzen import DzenTgImport


class P:
    pass


def test_needs_tg(tmp_path):
    p = P()
    p.dir = tmp_path
    c = DzenTgImport(cfg=None, opts={"key": "dzen", "channel": "my"})
    with pytest.raises(Fail, match="tg"):
        c.publish(p, dry=False)
    journal.put(tmp_path, "tg", "https://t.me/c/1")
    assert c.publish(p, dry=False).url == "https://dzen.ru/my"
