#!/usr/bin/env python3
"""
Copy Peak ACS SQL data from remote (10.80.100.10) → local SQL Express.

Usage:
  .\\venv\\Scripts\\python.exe sql\\copy_acs_to_local.py
  .\\venv\\Scripts\\python.exe sql\\copy_acs_to_local.py --source "10.80.100.10,1433" --dest "localhost\\SQLEXPRESS"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import acs_copy  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Copy ACS master tables remote → local")
    p.add_argument("--source", default="10.80.100.10,1433")
    p.add_argument("--dest", default=r"localhost\SQLEXPRESS")
    p.add_argument("--user", default="sa")
    p.add_argument("--password", default="cctv@2025")
    p.add_argument("--skip-punches", action="store_true")
    p.add_argument("--punches-only", action="store_true")
    args = p.parse_args()

    print(f"Source: {args.source} / master")
    print(f"Dest:   {args.dest} / master")

    notes = acs_copy.copy_acs_data(
        source_server=args.source,
        dest_server=args.dest,
        username=args.user,
        password=args.password,
        include_helpers=not args.punches_only,
        include_punches=not args.skip_punches,
        progress=print,
    )
    for n in notes:
        print(n)
    print("Done. In the app use Server=localhost\\SQLEXPRESS, then open Punches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
