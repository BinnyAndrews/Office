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

from paths import app_dir, logo_ico_path, logo_png_path, resource_dir

ROOT = app_dir()
BUNDLE = resource_dir()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BUNDLE) not in sys.path:
    sys.path.insert(0, str(BUNDLE))

import collector as col  # noqa: E402
import theme as ui_theme  # noqa: E402

APPSETTINGS = ROOT / "appsettings.json"
SINGLETON_HOST = "127.0.0.1"
SINGLETON_PORT = 58741
MUTEX_NAME = "Local\\PeakAttendanceUI_SingleInstance"
ERROR_ALREADY_EXISTS = 183

HELP_TEXT = """Peak Attendance — Help

WHAT IT DOES
  Reads punches from Hikvision Entry / Exit readers into SQL Server
  (atteninfo.dbo.AccessEvents) for Keka.
  Also manages employees (people + face photo) with SQL as master
  and push/pull to both door readers.

FIRST RUN
  1. Set SQL Server (e.g. localhost\\SQLEXPRESS), database atteninfo,
     username/password.
  2. Create / Repair database (SQL Server must already be installed).
     Creates atteninfo + AccessEvents, DeviceConfig, Employees, etc.
  3. Set Entry and Exit IP, username, password (Enabled / HTTPS as needed).
  4. Save configuration → Test devices (both SUCCESS).
  5. Run collector now (punches appear in AccessEvents).
  6. Optional: Employees → Pull from devices (merge people into SQL).
  7. Optional: Install / Start with Windows (tray + collect every minute).
     If already installed, only Uninstall is enabled (and the reverse).

DEVICE PANEL (per reader)
  Open device       — opens browser + login helper (Copy username/password).
                      Browsers cannot autofill Hikvision login forms.
  Test this device  — probe one reader (works even if Enabled is off)
  Reset watermark   — clear sync position; next run uses First lookback
  Enabled           — skip this reader without deleting settings
  HTTPS             — use https for Open / API (auto-sets Port 443;
                      leave unchecked for normal HTTP on port 80)
  Last success / last event / last error — from CollectorState (read-only)

COLLECTOR SETTINGS
  Sync interval     — Windows task period (minutes) when installed
  First lookback    — hours to pull when no watermark exists
  Timeout           — HTTP wait per device (seconds)
  Overlap           — re-read seconds before last watermark
  Max results       — Hikvision AcsEvent page size

EMPLOYEES (main button → Employees window)
  SQL dbo.Employees is the master copy of people.
  Pull from devices — read Entry + Exit UserInfo, merge by Employee No,
                      store face JPEG when available
  New / edit        — fill Employee No, name, validity, card, photo
  Save + Push       — save SQL, then create/update on BOTH readers
                      (UserInfo + face enroll when photo present)
  Delete            — remove from BOTH readers and SQL
  Entry/Exit status — dbo.EmployeeDeviceSync (OK / Missing / Error / Partial)
  Face photo limits — JPEG only (PNG/BMP auto-converted); max 200 KB;
                      min 80×80; recommended ≥ 640×480
                      Oversize photos are auto-resized/compressed on Load;
                      alerts if still over limit or below recommended size

INSTALL / UNINSTALL
  Install / Start with Windows
    • Tray at Windows logon
    • Hidden collector every 1 minute (Peak-Attendance-Collector task)
    • Desktop + Start Menu shortcuts
  Uninstall / Stop with Windows
    • Removes tasks + shortcuts
    • Keeps PeakAttendance.exe, appsettings.json, and database
  Only one of Install / Uninstall is enabled at a time.

WHERE DATA LIVES
  SQL login              → appsettings.json next to the exe
  Devices                → dbo.DeviceConfig
  Collector options      → dbo.AppConfig
  Punch sync health      → dbo.CollectorState
  Employees              → dbo.Employees
  Employee device status → dbo.EmployeeDeviceSync
  Punches (Keka)         → dbo.AccessEvents

TRAY / WINDOW / BRANDING
  Close window → tray (does not quit)
  Quit         → tray menu → Quit
  F1 or Help   → this text; Open full guide → Peak-Attendance.md
  Icon         → Peak Energy logo (exe, window, tray)

TROUBLESHOOTING
  Connectivity failed → VPN/LAN, correct IP/port
  Wrong password      → device admin credentials; wait if lockout
  SQL login failed    → server name, password, ODBC 18, SQL running
  No tray icon        → notification overflow; try --window
  Employee push fail  → Test devices first; check Entry/Exit status columns
  Face not on device  → JPEG enrolled best-effort; retry Save + Push
  Photo too large     → max 200 KB; app auto-compresses on Load — use a
                        closer face crop if still rejected
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
        self._logo_photo = None
        self._header_photo = None
        self.start_in_tray = start_in_tray
        self._singleton_sock = singleton_sock
        self._mutex_handle = mutex_handle
        ui_theme.apply_theme(self)
        self._apply_app_icon()
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
        ui_theme.apply_theme(self)
        outer = tk.Frame(self, bg=ui_theme.BG)
        outer.pack(fill=tk.BOTH, expand=True)

        header, self._header_photo = ui_theme.build_header(
            outer,
            "Peak Attendance",
            "Hikvision → SQL → Keka · Peak Energy",
        )
        header.pack(fill=tk.X)

        root = ttk.Frame(outer, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        # Main form area (fills remaining space above footer)
        form = ttk.Frame(root)
        form.grid(row=0, column=0, sticky="nsew")
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        # Row 0: SQL | Collector side by side
        sql_f = ttk.LabelFrame(form, text="SQL Server", padding=8)
        sql_f.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 6))
        self.sql_server = tk.StringVar()
        self.sql_database = tk.StringVar(value="atteninfo")
        self.sql_user = tk.StringVar(value="sa")
        self.sql_pass = PasswordEntry(sql_f)
        self._row(sql_f, 0, "Server", ttk.Entry(sql_f, textvariable=self.sql_server))
        self._row(sql_f, 1, "Database", ttk.Entry(sql_f, textvariable=self.sql_database))
        self._row(sql_f, 2, "Username", ttk.Entry(sql_f, textvariable=self.sql_user))
        self._row(sql_f, 3, "Password", self.sql_pass)

        sync_f = ttk.LabelFrame(form, text="Collector", padding=8)
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
            df = ttk.LabelFrame(form, text=title, padding=8)
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
            ui_theme.colored_checkbutton(flags, "Enabled", enabled).pack(side=tk.LEFT)
            ui_theme.colored_checkbutton(flags, "HTTPS", https).pack(side=tk.LEFT, padx=(12, 0))
            https.trace_add("write", lambda *_a, k=key: self._on_https_toggle(k))
            self._row(df, 7, "Last success", ttk.Label(df, textvariable=last_success))
            self._row(df, 8, "Last event", ttk.Label(df, textvariable=last_event))
            self._row(df, 9, "Last error", ttk.Label(df, textvariable=last_error, wraplength=320))
            actions = ttk.Frame(df)
            actions.grid(row=10, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
            ui_theme.colored_button(
                actions, "Open device", lambda k=key: self.open_device(k), kind="ghost"
            ).pack(side=tk.LEFT)
            ui_theme.colored_button(
                actions, "Test this device", lambda k=key: self.test_one_device(k), kind="accent"
            ).pack(side=tk.LEFT, padx=(6, 0))
            ui_theme.colored_button(
                actions, "Reset watermark", lambda k=key: self.reset_watermark(k), kind="ghost"
            ).pack(side=tk.LEFT, padx=(6, 0))
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
        footer = tk.Frame(root, bg=ui_theme.BG, padx=4, pady=6)
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        btn = tk.Frame(footer, bg=ui_theme.BG)
        btn.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        ui_theme.colored_button(btn, "Save configuration", self.save_all, kind="primary").pack(side=tk.LEFT)
        ui_theme.colored_button(
            btn, "Create / Repair database", self.create_database, kind="ghost"
        ).pack(side=tk.LEFT, padx=6)
        ui_theme.colored_button(btn, "Test devices", self.test_devices, kind="accent").pack(
            side=tk.LEFT, padx=6
        )
        ui_theme.colored_button(btn, "Run collector now", self.run_now, kind="success").pack(
            side=tk.LEFT, padx=6
        )
        ui_theme.colored_button(btn, "Employees", self.open_employees, kind="accent").pack(
            side=tk.LEFT, padx=6
        )
        ui_theme.colored_button(btn, "Reload", self.reload_all, kind="ghost").pack(side=tk.LEFT, padx=6)
        self.btn_install = ui_theme.colored_button(
            btn, "Install / Start with Windows", self.install_startup, kind="primary"
        )
        self.btn_install.pack(side=tk.LEFT, padx=6)
        self.btn_uninstall = ui_theme.colored_button(
            btn, "Uninstall / Stop with Windows", self.uninstall_startup, kind="danger"
        )
        self.btn_uninstall.pack(side=tk.LEFT, padx=6)
        ui_theme.colored_button(btn, "Help", self.show_help, kind="ghost").pack(side=tk.LEFT, padx=6)
        ui_theme.colored_button(btn, "Minimize to tray", self.hide_to_tray, kind="ghost").pack(
            side=tk.RIGHT
        )
        self.after(300, self._refresh_install_buttons)

        self.status = tk.StringVar(value="Ready.")
        self.status_lbl = tk.Label(
            footer,
            textvariable=self.status,
            bg=ui_theme.BG,
            fg=ui_theme.NAVY,
            font=ui_theme.FONT_UI_BOLD,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=900,
        )
        self.status_lbl.grid(row=1, column=0, sticky="ew", pady=2)

        self.log = tk.Text(footer, height=6, wrap=tk.WORD)
        ui_theme.style_log_text(self.log)
        self.log.grid(row=2, column=0, sticky="ew", pady=(2, 0))

        # Stubs used by older helpers
        self._canvas = None
        self._vscroll = None
        self._content = form

    def _apply_app_icon(self) -> None:
        """Set window icon from Peak Energy logo (PNG + ICO)."""
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
        if png is None:
            return
        try:
            from PIL import Image, ImageTk

            img = Image.open(png).convert("RGBA")
            # Keep a mid-size photo for title bar / taskbar on some Windows themes
            img.thumbnail((64, 64))
            self._logo_photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._logo_photo)
        except Exception:
            pass

    def _load_tray_image(self) -> Any:
        """Load Peak Energy logo for system tray (fallback to simple mark)."""
        from PIL import Image, ImageDraw

        png = logo_png_path()
        if png is not None:
            try:
                img = Image.open(png).convert("RGBA")
                # Square canvas so tray icon stays crisp
                size = 64
                canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                img.thumbnail((size, size))
                x = (size - img.width) // 2
                y = (size - img.height) // 2
                canvas.paste(img, (x, y), img)
                return canvas
            except Exception:
                pass
        img = Image.new("RGB", (64, 64), color=(20, 90, 160))
        draw = ImageDraw.Draw(img)
        draw.rectangle((12, 12, 52, 52), fill=(240, 240, 240))
        draw.text((22, 20), "P", fill=(20, 90, 160))
        return img

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
        ui_theme.apply_theme(win)

        header, win._header_photo = ui_theme.build_header(  # type: ignore[attr-defined]
            win, "Help", "Peak Attendance guide"
        )
        header.pack(fill=tk.X)

        frame = ttk.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = tk.Text(frame, wrap=tk.WORD)
        ui_theme.style_log_text(text)
        text.configure(font=("Segoe UI", 10), background=ui_theme.BG_PANEL, foreground=ui_theme.FG)
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

        ui_theme.colored_button(bar, "Open full guide", open_guide, kind="accent").pack(side=tk.LEFT)
        ui_theme.colored_button(bar, "Close", win.destroy, kind="ghost").pack(side=tk.RIGHT)
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

    def _on_https_toggle(self, key: str) -> None:
        """When HTTPS is toggled, switch Port 80↔443 if still on the other default."""
        vars_ = self.device_vars.get(key)
        if not vars_:
            return
        try:
            cur = int(vars_["port"].get() or 80)
        except ValueError:
            cur = 80
        if vars_["https"].get():
            if cur == 80:
                vars_["port"].set("443")
        else:
            if cur == 443:
                vars_["port"].set("80")

    def open_device(self, key: str) -> None:
        """Open device web UI and show login helper (browsers do not autofill Hikvision forms)."""
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
        use_https = bool(vars_["https"].get())
        try:
            port = int(vars_["port"].get() or (443 if use_https else 80))
        except ValueError:
            port = 443 if use_https else 80
        if use_https and port == 80:
            port = 443
            vars_["port"].set("443")
        if (not use_https) and port == 443:
            port = 80
            vars_["port"].set("80")
        scheme = "https" if use_https else "http"
        default_port = 443 if use_https else 80
        host = ip if port == default_port else f"{ip}:{port}"
        # Plain URL — Edge/Chrome strip user:pass@ and Hikvision uses a login form anyway.
        page_url = f"{scheme}://{host}/"
        try:
            webbrowser.open(page_url)
        except Exception as exc:
            messagebox.showerror("Open device", f"Could not open browser:\n{exc}")
            return
        self._show_device_login_helper(vars_["name"].get().strip() or key, page_url, user, password)
        self.set_status(f"Opened {page_url} — use the login helper to copy username/password.")

    def _show_device_login_helper(self, label: str, page_url: str, user: str, password: str) -> None:
        """Popup with copyable credentials (browsers will not autofill the device form)."""
        win = tk.Toplevel(self)
        win.title(f"Login — {label}")
        win.geometry("420x260")
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(
            frame,
            text="Browser opened the device page.\n"
            "Chrome/Edge do not autofill Hikvision login forms —\n"
            "copy and paste from here:",
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))

        ttk.Label(frame, text="Page").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(frame, text=page_url).grid(row=1, column=1, columnspan=2, sticky=tk.W, pady=2)

        user_var = tk.StringVar(value=user)
        pass_var = tk.StringVar(value=password)
        show_pw = tk.BooleanVar(value=False)

        ttk.Label(frame, text="Username").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=user_var, width=28).grid(row=2, column=1, sticky=tk.EW, pady=2)
        ttk.Button(
            frame,
            text="Copy",
            width=8,
            command=lambda: self._copy_text(user_var.get(), "Username copied."),
        ).grid(row=2, column=2, padx=(6, 0), pady=2)

        ttk.Label(frame, text="Password").grid(row=3, column=0, sticky=tk.W, pady=2)
        pass_entry = ttk.Entry(frame, textvariable=pass_var, width=28, show="*")
        pass_entry.grid(row=3, column=1, sticky=tk.EW, pady=2)

        def toggle_pw() -> None:
            show_pw.set(not show_pw.get())
            pass_entry.configure(show="" if show_pw.get() else "*")

        pw_btns = ttk.Frame(frame)
        pw_btns.grid(row=3, column=2, padx=(6, 0), pady=2)
        ttk.Button(
            pw_btns,
            text="Copy",
            width=8,
            command=lambda: self._copy_text(pass_var.get(), "Password copied."),
        ).pack(side=tk.TOP)
        ttk.Button(pw_btns, text="Show", width=8, command=toggle_pw).pack(side=tk.TOP, pady=(4, 0))

        note = ttk.Label(frame, text="Password is also on the clipboard now.")
        note.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(12, 0))

        ttk.Button(frame, text="Close", command=win.destroy).grid(
            row=5, column=0, columnspan=3, sticky=tk.E, pady=(16, 0)
        )

        try:
            self.clipboard_clear()
            self.clipboard_append(password)
        except tk.TclError:
            pass
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_force()

    def _copy_text(self, text: str, status: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.set_status(status)
        except tk.TclError as exc:
            messagebox.showerror("Copy", f"Could not copy to clipboard:\n{exc}")

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

    def open_employees(self) -> None:
        """Open employee management (SQL master + Entry/Exit sync)."""
        try:
            if not self.save_all(quiet=True):
                return
            from employees_ui import EmployeesWindow

            EmployeesWindow(self, APPSETTINGS)
        except Exception as exc:
            messagebox.showerror("Employees", str(exc))

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
            self.btn_install.configure(state=tk.DISABLED)
            self.btn_uninstall.configure(state=tk.NORMAL)
        else:
            self.btn_install.configure(state=tk.NORMAL)
            self.btn_uninstall.configure(state=tk.DISABLED)

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

        img = self._load_tray_image()

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
