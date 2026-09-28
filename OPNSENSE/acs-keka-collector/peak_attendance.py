#!/usr/bin/env python3
"""Peak Attendance entry point (UI or --collect for scheduled runs)."""

from __future__ import annotations

import sys


def main() -> int:
    if "--collect" in sys.argv:
        # Leave other flags (--since-hours, --probe, …) for collector
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--collect"]
        from collector import main as collector_main

        return collector_main()

    from ui_app import main as ui_main

    return ui_main()


if __name__ == "__main__":
    raise SystemExit(main())
