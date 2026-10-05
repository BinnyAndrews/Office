#!/usr/bin/env python3
"""Peak Energy Dashboard — read-only SQL views (no collector / devices)."""

from __future__ import annotations

import sys


def main() -> int:
    from ui_dashboard_app import main as ui_main

    return ui_main()


if __name__ == "__main__":
    raise SystemExit(main())
