#!/usr/bin/env python3
"""Peak Energy Biometrics entry point (UI or --collect for scheduled runs)."""

from __future__ import annotations

import sys


def _acquire_collect_mutex() -> object | None:
    """One scheduled collect at a time (PyInstaller cold start can exceed 1 minute)."""
    if sys.platform != "win32":
        return object()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, "Global\\PeakEnergyBiometricsCollect")
    if not handle:
        return None
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def main() -> int:
    if "--collect" in sys.argv:
        # Leave other flags (--since-hours, --probe, …) for collector
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--collect"]
        mutex = _acquire_collect_mutex()
        if mutex is None:
            # Previous collect still running — skip this tick
            return 0
        try:
            from collector import main as collector_main

            return collector_main()
        finally:
            if sys.platform == "win32":
                import ctypes

                ctypes.windll.kernel32.CloseHandle(mutex)

    from ui_app import main as ui_main

    return ui_main()


if __name__ == "__main__":
    raise SystemExit(main())
