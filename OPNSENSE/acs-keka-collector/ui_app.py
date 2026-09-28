#!/usr/bin/env python3
"""Peak Attendance desktop UI — config, status, minimize to tray."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any
from urllib.parse import quote

from paths import app_dir, resource_dir

ROOT = app_dir()
BUNDLE = resource_dir()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BUNDLE) not in sys.path:
    sys.path.insert(0, str(BUNDLE))

import collector as col  # noqa: E402

APPSETTINGS = ROOT / "appsettings.json"
SINGLETON_HOST = "127.0.0.1"
SINGLETON_PORT = 58741
MUTEX_NAME = "Local\\PeakAttendanceUI_SingleInstance"
ERROR_ALREADY_EXISTS = 183

HELP_TEXT = """Peak Attendance — Help

WHAT IT DOES
  Reads punches from Hikvision Entry / Exit readers and writes them to
  SQL Server database atteninfo (table AccessEvents) for Keka.

FIRST RUN
  1. Set SQL Server (e.g. localhost\\SQLEXPRESS), database atteninfo, user/password.
  2. Click Create / Repair database (SQL Server must already be installed).
  3. Set Entry and Exit device IP, username, password.
  4. Save configuration → Test devices (both SUCCESS).
  5. Run collector now.
  6. Optional: Install / Start with Windows (tray + collect every minute).
     When installed, only Uninstall is enabled; when not, only Install.

DEVICE BUTTONS
  Open device       — opens the reader web page (uses on-screen login)
  Test this device  — checks connectivity / password for one reader
  Reset watermark   — next collect re-reads from First lookback hours
  Enabled           — uncheck to skip this reader without deleting settings
  HTTPS             — use https:// when opening / talking to the device

COLLECTOR SETTINGS
  Sync interval     — how often the Windows task runs (minutes)
  First lookback    — hours to pull when there is no watermark yet
  Timeout           — HTTP wait per device (seconds)
  Overlap           — re-read this many seconds before last watermark
  Max results       — page size for the Hikvision event API

WHERE SETTINGS LIVE
  SQL server login  → appsettings.json next to the exe
  Devices           → SQL dbo.DeviceConfig
  Collector options → SQL dbo.AppConfig
  Sync health       → SQL dbo.CollectorState (Last success / error)

TRAY / WINDOW
  Close window → back to tray (does not quit)
  Quit         → tray menu → Quit
  Press F1 anytime for this help

TROUBLESHOOTING
  Connectivity failed → VPN/LAN to device IP, correct IP/port
  Wrong password      → device admin user/password; wait if lockout
  SQL login failed    → server name, sa password, ODBC 18, SQL running
  No tray icon        → check notification overflow; run with --window
  Logs                → logs\\collector.log next to the exe
"""


def notify_existing_instance(command: str = "SHOW") -> bool:
    """Tell an already-running instance to show/focus. Returns True if one was found."""
    try:
        with socket.create_connection((SINGLETON_HOST, SINGLETON_PORT), timeout=0.8) as sock:
            sock.sendall((command.strip() + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def acquire_mutex() -> Any | None:
    """Windows named mutex. None = another instance already owns it."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def open_ipc_server() -> socket.socket | None:
    """Listen for SHOW commands from later launches. Do not use SO_REUSEADDR."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((SINGLETON_HOST, SINGLETON_PORT))
        sock.listen(5)
        return sock
    except OSError:
        try:
            sock.close()
        except OSError:
            pass
        return None


class PasswordEntry(ttk.Frame):
    def __init__(self, master: tk.Misc, **kwargs: Any) -> None:
        super().__init__(master)
        self.var = tk.StringVar(**kwargs)
        self.show = False
        self.entry = ttk.Entry(self, textvariable=self.var, show="*", width=28)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn = ttk.Button(self, text="Show", width=6, command=self.toggle)
        self.btn.pack(side=tk.LEFT, padx=(4, 0))

    def toggle(self) -> None:
        self.show = not self.show
        self.entry.configure(show="" if self.show else "*")
        self.btn.configure(text="Hide" if self.show else "Show")

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value)


class KekaApp(tk.Tk):
    def __init__(
        self,
        start_in_tray: bool = True,
        singleton_sock: socket.socket | None = None,
        mutex_handle: Any | None = None,
    ) -> None:
        super().__init__()
        self.title("Peak Attendance")
        self.minsize(900, 720)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self.tray_icon = None
        self.start_in_tray = start_in_tray
        self._singleton_sock = singleton_sock
        self._mutex_handle = mutex_handle
        self._build()
        self.bind("<F1>", lambda _e: self.show_help())
        if singleton_sock is not None:
            threading.Thread(target=self._singleton_listen, daemon=True).start()
        if start_in_tray:
            self.withdraw()
            self.after(100, self._boot_to_tray)
        else:
            self.after(50, self._go_fullscreen)
        self.after(200, self.reload_all)

    def _singleton_listen(self) -> None:
        sock = self._singleton_sock
        if sock is None:
            return
        while True:
            try:
                conn, _addr = sock.accept()
            except OSError:
                break
            try:
                data = conn.recv(64).decode("utf-8", errors="ignore").strip().upper()
            except OSError:
                data = ""
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            if data.startswith("SHOW") or data.startswith("OPEN"):
                self.after(0, self._show_from_tray)
            elif data.startswith("QUIT"):
                self.after(0, self.destroy)

    def _boot_to_tray(self) -> None:
        try:
            self._ensure_tray()
            self.set_status("Running in tray. Double-click the tray icon to open.")
        except Exception as exc:
            self.deiconify()
            self.after(50, self._go_fullscreen)
            messagebox.showwarning(
                "Tray unavailable",
                f"Could not start in tray ({exc}). Showing window instead.\n"
                "Install: pip install pystray pillow",
            )

    def _build(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        # Main form area (fills remaining space above footer)
        form = ttk.Frame(root)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        # Row 0: SQL | Collector side by side
        sql_f = ttk.LabelFrame(form, text="SQL Server", padding=6)
        sql_f.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 6))
        self.sql_server = tk.StringVar()
        self.sql_database = tk.StringVar(value="atteninfo")
        self.sql_user = tk.StringVar(value="sa")
        self.sql_pass = PasswordEntry(sql_f)
        self._row(sql_f, 0, "Server", ttk.Entry(sql_f, textvariable=self.sql_server))
        self._row(sql_f, 1, "Database", ttk.Entry(sql_f, textvariable=self.sql_database))
        self._row(sql_f, 2, "Username", ttk.Entry(sql_f, textvariable=self.sql_user))
        self._row(sql_f, 3, "Password", self.sql_pass)

        sync_f = ttk.LabelFrame(form, text="Collector", padding=6)
        sync_f.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 6))
        self.sync_mins = tk.StringVar(value="1")
        self.lookback = tk.StringVar(value="24")
        self.timeout_secs = tk.StringVar(value="20")
        self.overlap_secs = tk.StringVar(value="120")
        self.max_results = tk.StringVar(value="30")
        self._row(sync_f, 0, "Sync interval (min)", ttk.Entry(sync_f, textvariable=self.sync_mins, width=10))
        self._row(sync_f, 1, "First lookback (hrs)", ttk.Entry(sync_f, textvariable=self.lookback, width=10))
        self._row(sync_f, 2, "Timeout (sec)", ttk.Entry(sync_f, textvariable=self.timeout_secs, width=10))
        self._row(sync_f, 3, "Overlap (sec)", ttk.Entry(sync_f, textvariable=self.overlap_secs, width=10))
        self._row(sync_f, 4, "Max results / page", ttk.Entry(sync_f, textvariable=self.max_results, width=10))

        # Row 1: Entry | Exit side by side
        self.device_vars: dict[str, dict[str, Any]] = {}
        for col_i, (key, title) in enumerate((("entry", "Entry device"), ("exit", "Exit device"))):
            df = ttk.LabelFrame(form, text=title, padding=6)
            df.grid(row=1, column=col_i, sticky="nsew", padx=(0 if col_i == 0 else 4, 0 if col_i == 1 else 4), pady=(0, 6))
            ip = tk.StringVar()
            port = tk.StringVar(value="80")
            user = tk.StringVar(value="admin")
            pw = PasswordEntry(df)
            direction = tk.StringVar(value="In" if key == "entry" else "Out")
            name = tk.StringVar(value="Entry Reader" if key == "entry" else "Exit Reader")
            enabled = tk.BooleanVar(value=True)
            https = tk.BooleanVar(value=False)
            last_success = tk.StringVar(value="—")
            last_event = tk.StringVar(value="—")
            last_error = tk.StringVar(value="—")
            self._row(df, 0, "Display name", ttk.Entry(df, textvariable=name))
            self._row(df, 1, "IP address", ttk.Entry(df, textvariable=ip))
            self._row(df, 2, "Port", ttk.Entry(df, textvariable=port, width=10))
            self._row(df, 3, "Username", ttk.Entry(df, textvariable=user))
            self._row(df, 4, "Password", pw)
            self._row(
                df,
                5,
                "Direction",
                ttk.Combobox(df, textvariable=direction, values=["In", "Out"], width=10, state="readonly"),
            )
            flags = ttk.Frame(df)
            flags.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
            ttk.Checkbutton(flags, text="Enabled", variable=enabled).pack(side=tk.LEFT)
            ttk.Checkbutton(flags, text="HTTPS", variable=https).pack(side=tk.LEFT, padx=(12, 0))
            self._row(df, 7, "Last success", ttk.Label(df, textvariable=last_success))
            self._row(df, 8, "Last event", ttk.Label(df, textvariable=last_event))
            self._row(df, 9, "Last error", ttk.Label(df, textvariable=last_error, wraplength=320))
            actions = ttk.Frame(df)
            actions.grid(row=10, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
            ttk.Button(actions, text="Open device", command=lambda k=key: self.open_device(k)).pack(
                side=tk.LEFT
            )
            ttk.Button(actions, text="Test this device", command=lambda k=key: self.test_one_device(k)).pack(
                side=tk.LEFT, padx=(6, 0)
            )
            ttk.Button(actions, text="Reset watermark", command=lambda k=key: self.reset_watermark(k)).pack(
                side=tk.LEFT, padx=(6, 0)
            )
            self.device_vars[key] = {
                "name": name,
                "ip": ip,
                "port": port,
                "user": user,
                "pass": pw,
                "direction": direction,
                "enabled": enabled,
                "https": https,
                "last_success": last_success,
                "last_event": last_event,
                "last_error": last_error,
            }

        # Fixed footer — always visible (no scroll needed)
        footer = ttk.Frame(root)
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        btn = ttk.Frame(footer)
        btn.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        ttk.Button(btn, text="Save configuration", command=self.save_all).pack(side=tk.LEFT)
        ttk.Button(btn, text="Create / Repair database", command=self.create_database).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Test devices", command=self.test_devices).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Run collector now", command=self.run_now).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Reload", command=self.reload_all).pack(side=tk.LEFT, padx=6)
        self.btn_install = ttk.Button(
            btn, text="Install / Start with Windows", command=self.install_startup
        )
        self.btn_install.pack(side=tk.LEFT, padx=6)
        self.btn_uninstall = ttk.Button(
            btn, text="Uninstall / Stop with Windows", command=self.uninstall_startup
        )
        self.btn_uninstall.pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Help", command=self.show_help).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn, text="Minimize to tray", command=self.hide_to_tray).pack(side=tk.RIGHT)
        self.after(300, self._refresh_install_buttons)

        self.status = tk.StringVar(value="Ready.")
        self.status_lbl = ttk.Label(footer, textvariable=self.status, wraplength=900)
        self.status_lbl.grid(row=1, column=0, sticky="ew", pady=2)

        self.log = tk.Text(footer, height=6, wrap=tk.WORD)
        self.log.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        # Stubs used by older helpers
        self._canvas = None
        self._vscroll = None
        self._content = form

    def _on_mousewheel(self, event: tk.Event) -> None:
        return

    def _go_fullscreen(self) -> None:
        self.update_idletasks()
        try:
            self.state("zoomed")
        except tk.TclError:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            self.geometry(f"{screen_w}x{screen_h}+0+0")
        self.update_idletasks()
        win_w = max(self.winfo_width(), 900)
        self.status_lbl.configure(wraplength=max(600, win_w - 40))

    def _fit_to_screen(self) -> None:
        self._go_fullscreen()

    def _row(self, parent: tk.Misc, row: int, label: str, widget: tk.Misc) -> None:
        ttk.Label(parent, text=label, width=18).grid(row=row, column=0, sticky=tk.W, pady=1, padx=(0, 6))
        widget.grid(row=row, column=1, sticky=tk.EW, pady=1)
        parent.columnconfigure(1, weight=1)

    def append_log(self, text: str) -> None:
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)

    def set_status(self, text: str) -> None:
        self.status.set(text)
        self.append_log(text)

    def _help_guide_path(self) -> Path | None:
        for path in (BUNDLE / "docs" / "Peak-Attendance.md", ROOT / "docs" / "Peak-Attendance.md"):
            if path.exists():
                return path
        return None

    def show_help(self) -> None:
        """In-app help window; optional full Markdown guide."""
        win = tk.Toplevel(self)
        win.title("Peak Attendance — Help")
        win.geometry("720x560")
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = tk.Text(frame, wrap=tk.WORD, font=("Consolas", 10))
        scroll = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        text.insert("1.0", HELP_TEXT)
        text.configure(state=tk.DISABLED)

        bar = ttk.Frame(frame)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        def open_guide() -> None:
            path = self._help_guide_path()
            if path is None:
                messagebox.showerror("Help", "Full guide not found (docs/Peak-Attendance.md).", parent=win)
                return
            try:
                if hasattr(os, "startfile"):
                    os.startfile(str(path))  # type: ignore[attr-defined]
                else:
                    webbrowser.open(path.as_uri())
                self.set_status(f"Opened guide: {path}")
            except Exception as exc:
                messagebox.showerror("Help", f"Could not open guide:\n{exc}", parent=win)

        ttk.Button(bar, text="Open full guide", command=open_guide).pack(side=tk.LEFT)
        ttk.Button(bar, text="Close", command=win.destroy).pack(side=tk.RIGHT)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_force()

    def reload_all(self) -> None:
        try:
            if not APPSETTINGS.exists():
                example = BUNDLE / "appsettings.example.json"
                if not example.exists():
                    example = ROOT / "appsettings.example.json"
                APPSETTINGS.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            boot = col.load_json(APPSETTINGS)
            sql = boot["sql"]
            self.sql_server.set(sql.get("server", ""))
            self.sql_database.set(sql.get("database", "atteninfo"))
            self.sql_user.set(sql.get("username", "sa"))
            self.sql_pass.set(sql.get("password", ""))

            cfg = col.load_runtime_config(APPSETTINGS)
            self.sync_mins.set(str(cfg["poll"].get("sync_interval_minutes") or 1))
            self.lookback.set(str(cfg["poll"].get("first_lookback_hours") or 24))
            self.timeout_secs.set(str(cfg["poll"].get("timeout_seconds") or 20))
            self.overlap_secs.set(str(cfg["poll"].get("overlap_seconds") or 120))
            self.max_results.set(str(cfg["poll"].get("max_results") or 30))
            # Load all devices including disabled via direct SQL
            conn = col.connect_sql(sql)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT DeviceKey, DisplayName, IpAddress, Port, Username, Password,
                           Direction, Https, Enabled
                    FROM dbo.DeviceConfig
                    """
                )
                found = {r.DeviceKey: r for r in cur.fetchall()}
                cur.execute(
                    """
                    SELECT DeviceIP, LastEventTime, LastSerialNo, LastSuccessUtc, LastError
                    FROM dbo.CollectorState
                    """
                )
                states = {r.DeviceIP: r for r in cur.fetchall()}
            finally:
                conn.close()
            for key, vars_ in self.device_vars.items():
                row = found.get(key)
                if not row:
                    vars_["last_success"].set("—")
                    vars_["last_event"].set("—")
                    vars_["last_error"].set("—")
                    continue
                vars_["name"].set(row.DisplayName or "")
                vars_["ip"].set(row.IpAddress or "")
                vars_["port"].set(str(row.Port or 80))
                vars_["user"].set(row.Username or "")
                vars_["pass"].set(row.Password or "")
                vars_["direction"].set(row.Direction or ("In" if key == "entry" else "Out"))
                vars_["https"].set(bool(row.Https))
                vars_["enabled"].set(bool(row.Enabled))
                st = states.get(row.IpAddress)
                if st:
                    vars_["last_success"].set(
                        f"{st.LastSuccessUtc} UTC" if st.LastSuccessUtc else "—"
                    )
                    vars_["last_event"].set(str(st.LastEventTime) if st.LastEventTime else "—")
                    vars_["last_error"].set((st.LastError or "").strip() or "—")
                else:
                    vars_["last_success"].set("—")
                    vars_["last_event"].set("—")
                    vars_["last_error"].set("—")
            self.set_status("Configuration loaded.")
            self.after(50, self._fit_to_screen)
            self.after(100, self._refresh_install_buttons)
        except Exception as exc:
            self.set_status(f"Load failed: {exc}")
            messagebox.showerror("Load failed", str(exc))
            self.after(50, self._fit_to_screen)
            self.after(100, self._refresh_install_buttons)

    def save_all(self, quiet: bool = False) -> bool:
        try:
            boot = {
                "sql": {
                    "server": self.sql_server.get().strip(),
                    "database": self.sql_database.get().strip() or "atteninfo",
                    "username": self.sql_user.get().strip(),
                    "password": self.sql_pass.get(),
                    "driver": "ODBC Driver 18 for SQL Server",
                }
            }
            col.save_json(APPSETTINGS, boot)
            conn = col.connect_sql(boot["sql"])
            try:
                cur = conn.cursor()
                for key, vars_ in self.device_vars.items():
                    https = 1 if vars_["https"].get() else 0
                    enabled = 1 if vars_["enabled"].get() else 0
                    cur.execute(
                        """
                        MERGE dbo.DeviceConfig AS t
                        USING (SELECT ? AS DeviceKey) AS s
                        ON t.DeviceKey = s.DeviceKey
                        WHEN MATCHED THEN UPDATE SET
                            DisplayName=?, IpAddress=?, Port=?, Username=?, Password=?,
                            Direction=?, Https=?, Enabled=?, UpdatedAt=SYSUTCDATETIME()
                        WHEN NOT MATCHED THEN INSERT
                            (DeviceKey, DisplayName, IpAddress, Port, Username, Password, Direction, Https, Enabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        key,
                        vars_["name"].get().strip(),
                        vars_["ip"].get().strip(),
                        int(vars_["port"].get() or 80),
                        vars_["user"].get().strip(),
                        vars_["pass"].get(),
                        vars_["direction"].get().strip() or "In",
                        https,
                        enabled,
                        key,
                        vars_["name"].get().strip(),
                        vars_["ip"].get().strip(),
                        int(vars_["port"].get() or 80),
                        vars_["user"].get().strip(),
                        vars_["pass"].get(),
                        vars_["direction"].get().strip() or "In",
                        https,
                        enabled,
                    )
                for k, v in (
                    ("SyncIntervalMinutes", self.sync_mins.get().strip() or "1"),
                    ("FirstLookbackHours", self.lookback.get().strip() or "24"),
                    ("TimeoutSeconds", self.timeout_secs.get().strip() or "20"),
                    ("OverlapSeconds", self.overlap_secs.get().strip() or "120"),
                    ("MaxResults", self.max_results.get().strip() or "30"),
                ):
                    cur.execute(
                        """
                        MERGE dbo.AppConfig AS t
                        USING (SELECT ? AS ConfigKey) AS s
                        ON t.ConfigKey = s.ConfigKey
                        WHEN MATCHED THEN UPDATE SET ConfigValue=?, UpdatedAt=SYSUTCDATETIME()
                        WHEN NOT MATCHED THEN INSERT (ConfigKey, ConfigValue) VALUES (?, ?);
                        """,
                        k,
                        v,
                        k,
                        v,
                    )
                conn.commit()
            finally:
                conn.close()
            self.set_status("Configuration saved.")
            if not quiet:
                messagebox.showinfo("Saved", "Configuration saved to appsettings.json and SQL.")
            return True
        except Exception as exc:
            self.set_status(f"Save failed: {exc}")
            messagebox.showerror("Save failed", str(exc))
            return False

    def _format_device_results(self, results: list[dict], action: str) -> tuple[bool, str]:
        lines: list[str] = []
        failed_names: list[str] = []
        reason_label = {
            "connectivity": "Connectivity",
            "password": "Wrong password / auth",
            "http": "HTTP error",
            "other": "Error",
            "success": "Success",
        }
        for r in results:
            if r.get("ok"):
                lines.append(f"SUCCESS — {r['name']} ({r['ip']})\n  {r['detail']}")
            else:
                failed_names.append(str(r["name"]))
                reason = reason_label.get(str(r.get("reason")), str(r.get("reason")))
                lines.append(
                    f"FAILED — {r['name']} ({r['ip']})\n"
                    f"  Reason: {reason}\n"
                    f"  {r['detail']}"
                )
        body = "\n\n".join(lines) if lines else "No enabled devices configured."
        ok = not failed_names
        if ok:
            summary = f"{action}: all {len(results)} device(s) OK."
        else:
            summary = f"{action}: failed device(s): {', '.join(failed_names)}"
        return ok, f"{summary}\n\n{body}"

    def create_database(self) -> None:
        """Create atteninfo + tables if SQL Server is already installed."""
        if not messagebox.askyesno(
            "Create / Repair database",
            "Create or repair database from the SQL settings above?\n\n"
            "Requires SQL Server already installed and a login that can create databases "
            "(e.g. sa).",
        ):
            return
        if not self.save_all(quiet=True):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Creating / repairing database…"))
                boot = col.load_json(APPSETTINGS)
                notes = col.ensure_atteninfo_database(boot["sql"])
                text = "Database ready.\n\n" + "\n".join(notes)
                self.after(0, lambda: self.append_log(text))
                self.after(0, lambda: self.set_status("Database ready."))
                self.after(0, lambda: messagebox.showinfo("Create / Repair database", text))
                self.after(0, self.reload_all)
            except Exception as exc:
                msg = str(exc)
                low = msg.lower()
                if "login failed" in low:
                    msg = (
                        "SQL login failed. Check Server, Username, and Password.\n"
                        "The login must be allowed to create databases (e.g. sa)."
                    )
                elif "cannot open database" in low and "master" in low:
                    msg = "Cannot connect to SQL Server. Is the service running?"
                self.after(0, lambda: self.set_status(f"Database setup failed: {msg}"))
                self.after(0, lambda: messagebox.showerror("Create / Repair database", msg))

        threading.Thread(target=worker, daemon=True).start()

    def test_devices(self) -> None:
        if not self.save_all(quiet=True):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Testing devices…"))
                cfg = col.load_runtime_config(APPSETTINGS)
                results = col.probe_devices(cfg)
                ok, text = self._format_device_results(results, "Test")
                self.after(0, lambda: self.append_log(text))
                self.after(0, lambda: self.set_status(text.split("\n", 1)[0]))
                self.after(
                    0,
                    lambda: (
                        messagebox.showinfo("Test devices", text)
                        if ok
                        else messagebox.showerror("Test devices", text)
                    ),
                )
            except Exception as exc:
                self.after(0, lambda: self.set_status(f"Test failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Test devices", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def open_device(self, key: str) -> None:
        """Open this device's web UI using the username/password from the screen."""
        vars_ = self.device_vars.get(key)
        if not vars_:
            return
        ip = vars_["ip"].get().strip()
        if not ip:
            messagebox.showerror("Open device", "Enter an IP address first.")
            return
        user = vars_["user"].get().strip()
        if not user:
            messagebox.showerror("Open device", "Enter a username first.")
            return
        password = vars_["pass"].get()
        port = int(vars_["port"].get() or 80)
        scheme = "https" if vars_["https"].get() else "http"
        default_port = 443 if scheme == "https" else 80
        host = ip if port == default_port else f"{ip}:{port}"
        # Embed credentials so the browser can log in (must URL-encode special chars).
        auth = f"{quote(user, safe='')}:{quote(password, safe='')}"
        url = f"{scheme}://{auth}@{host}/"
        safe_url = f"{scheme}://{user}@{host}/"
        try:
            # Clipboard backup: modern browsers often strip user:pass from the URL.
            self.clipboard_clear()
            self.clipboard_append(password)
            webbrowser.open(url)
            self.set_status(
                f"Opened {safe_url} using on-screen login; password also copied to clipboard."
            )
        except Exception as exc:
            messagebox.showerror("Open device", f"Could not open browser:\n{exc}")

    def reset_watermark(self, key: str) -> None:
        """Clear CollectorState for this device so the next run uses First lookback."""
        vars_ = self.device_vars.get(key)
        if not vars_:
            return
        label = vars_["name"].get().strip() or key
        ip = vars_["ip"].get().strip()
        if not ip:
            messagebox.showerror("Reset watermark", f"Enter an IP address for {label} first.")
            return
        lookback = self.lookback.get().strip() or "24"
        if not messagebox.askyesno(
            "Reset watermark",
            f"Clear sync position for {label} ({ip})?\n\n"
            f"The next collector run will re-read about the last {lookback} hour(s).\n"
            "Existing AccessEvents rows are kept (duplicates are skipped).",
        ):
            return
        if not self.save_all(quiet=True):
            return
        try:
            boot = col.load_json(APPSETTINGS)
            col.reset_device_watermark(boot["sql"], ip)
            self.set_status(f"Watermark reset for {label} ({ip}).")
            messagebox.showinfo("Reset watermark", f"Watermark cleared for {label} ({ip}).")
            self.reload_all()
        except Exception as exc:
            self.set_status(f"Reset failed: {exc}")
            messagebox.showerror("Reset watermark", str(exc))

    def _device_dict_from_ui(self, key: str) -> dict[str, Any]:
        """Build a collector device dict from on-screen values (works even if disabled)."""
        vars_ = self.device_vars[key]
        direction = vars_["direction"].get().strip() or "In"
        status = 0 if direction.lower() in {"in", "entry", "0"} else 1
        return {
            "name": key,
            "display_name": vars_["name"].get().strip() or key,
            "ip": vars_["ip"].get().strip(),
            "port": int(vars_["port"].get() or 80),
            "https": bool(vars_["https"].get()),
            "username": vars_["user"].get().strip(),
            "password": vars_["pass"].get(),
            "direction": direction,
            "device_number": 1 if status == 0 else 2,
            "status": status,
        }

    def test_one_device(self, key: str) -> None:
        """Save config, then probe only the selected device (even if disabled)."""
        vars_ = self.device_vars.get(key)
        if not vars_:
            return
        label = vars_["name"].get().strip() or key
        if not vars_["ip"].get().strip():
            messagebox.showerror("Test this device", f"Enter an IP address for {label} first.")
            return
        if not self.save_all(quiet=True):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status(f"Testing {label}…"))
                cfg = col.load_runtime_config(APPSETTINGS)
                cfg = dict(cfg)
                cfg["devices"] = [self._device_dict_from_ui(key)]
                results = col.probe_devices(cfg)
                ok, text = self._format_device_results(results, f"Test {label}")
                self.after(0, lambda: self.append_log(text))
                self.after(0, lambda: self.set_status(text.split("\n", 1)[0]))
                self.after(
                    0,
                    lambda: (
                        messagebox.showinfo("Test this device", text)
                        if ok
                        else messagebox.showerror("Test this device", text)
                    ),
                )
            except Exception as exc:
                self.after(0, lambda: self.set_status(f"Test failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Test this device", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def run_now(self) -> None:
        if not self.save_all(quiet=True):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Running collector…"))
                cfg = col.load_runtime_config(APPSETTINGS)
                results = col.collect_all(cfg, dry_run=False, ignore_watermark=False)
                ok, text = self._format_device_results(results, "Collector")
                self.after(0, lambda: self.append_log(text))
                self.after(0, lambda: self.set_status(text.split("\n", 1)[0]))
                self.after(0, self.reload_all)
                self.after(
                    0,
                    lambda: (
                        messagebox.showinfo("Run collector", text)
                        if ok
                        else messagebox.showerror("Run collector", text)
                    ),
                )
            except Exception as exc:
                # SQL / config failures
                msg = str(exc)
                low = msg.lower()
                if "login failed" in low:
                    msg = "SQL login failed — check SQL server, username, and password."
                elif "odbc" in low or "driver" in low:
                    msg = f"SQL connection failed — {exc}"
                self.after(0, lambda: self.set_status(f"Collector failed: {msg}"))
                self.after(0, lambda: messagebox.showerror("Run collector", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _is_startup_installed(self) -> bool:
        """True if the Windows collector task is registered."""
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", "Peak-Attendance-Collector"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode == 0

    def _refresh_install_buttons(self) -> None:
        """Show Install when not registered; Uninstall when registered."""
        try:
            installed = self._is_startup_installed()
        except Exception:
            installed = False
        if installed:
            self.btn_install.state(["disabled"])
            self.btn_uninstall.state(["!disabled"])
        else:
            self.btn_install.state(["!disabled"])
            self.btn_uninstall.state(["disabled"])

    def install_startup(self) -> None:
        """Register Start-with-Windows, collector task, shortcuts."""
        if self._is_startup_installed():
            messagebox.showinfo(
                "Already installed",
                "Peak Attendance is already registered for Windows startup.\n"
                "Use Uninstall / Stop with Windows first if you want to change it.",
            )
            self._refresh_install_buttons()
            return
        if not messagebox.askyesno(
            "Install / Start with Windows",
            "Register Peak Attendance to:\n"
            "• Start with Windows at logon (tray)\n"
            "• Collect punches every 1 minute (hidden)\n"
            "• Create Desktop + Start Menu shortcuts\n\n"
            "Continue?",
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Installing / registering startup…"))
                if getattr(sys, "frozen", False):
                    msg = self._install_frozen()
                    ok = True
                else:
                    proc = subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(ROOT / "install.ps1"),
                            "-NoStartApp",
                        ],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    msg = ((proc.stdout or "") + (proc.stderr or "")).strip() or f"(exit {proc.returncode})"
                    ok = proc.returncode == 0
                self.after(0, lambda: self.append_log(msg[-1500:]))
                self.after(0, self._refresh_install_buttons)
                if ok:
                    self.after(0, lambda: self.set_status("Installed — starts with Windows; collector every 1 min."))
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Install complete",
                            "Peak Attendance is registered.\n\n"
                            "• Starts with Windows at logon (tray)\n"
                            "• Collector runs every 1 minute (hidden)\n"
                            "• Desktop + Start Menu shortcuts created",
                        ),
                    )
                else:
                    self.after(0, lambda: self.set_status("Install failed"))
                    self.after(0, lambda: messagebox.showerror("Install failed", msg[-1500:]))
            except Exception as exc:
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status(f"Install failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Install failed", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def uninstall_startup(self) -> None:
        """Remove Start-with-Windows, collector task, and shortcuts (keeps exe + DB)."""
        if not self._is_startup_installed():
            messagebox.showinfo(
                "Not installed",
                "Peak Attendance is not registered for Windows startup.\n"
                "Use Install / Start with Windows to register it.",
            )
            self._refresh_install_buttons()
            return
        if not messagebox.askyesno(
            "Uninstall / Stop with Windows",
            "Remove Peak Attendance from Windows startup and stop automatic collection?\n\n"
            "This will:\n"
            "• Delete the every-minute collector task\n"
            "• Remove Startup / Start Menu / Desktop shortcuts\n\n"
            "This will NOT:\n"
            "• Delete PeakAttendance.exe or appsettings.json\n"
            "• Delete the atteninfo database or punches\n\n"
            "Continue?",
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Uninstalling startup / collector…"))
                msg = self._uninstall_startup()
                self.after(0, lambda: self.append_log(msg))
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status("Uninstalled — no longer starts with Windows."))
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Uninstall complete",
                        "Automatic startup and collector task removed.\n\n"
                        "The exe and database were left in place.\n"
                        "You can still open the app and use Run collector now.",
                    ),
                )
            except Exception as exc:
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status(f"Uninstall failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Uninstall failed", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _uninstall_startup(self) -> str:
        """Remove tasks and shortcuts created by Install / Start with Windows."""
        lines: list[str] = []
        for task in ("Peak-Attendance-Collector", "Peak-Attendance-UI"):
            r = subprocess.run(
                ["schtasks", "/Delete", "/TN", task, "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if r.returncode == 0:
                lines.append(f"Removed task: {task}")
            else:
                err = ((r.stderr or "") + (r.stdout or "")).strip()
                if "cannot find" in err.lower() or "does not exist" in err.lower() or r.returncode != 0:
                    lines.append(f"Task not present (ok): {task}")

        paths = [
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "Peak Attendance.lnk",
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Peak Attendance"
            / "Peak Attendance.lnk",
            Path.home() / "Desktop" / "Peak Attendance.lnk",
        ]
        if getattr(sys, "frozen", False):
            paths.append(Path(sys.executable).resolve().parent / "run-collector.vbs")

        for path in paths:
            try:
                if path.exists():
                    path.unlink()
                    lines.append(f"Removed: {path}")
            except OSError as exc:
                lines.append(f"Could not remove {path}: {exc}")

        menu_dir = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Peak Attendance"
        )
        try:
            if menu_dir.exists() and not any(menu_dir.iterdir()):
                menu_dir.rmdir()
                lines.append(f"Removed folder: {menu_dir}")
        except OSError:
            pass

        return "\n".join(lines) if lines else "Nothing to remove."

    def _install_frozen(self) -> str:
        """Register shortcuts + tasks when running as PeakAttendance.exe."""
        exe = Path(sys.executable).resolve()
        app_folder = exe.parent
        lines: list[str] = []

        def shortcut(path: Path, args: str = "") -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            ps = (
                f'$w=New-Object -ComObject WScript.Shell; '
                f'$s=$w.CreateShortcut(\'{path}\'); '
                f'$s.TargetPath=\'{exe}\'; '
                f'$s.Arguments=\'{args}\'; '
                f'$s.WorkingDirectory=\'{app_folder}\'; '
                f'$s.Description=\'Peak Attendance\'; '
                f'$s.Save()'
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                check=False,
                capture_output=True,
                text=True,
            )

        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        start_menu = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Peak Attendance"
        desktop = Path.home() / "Desktop"
        shortcut(startup / "Peak Attendance.lnk")
        shortcut(start_menu / "Peak Attendance.lnk")
        shortcut(desktop / "Peak Attendance.lnk")
        lines.append("Shortcuts: Startup, Start Menu, Desktop")

        # Hidden collector every minute
        tr = f'"{exe}" --collect'
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", "Peak-Attendance-Collector", "/SC", "MINUTE", "/MO", "1", "/F", "/TR", tr],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        lines.append(f"Collector task exit={r.returncode}")
        if r.returncode != 0:
            # Fallback: VBS wrapper with window style 0
            vbs = app_folder / "run-collector.vbs"
            vbs.write_text(
                f'Set sh = CreateObject("WScript.Shell")\n'
                f'sh.CurrentDirectory = "{app_folder}"\n'
                f'sh.Run """{exe}"" --collect", 0, False\n',
                encoding="ascii",
                errors="replace",
            )
            tr2 = f'wscript.exe //B //Nologo "{vbs}"'
            r2 = subprocess.run(
                ["schtasks", "/Create", "/TN", "Peak-Attendance-Collector", "/SC", "MINUTE", "/MO", "1", "/F", "/TR", tr2],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            lines.append(f"Collector VBS task exit={r2.returncode}")
            if r2.returncode != 0:
                raise RuntimeError((r.stderr or "") + (r2.stderr or "") or "schtasks failed")
        return "\n".join(lines)

    def hide_to_tray(self) -> None:
        self.withdraw()
        try:
            self._ensure_tray()
        except Exception as exc:
            self.deiconify()
            messagebox.showwarning(
                "Tray unavailable",
                f"Could not create tray icon ({exc}). Window stayed open.\n"
                "Install: pip install pystray pillow",
            )

    def _ensure_tray(self) -> None:
        if self.tray_icon is not None:
            return
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), color=(20, 90, 160))
        draw = ImageDraw.Draw(img)
        draw.rectangle((12, 12, 52, 52), fill=(240, 240, 240))
        draw.text((22, 20), "P", fill=(20, 90, 160))

        def show(icon: Any = None, item: Any = None) -> None:
            self.after(0, self._show_from_tray)

        def run_now(icon: Any = None, item: Any = None) -> None:
            self.after(0, self.run_now)

        def help_item(icon: Any = None, item: Any = None) -> None:
            self.after(0, self._show_from_tray)
            self.after(200, self.show_help)

        def quit_app(icon: Any = None, item: Any = None) -> None:
            if self.tray_icon is not None:
                self.tray_icon.stop()
                self.tray_icon = None
            self.after(0, self.destroy)

        menu = pystray.Menu(
            pystray.MenuItem("Open Peak Attendance", show, default=True),
            pystray.MenuItem("Run collector now", run_now),
            pystray.MenuItem("Help", help_item),
            pystray.MenuItem("Quit", quit_app),
        )
        self.tray_icon = pystray.Icon("peak_attendance", img, "Peak Attendance", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self.after(50, self._fit_to_screen)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Peak Attendance")
    parser.add_argument(
        "--window",
        action="store_true",
        help="Open the main window immediately (default is start in tray)",
    )
    args = parser.parse_args()

    # Mutex first (reliable on Windows). Socket is only for SHOW signaling.
    mutex = acquire_mutex()
    if mutex is None:
        notify_existing_instance("SHOW")
        return 0

    sock = open_ipc_server()
    app = KekaApp(start_in_tray=not args.window, singleton_sock=sock, mutex_handle=mutex)
    try:
        app.mainloop()
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if mutex is not None:
            try:
                ctypes.windll.kernel32.CloseHandle(mutex)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
