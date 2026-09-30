#!/usr/bin/env python3
"""Dashboard — monthly and daily worked hours / break time per employee."""

from __future__ import annotations

import calendar
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


class DashboardWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, appsettings: Path) -> None:
        super().__init__(master)
        self.title("Peak Energy Biometrics — Dashboard")
        self.geometry("1040x680")
        self.appsettings = appsettings
        self._logo_photo = None
        self._header_photo = None
        self.mindate, self.maxdate = punch_mod.day_window()
        today = date.today()
        self._year = today.year
        self._month = today.month
        self._month_rows: list[dict[str, Any]] = []
        self._day_rows: list[dict[str, Any]] = []
        self._month_sort_col = "id"
        self._month_sort_asc = True
        self._day_sort_col = "id"
        self._day_sort_asc = True
        self._selected_emp: str | None = None
        self._apply_window_icon()
        self._build()
        self.after(80, self.reload_month)

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
            "Dashboard",
            "Worked hours and break time · same calendar day Entry → Exit",
        )
        header.pack(fill=tk.X)

        root = ttk.Frame(outer, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        self.month_tab = ttk.Frame(self.notebook, padding=6)
        self.day_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.month_tab, text="Month")
        self.notebook.add(self.day_tab, text="Day")

        self._build_month_tab()
        self._build_day_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _build_month_tab(self) -> None:
        tab = self.month_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=2)
        tab.rowconfigure(2, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.columnconfigure(9, weight=1)

        ttk.Label(bar, text="Month").grid(row=0, column=0, sticky=tk.W, padx=(0, 6))
        months = [calendar.month_name[i] for i in range(1, 13)]
        self.month_name_var = tk.StringVar(value=calendar.month_name[self._month])
        self.month_combo = ttk.Combobox(
            bar,
            textvariable=self.month_name_var,
            values=months,
            width=12,
            state="readonly",
        )
        self.month_combo.grid(row=0, column=1, sticky=tk.W)
        self.month_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_month_picker())

        years = list(range(self.mindate.year, self.maxdate.year + 1))
        self.year_var = tk.StringVar(value=str(self._year))
        self.year_combo = ttk.Combobox(
            bar,
            textvariable=self.year_var,
            values=[str(y) for y in years],
            width=6,
            state="readonly",
        )
        self.year_combo.grid(row=0, column=2, sticky=tk.W, padx=(6, 0))
        self.year_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_month_picker())

        ui_theme.colored_button(bar, "◀ Prev", self._prev_month, kind="ghost").grid(
            row=0, column=3, padx=(8, 0)
        )
        ui_theme.colored_button(bar, "Next ▶", self._next_month, kind="ghost").grid(
            row=0, column=4, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "This month", self._goto_this_month, kind="ghost").grid(
            row=0, column=5, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "Load", self.reload_month, kind="primary").grid(
            row=0, column=6, padx=(12, 0)
        )

        ttk.Label(bar, text="Employee No").grid(row=0, column=7, sticky=tk.W, padx=(16, 6))
        self.month_filter = tk.StringVar()
        ttk.Entry(bar, textvariable=self.month_filter, width=12).grid(row=0, column=8, sticky=tk.W)
        self.month_filter.trace_add("write", lambda *_a: self._apply_month_filter())

        self.month_status = tk.StringVar(value="Select a month and Load.")
        ttk.Label(bar, textvariable=self.month_status, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=10, sticky=tk.W, pady=(6, 0)
        )

        cols = ("id", "name", "days", "worked", "break", "incomplete")
        self.month_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        headings = {
            "id": ("Employee No", 110),
            "name": ("Name", 200),
            "days": ("Days present", 100),
            "worked": ("Worked", 90),
            "break": ("Break", 90),
            "incomplete": ("Incomplete", 90),
        }
        for key, (title, width) in headings.items():
            self.month_tree.heading(key, text=title, command=lambda c=key: self._sort_month(c))
            self.month_tree.column(key, width=width, minwidth=60, stretch=(key == "name"))
        yscroll = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.month_tree.yview)
        self.month_tree.configure(yscrollcommand=yscroll.set)
        self.month_tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")
        self.month_tree.bind("<<TreeviewSelect>>", self._on_month_select)

        detail_f = ttk.LabelFrame(tab, text="Days for selected employee", padding=4)
        detail_f.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        detail_f.columnconfigure(0, weight=1)
        detail_f.rowconfigure(0, weight=1)

        dcols = ("date", "worked", "break", "note")
        self.detail_tree = ttk.Treeview(detail_f, columns=dcols, show="headings", selectmode="browse", height=8)
        dheadings = {
            "date": ("Date", 110),
            "worked": ("Worked", 90),
            "break": ("Break", 90),
            "note": ("Note", 160),
        }
        for key, (title, width) in dheadings.items():
            self.detail_tree.heading(key, text=title)
            self.detail_tree.column(key, width=width, minwidth=50, stretch=(key == "note"))
        dscroll = ttk.Scrollbar(detail_f, orient=tk.VERTICAL, command=self.detail_tree.yview)
        self.detail_tree.configure(yscrollcommand=dscroll.set)
        self.detail_tree.grid(row=0, column=0, sticky="nsew")
        dscroll.grid(row=0, column=1, sticky="ns")

    def _build_day_tab(self) -> None:
        tab = self.day_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.columnconfigure(8, weight=1)

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
        self.day_picker.bind("<<DateEntrySelected>>", lambda _e: self.reload_day())

        ui_theme.colored_button(bar, "◀ Prev", self._prev_day, kind="ghost").grid(
            row=0, column=2, padx=(8, 0)
        )
        ui_theme.colored_button(bar, "Next ▶", self._next_day, kind="ghost").grid(
            row=0, column=3, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "Today", self._goto_today, kind="ghost").grid(
            row=0, column=4, padx=(4, 0)
        )
        ui_theme.colored_button(bar, "Load", self.reload_day, kind="primary").grid(
            row=0, column=5, padx=(12, 0)
        )

        ttk.Label(bar, text="Employee No").grid(row=0, column=6, sticky=tk.W, padx=(16, 6))
        self.day_filter = tk.StringVar()
        ttk.Entry(bar, textvariable=self.day_filter, width=12).grid(row=0, column=7, sticky=tk.W)
        self.day_filter.trace_add("write", lambda *_a: self._apply_day_filter())

        self.day_status = tk.StringVar(value="Select a day and Load.")
        ttk.Label(bar, textvariable=self.day_status, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=9, sticky=tk.W, pady=(6, 0)
        )

        cols = ("id", "name", "worked", "break", "note")
        self.day_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        headings = {
            "id": ("Employee No", 110),
            "name": ("Name", 220),
            "worked": ("Worked", 90),
            "break": ("Break", 90),
            "note": ("Note", 160),
        }
        for key, (title, width) in headings.items():
            self.day_tree.heading(key, text=title, command=lambda c=key: self._sort_day(c))
            self.day_tree.column(key, width=width, minwidth=60, stretch=(key in {"name", "note"}))
        yscroll = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.day_tree.yview)
        self.day_tree.configure(yscrollcommand=yscroll.set)
        self.day_tree.grid(row=1, column=0, sticky="nsew")
        yscroll.grid(row=1, column=1, sticky="ns")

        tip = (
            f"Days available: {self.mindate.isoformat()} → {self.maxdate.isoformat()}  ·  "
            "Worked = Entry→Exit · Break = Exit→next Entry · Missing exit is not counted."
        )
        ttk.Label(tab, text=tip, style="Muted.TLabel").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

    def _on_tab_changed(self, _event: Any = None) -> None:
        try:
            tab_id = self.notebook.index(self.notebook.select())
        except tk.TclError:
            return
        if tab_id == 1 and not self._day_rows:
            self.reload_day()

    # --- Month navigation -----------------------------------------------------

    def _on_month_picker(self) -> None:
        name = self.month_name_var.get()
        try:
            month = list(calendar.month_name).index(name)
        except ValueError:
            month = self._month
        try:
            year = int(self.year_var.get())
        except ValueError:
            year = self._year
        self._year, self._month = punch_mod.shift_month(
            year, month, 0, mindate=self.mindate, maxdate=self.maxdate
        )
        self._sync_month_picker()
        self.reload_month()

    def _sync_month_picker(self) -> None:
        self.month_name_var.set(calendar.month_name[self._month])
        self.year_var.set(str(self._year))

    def _prev_month(self) -> None:
        self._year, self._month = punch_mod.shift_month(
            self._year, self._month, -1, mindate=self.mindate, maxdate=self.maxdate
        )
        self._sync_month_picker()
        self.reload_month()

    def _next_month(self) -> None:
        self._year, self._month = punch_mod.shift_month(
            self._year, self._month, 1, mindate=self.mindate, maxdate=self.maxdate
        )
        self._sync_month_picker()
        self.reload_month()

    def _goto_this_month(self) -> None:
        today = date.today()
        self._year, self._month = punch_mod.shift_month(
            today.year, today.month, 0, mindate=self.mindate, maxdate=self.maxdate
        )
        self._sync_month_picker()
        self.reload_month()

    # --- Day navigation -------------------------------------------------------

    def _selected_day(self) -> date:
        raw = self.day_picker.get_date()
        day = raw if isinstance(raw, date) else date.today()
        if day < self.mindate:
            return self.mindate
        if day > self.maxdate:
            return self.maxdate
        return day

    def _set_day(self, day: date) -> None:
        day = punch_mod.shift_day(day, 0, mindate=self.mindate, maxdate=self.maxdate)
        self.day_picker.set_date(day)

    def _prev_day(self) -> None:
        self._set_day(
            punch_mod.shift_day(self._selected_day(), -1, mindate=self.mindate, maxdate=self.maxdate)
        )
        self.reload_day()

    def _next_day(self) -> None:
        self._set_day(
            punch_mod.shift_day(self._selected_day(), 1, mindate=self.mindate, maxdate=self.maxdate)
        )
        self.reload_day()

    def _goto_today(self) -> None:
        self._set_day(date.today())
        self.reload_day()

    # --- Load -----------------------------------------------------------------

    def reload_month(self) -> None:
        label = punch_mod.month_label(self._year, self._month)
        self.month_status.set(f"Loading {label}…")
        self.month_tree.delete(*self.month_tree.get_children())
        self.detail_tree.delete(*self.detail_tree.get_children())
        self._selected_emp = None
        year, month = self._year, self._month

        def worker() -> None:
            try:
                sql = self._sql()
                rows = punch_mod.load_month_summary(sql, year, month)
                server = str(sql.get("server") or "")
                db = str(sql.get("database") or "")
                table = col.punch_table_name(sql)
                self.after(0, lambda: self._show_month(rows, year, month, server, db, table))
            except Exception as exc:
                self.after(0, lambda: self._load_failed("Month", exc, self.month_status))

        threading.Thread(target=worker, daemon=True).start()

    def reload_day(self) -> None:
        day = self._selected_day()
        self.day_status.set(f"Loading {day.isoformat()}…")
        self.day_tree.delete(*self.day_tree.get_children())

        def worker() -> None:
            try:
                sql = self._sql()
                rows = punch_mod.load_day_summary(sql, day)
                server = str(sql.get("server") or "")
                db = str(sql.get("database") or "")
                table = col.punch_table_name(sql)
                self.after(0, lambda: self._show_day(rows, day, server, db, table))
            except Exception as exc:
                self.after(0, lambda: self._load_failed("Day", exc, self.day_status))

        threading.Thread(target=worker, daemon=True).start()

    def _load_failed(self, title: str, exc: Exception, status: tk.StringVar) -> None:
        status.set("Load failed.")
        messagebox.showerror(f"Dashboard — {title}", str(exc), parent=self)

    def _show_month(
        self,
        rows: list[dict[str, Any]],
        year: int,
        month: int,
        server: str,
        db: str,
        table: str,
    ) -> None:
        self._month_rows = rows
        self._apply_month_filter()
        shown = len(self.month_tree.get_children())
        self.month_status.set(
            f"{punch_mod.month_label(year, month)}  ·  {shown} shown / {len(rows)} employees  ·  "
            f"{server} / {db}.dbo.{table}"
        )

    def _show_day(
        self,
        rows: list[dict[str, Any]],
        day: date,
        server: str,
        db: str,
        table: str,
    ) -> None:
        self._day_rows = rows
        self._apply_day_filter()
        shown = len(self.day_tree.get_children())
        self.day_status.set(
            f"{day.isoformat()}  ·  {shown} shown / {len(rows)} employees  ·  "
            f"{server} / {db}.dbo.{table}"
        )

    # --- Filters / sort / detail ----------------------------------------------

    def _filtered_month(self) -> list[dict[str, Any]]:
        needle = self.month_filter.get().strip().lower()
        if not needle:
            return list(self._month_rows)
        return [r for r in self._month_rows if needle in str(r.get("employee_no") or "").lower()]

    def _filtered_day(self) -> list[dict[str, Any]]:
        needle = self.day_filter.get().strip().lower()
        if not needle:
            return list(self._day_rows)
        return [r for r in self._day_rows if needle in str(r.get("employee_no") or "").lower()]

    def _apply_month_filter(self) -> None:
        rows = self._sorted_month(self._filtered_month())
        self.month_tree.delete(*self.month_tree.get_children())
        self.detail_tree.delete(*self.detail_tree.get_children())
        for row in rows:
            self.month_tree.insert(
                "",
                tk.END,
                iid=str(row["employee_no"]),
                values=(
                    row["employee_no"],
                    row.get("name") or "—",
                    row.get("days_present", 0),
                    row.get("worked_label") or "0:00",
                    row.get("break_label") or "0:00",
                    row.get("incomplete_days", 0),
                ),
            )
        if self._selected_emp and self.month_tree.exists(self._selected_emp):
            self.month_tree.selection_set(self._selected_emp)
            self._fill_detail(self._selected_emp)

    def _apply_day_filter(self) -> None:
        rows = self._sorted_day(self._filtered_day())
        self.day_tree.delete(*self.day_tree.get_children())
        for row in rows:
            note = ""
            days = row.get("days") or []
            if days:
                note = str(days[0].get("note") or "")
            elif row.get("incomplete_days"):
                note = "Missing exit"
            self.day_tree.insert(
                "",
                tk.END,
                values=(
                    row["employee_no"],
                    row.get("name") or "—",
                    row.get("worked_label") or "0:00",
                    row.get("break_label") or "0:00",
                    note or "—",
                ),
            )

    def _sort_month(self, col: str) -> None:
        if self._month_sort_col == col:
            self._month_sort_asc = not self._month_sort_asc
        else:
            self._month_sort_col = col
            self._month_sort_asc = True
        self._apply_month_filter()

    def _sort_day(self, col: str) -> None:
        if self._day_sort_col == col:
            self._day_sort_asc = not self._day_sort_asc
        else:
            self._day_sort_col = col
            self._day_sort_asc = True
        self._apply_day_filter()

    def _sorted_month(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        key = self._month_sort_col
        mapping = {
            "id": lambda r: str(r.get("employee_no") or "").lower(),
            "name": lambda r: str(r.get("name") or "").lower(),
            "days": lambda r: int(r.get("days_present") or 0),
            "worked": lambda r: int(r.get("worked_seconds") or 0),
            "break": lambda r: int(r.get("break_seconds") or 0),
            "incomplete": lambda r: int(r.get("incomplete_days") or 0),
        }
        fn = mapping.get(key, mapping["id"])
        return sorted(rows, key=fn, reverse=not self._month_sort_asc)

    def _sorted_day(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        key = self._day_sort_col
        mapping = {
            "id": lambda r: str(r.get("employee_no") or "").lower(),
            "name": lambda r: str(r.get("name") or "").lower(),
            "worked": lambda r: int(r.get("worked_seconds") or 0),
            "break": lambda r: int(r.get("break_seconds") or 0),
            "note": lambda r: str((r.get("days") or [{}])[0].get("note") or "").lower(),
        }
        fn = mapping.get(key, mapping["id"])
        return sorted(rows, key=fn, reverse=not self._day_sort_asc)

    def _on_month_select(self, _event: Any = None) -> None:
        sel = self.month_tree.selection()
        if not sel:
            self._selected_emp = None
            self.detail_tree.delete(*self.detail_tree.get_children())
            return
        emp = sel[0]
        self._selected_emp = emp
        self._fill_detail(emp)

    def _fill_detail(self, emp: str) -> None:
        self.detail_tree.delete(*self.detail_tree.get_children())
        rec = next((r for r in self._month_rows if str(r.get("employee_no")) == emp), None)
        if not rec:
            return
        for day in rec.get("days") or []:
            d = day.get("date")
            self.detail_tree.insert(
                "",
                tk.END,
                values=(
                    d.isoformat() if hasattr(d, "isoformat") else str(d),
                    day.get("worked_label") or "0:00",
                    day.get("break_label") or "0:00",
                    day.get("note") or "—",
                ),
            )
