#!/usr/bin/env python3
"""Punches browser — view SQL punches by selectable day (2-year range)."""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

import collector as col
import punches as punch_mod
import theme as ui_theme
from paths import logo_ico_path, logo_png_path
from tkcalendar import DateEntry

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore


class PunchesWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, appsettings: Path) -> None:
        super().__init__(master)
        self.title("Peak Energy Biometrics — Punches")
        self.geometry("980x620")
        self.appsettings = appsettings
        self._logo_photo = None
        self._rows: list[dict[str, Any]] = []
        self._sort_col = "time"
        self._sort_asc = True
        self.mindate, self.maxdate = punch_mod.day_window()
        self._apply_window_icon()
        self._build()
        self.after(80, self.reload)

    def _apply_window_icon(self) -> None:
        ico = logo_ico_path()
        if ico is not None:
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                try:
                    self.iconbitmap(str(ico))
                except tk.TclError:
                    pass
        png = logo_png_path()
        if png is None or Image is None or ImageTk is None:
            return
        try:
            img = Image.open(png).convert("RGBA")
            img.thumbnail((64, 64))
            self._logo_photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._logo_photo)
        except Exception:
            pass

    def _sql(self) -> dict[str, Any]:
        return col.load_json(self.appsettings)["sql"]

    def _build(self) -> None:
        ui_theme.apply_theme(self)
        outer = tk.Frame(self, bg=ui_theme.BG)
        outer.pack(fill=tk.BOTH, expand=True)

        header, self._header_photo = ui_theme.build_header(
            outer,
            "Punches",
            "SQL punch table · pick any day in the last 2 years",
        )
        header.pack(fill=tk.X)

        root = ttk.Frame(outer, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        bar = ttk.Frame(root)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.columnconfigure(9, weight=1)

        ttk.Label(bar, text="Day").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        today = date.today()
        self.day_picker = DateEntry(
            bar,
            width=12,
            date_pattern="yyyy-mm-dd",
            year=today.year,
            month=today.month,
            day=today.day,
            mindate=self.mindate,
            maxdate=self.maxdate,
            background=ui_theme.NAVY,
            foreground="white",
            headersbackground=ui_theme.NAVY,
            headersforeground="white",
            selectbackground=ui_theme.CYAN,
            selectforeground=ui_theme.NAVY_DARK,
        )
        self.day_picker.grid(row=0, column=1, sticky=tk.W)

        ui_theme.colored_button(bar, "◀ Prev", self._prev_day, kind="ghost").grid(
            row=0, column=2, padx=(8, 0)
        )
        ui_theme.colored_button(bar, "Next ▶", self._next_day, kind="ghost").grid(
            row=0, column=3, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "Today", self._goto_today, kind="ghost").grid(
            row=0, column=4, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "Load punches", self.reload, kind="primary").grid(
            row=0, column=5, padx=(12, 0)
        )
        ui_theme.colored_button(
            bar, "Import history from ACS SQL…", self.import_from_acs, kind="accent"
        ).grid(row=0, column=6, padx=(12, 0))

        ttk.Label(bar, text="Employee No").grid(row=0, column=7, sticky=tk.W, padx=(16, 6))
        self.filter_id = tk.StringVar()
        ttk.Entry(bar, textvariable=self.filter_id, width=12).grid(row=0, column=8, sticky=tk.W)
        self.filter_id.trace_add("write", lambda *_a: self._apply_filter())

        self.status = tk.StringVar(value="Select a day and Load punches.")
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=10, sticky=tk.W, pady=(6, 0)
        )

        cols = ("date", "time", "id", "name", "direction", "device", "auth")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
        headings = {
            "date": ("Date", 100),
            "time": ("Time", 90),
            "id": ("Employee No", 110),
            "name": ("Name", 180),
            "direction": ("Direction", 90),
            "device": ("Device", 140),
            "auth": ("Auth type", 160),
        }
        for key, (title, width) in headings.items():
            self.tree.heading(key, text=title, command=lambda c=key: self._sort_by(c))
            self.tree.column(key, width=width, minwidth=60, stretch=(key in {"name", "device", "auth"}))

        yscroll = ttk.Scrollbar(root, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")

        tip = (
            f"Days available: {self.mindate.isoformat()} → {self.maxdate.isoformat()}  ·  "
            "Uses Server / Database / Punch table from the main window."
        )
        ttk.Label(root, text=tip, style="Muted.TLabel").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        self.day_picker.bind("<<DateEntrySelected>>", lambda _e: self.reload())

    def _selected_day(self) -> date:
        raw = self.day_picker.get_date()
        if isinstance(raw, date):
            day = raw
        else:
            day = date.today()
        if day < self.mindate:
            return self.mindate
        if day > self.maxdate:
            return self.maxdate
        return day

    def _set_day(self, day: date) -> None:
        day = punch_mod.shift_day(day, 0, mindate=self.mindate, maxdate=self.maxdate)
        self.day_picker.set_date(day)

    def _prev_day(self) -> None:
        self._set_day(punch_mod.shift_day(self._selected_day(), -1, mindate=self.mindate, maxdate=self.maxdate))
        self.reload()

    def _next_day(self) -> None:
        self._set_day(punch_mod.shift_day(self._selected_day(), 1, mindate=self.mindate, maxdate=self.maxdate))
        self.reload()

    def _goto_today(self) -> None:
        self._set_day(date.today())
        self.reload()

    def import_from_acs(self) -> None:
        """One-time copy of previous punches/helpers from ACS SQL into this PC's SQL."""
        dest = self._sql()
        dest_server = str(dest.get("server") or "").strip()
        user = str(dest.get("username") or "sa").strip() or "sa"
        password = str(dest.get("password") or "")
        source_default = "10.80.100.10,1433"

        win = tk.Toplevel(self)
        win.title("Import history from ACS SQL")
        win.geometry("460x260")
        win.transient(self)
        win.grab_set()
        ui_theme.apply_theme(win)

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="Copies previous punches (and helpers) from the ACS SQL Server\n"
            "into the Server configured in the main window.\n"
            "Existing local rows in those tables are replaced.",
            style="Muted.TLabel",
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        src_var = tk.StringVar(value=source_default)
        ttk.Label(frame, text="Source (ACS)").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=src_var).grid(row=1, column=1, sticky=tk.EW, pady=2)
        ttk.Label(frame, text="Destination").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(frame, text=dest_server or "(set Server on main window)").grid(
            row=2, column=1, sticky=tk.W, pady=2
        )

        helpers_var = tk.BooleanVar(value=True)
        punches_var = tk.BooleanVar(value=True)
        ui_theme.colored_checkbutton(
            frame, "Copy Employees / devices / config", helpers_var
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ui_theme.colored_checkbutton(
            frame, "Copy punches (atteninfo) — can take several minutes", punches_var
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W)

        status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status, style="Muted.TLabel").grid(
            row=5, column=0, columnspan=2, sticky=tk.W, pady=(10, 0)
        )

        btns = ttk.Frame(frame)
        btns.grid(row=6, column=0, columnspan=2, sticky=tk.E, pady=(12, 0))

        def start() -> None:
            source = src_var.get().strip()
            if not source:
                messagebox.showerror("Import", "Enter the ACS SQL Server.", parent=win)
                return
            if not dest_server:
                messagebox.showerror(
                    "Import",
                    "Set Server on the main window (e.g. localhost\\SQLEXPRESS) and Save first.",
                    parent=win,
                )
                return
            if source.lower() == dest_server.lower():
                messagebox.showerror(
                    "Import",
                    "Source and destination are the same. Point the main window at local SQL Express first.",
                    parent=win,
                )
                return
            if not helpers_var.get() and not punches_var.get():
                messagebox.showerror("Import", "Select at least one copy option.", parent=win)
                return
            if not messagebox.askyesno(
                "Import history",
                f"Replace data on:\n  {dest_server}\n\nwith a copy from:\n  {source}\n\nContinue?",
                parent=win,
            ):
                return

            import_btn.configure(state=tk.DISABLED)
            status.set("Importing…")

            def worker() -> None:
                try:
                    import acs_copy

                    def prog(msg: str) -> None:
                        self.after(0, lambda m=msg: status.set(m))

                    notes = acs_copy.copy_acs_data(
                        source_server=source,
                        dest_server=dest_server,
                        username=user,
                        password=password,
                        include_helpers=bool(helpers_var.get()),
                        include_punches=bool(punches_var.get()),
                        progress=prog,
                    )
                    text = "Import finished.\n\n" + "\n".join(notes)

                    def done() -> None:
                        status.set("Import finished.")
                        messagebox.showinfo("Import history", text, parent=win)
                        win.destroy()
                        self.reload()

                    self.after(0, done)
                except Exception as exc:
                    self.after(
                        0,
                        lambda: (
                            status.set("Import failed."),
                            import_btn.configure(state=tk.NORMAL),
                            messagebox.showerror("Import history", str(exc), parent=win),
                        ),
                    )

            threading.Thread(target=worker, daemon=True).start()

        import_btn = ui_theme.colored_button(btns, "Start import", start, kind="primary")
        import_btn.pack(side=tk.LEFT, padx=(0, 6))
        ui_theme.colored_button(btns, "Cancel", win.destroy, kind="ghost").pack(side=tk.LEFT)

    def reload(self) -> None:
        day = self._selected_day()
        self.status.set(f"Loading punches for {day.isoformat()}…")
        self.tree.delete(*self.tree.get_children())

        def worker() -> None:
            try:
                sql = self._sql()
                rows = punch_mod.fetch_punches_for_day(sql, day)
                server = str(sql.get("server") or "")
                db = str(sql.get("database") or "")
                table = col.punch_table_name(sql)
                self.after(0, lambda: self._show_rows(rows, day, server, db, table))
            except Exception as exc:
                self.after(0, lambda: self._load_failed(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _load_failed(self, exc: Exception) -> None:
        self.status.set("Load failed.")
        messagebox.showerror("Punches", str(exc), parent=self)

    def _show_rows(
        self,
        rows: list[dict[str, Any]],
        day: date,
        server: str,
        db: str,
        table: str,
    ) -> None:
        self._rows = rows
        self._apply_filter()
        shown = len(self.tree.get_children())
        self.status.set(
            f"{day.isoformat()}  ·  {shown} shown / {len(rows)} total  ·  "
            f"{server} / {db}.dbo.{table}"
        )

    def _filtered_rows(self) -> list[dict[str, Any]]:
        needle = self.filter_id.get().strip().lower()
        if not needle:
            return list(self._rows)
        out: list[dict[str, Any]] = []
        for row in self._rows:
            if needle in str(row.get("ID") or "").lower():
                out.append(row)
        return out

    def _apply_filter(self) -> None:
        rows = self._filtered_rows()
        rows = self._sorted(rows)
        self.tree.delete(*self.tree.get_children())
        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    punch_mod.format_punch_date(row),
                    punch_mod.format_punch_time(row),
                    str(row.get("ID") or ""),
                    str(row.get("display_name") or "—"),
                    str(row.get("direction_label") or "—"),
                    str(row.get("device") or "—"),
                    str(row.get("authenticationtype") or "—"),
                ),
            )

    def _sort_by(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._apply_filter()

    def _sorted(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        key = self._sort_col
        mapping = {
            "date": lambda r: punch_mod.format_punch_date(r),
            "time": lambda r: punch_mod.format_punch_time(r),
            "id": lambda r: str(r.get("ID") or "").lower(),
            "name": lambda r: str(r.get("display_name") or "").lower(),
            "direction": lambda r: str(r.get("direction_label") or "").lower(),
            "device": lambda r: str(r.get("device") or "").lower(),
            "auth": lambda r: str(r.get("authenticationtype") or "").lower(),
        }
        fn = mapping.get(key, mapping["time"])
        return sorted(rows, key=fn, reverse=not self._sort_asc)
