import sys

# На русской Windows вывод в канал идёт в cp1251, а там нет ✓ ✗ ⚠ — без этого rk падает на первой же строке
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from rk.cli import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
