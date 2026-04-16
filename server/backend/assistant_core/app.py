from __future__ import annotations

try:
    from app import app, main
except ImportError:
    from ..app import app, main


if __name__ == "__main__":
    main()
