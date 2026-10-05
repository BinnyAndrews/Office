#!/usr/bin/env python3
"""Peak Energy Dashboard — SQL server config, Punches, Dashboard, tray."""

from __future__ import annotations

import ctypes
import socket
import subprocess
import sys
import threading
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
APP_TITLE = "Peak Energy Dashboard"
SHORTCUT_LABEL = "Peak Energy Dashboard"
STARTUP_TASK = "Peak-Energy-Dashboard-UI"

SQL_DEFAULT_DATABASE = "master"
SQL_DEFAULT_PUNCH_TABLE = "atteninfo"
SQL_DEFAULT_USERNAME = "sa"
SQL_DEFAULT_PASSWORD = "cctv@2025"
SQL_DEFAULT_DRIVER = "ODBC Driver 18 for SQL Server"

SINGLETON_HOST = "127.0.0.1"
SINGLETON_PORT = 58742
MUTEX_NAME = "Local\\PeakEnergyDashboardUI_SingleInstance"
ERROR_ALREADY_EXISTS = 183

HELP_TEXT = """Peak Energy Dashboard — Help

WHAT THIS APP IS
  A lightweight viewer for punch data already in SQL Server.
  It does NOT connect to Entry/Exit readers, does NOT run the punch
  collector, and does NOT manage employees.

CONFIGURATION
  • Server — SQL Server host only (editable).
    Examples: localhost, localhost\\SQLEXPRESS, 10.80.100.10,1433
  • Database, punch table, username, and password are fixed:
    master · dbo.atteninfo · sa (defaults used from appsettings.json).
  • Save configuration — writes Server to appsettings.json next to this exe
    and checks that SQL is reachable.
  • Reload — reload appsettings.json from disk.

PUNCHES
  Browse raw punches in atteninfo for a selected day (last 2 years).

DASHBOARD
  Monthly summary and daily detail: worked hours and break time per person.
  Names come from dbo.Employees when present; otherwise from punch rows.

WINDOWS STARTUP
  Install / Start with Windows — logon shortcut + scheduled task for this
  dashboard app only (no collector task).
  Uninstall / Stop with Windows — removes dashboard startup only.

TRAY
  Close window → minimizes to tray (does not quit).
  Quit — tray icon → Quit.
  Command line: add --window to open the main window immediately.

TROUBLESHOOTING
  SQL unreachable — check Server, firewall, SQL running, Mixed Mode.
  Empty Dashboard/Punches — confirm the ACS collector PC is writing atteninfo.
  ODBC Driver 18 for SQL Server must be installed on this PC.
"""


def notify_existing_instance(command: str = "SHOW") -> bool:
    try:
        with socket.create_connection((SINGLETON_HOST, SINGLETON_PORT), timeout=0.4) as sock:
            sock.sendall((command + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def acquire_mutex() -> Any | None:
    if sys.platform != "win32":
        return object()
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def open_ipc_server() -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((SINGLETON_HOST, SINGLETON_PORT))
        sock.listen(1)
        sock.settimeout(0.5)
        return sock
    except OSError:
        sock.close()
        return None


def _default_appsettings() -> dict[str, Any]:
    return {
        "sql": {
            "server": "localhost\\SQLEXPRESS",
            "database": SQL_DEFAULT_DATABASE,
            "punch_table": SQL_DEFAULT_PUNCH_TABLE,
            "username": SQL_DEFAULT_USERNAME,
            "password": SQL_DEFAULT_PASSWORD,
            "driver": SQL_DEFAULT_DRIVER,
        },
    }


def _normalize_sql_block(raw: dict[str, Any] | None) -> dict[str, Any]:
    sql = dict(raw or {})
    sql["database"] = SQL_DEFAULT_DATABASE
    sql["punch_table"] = SQL_DEFAULT_PUNCH_TABLE
    if not str(sql.get("username") or "").strip():
        sql["username"] = SQL_DEFAULT_USERNAME
    pw = str(sql.get("password") or "").strip()
    if not pw or pw.lower() in {"change_me", "changeme"}:
        sql["password"] = SQL_DEFAULT_PASSWORD
    if not str(sql.get("driver") or "").strip():
        sql["driver"] = SQL_DEFAULT_DRIVER
    return sql


class DashboardApp(tk.Tk):
    def __init__(
        self,
        start_in_tray: bool = True,
        singleton_sock: socket.socket | None = None,
        mutex_handle: Any | None = None,
    ) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(520, 380)
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
            self.after(50, self._boot_to_tray)
        else:
            self.after(30, self._fit_to_screen)
        self.after(80, self.reload_all)

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
            self.after(50, self._fit_to_screen)
            messagebox.showwarning(
                "Tray unavailable",
                f"Could not start in tray ({exc}). Showing window instead.\n"
                "Install: pip install pystray pillow",
            )

    def _build(self) -> None:
        outer = tk.Frame(self, bg=ui_theme.BG)
        outer.pack(fill=tk.BOTH, expand=True)

        header, self._header_photo = ui_theme.build_header(
            outer,
            APP_TITLE,
            "SQL punch data · Hours, breaks & punch browse",
        )
        header.pack(fill=tk.X)

        root = ttk.Frame(outer, padding=10)
        root.pack(fill=tk.BOTH, expand=True)

        sql_f = ttk.LabelFrame(root, text="SQL Server", padding=8)
        sql_f.pack(fill=tk.X, pady=(0, 8))
        sql_f.columnconfigure(1, weight=1)

        self.sql_server = tk.StringVar()
        ttk.Label(sql_f, text="Server", width=14).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(sql_f, textvariable=self.sql_server).grid(row=0, column=1, sticky=tk.EW, pady=2)

        ttk.Label(
            sql_f,
            text=(
                "Only the server name is configurable here. "
                f"Database={SQL_DEFAULT_DATABASE}, table={SQL_DEFAULT_PUNCH_TABLE}, "
                f"login={SQL_DEFAULT_USERNAME} (from appsettings.json). "
                "Use localhost or localhost\\SQLEXPRESS on the ACS PC; "
                "remote PCs: 10.80.100.10,1433."
            ),
            style="Muted.TLabel",
            wraplength=480,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))

        footer = tk.Frame(root, bg=ui_theme.BG, padx=4, pady=6)
        footer.pack(fill=tk.X)

        btns = tk.Frame(footer, bg=ui_theme.BG)
        btns.pack(fill=tk.X, pady=(4, 2))
        for col in range(4):
            btns.columnconfigure(col, weight=1, uniform="dash_btns")
        pad = {"padx": (0, 6), "pady": 2, "sticky": "ew"}

        def put(row: int, col: int, text: str, command: Any, kind: str = "ghost") -> tk.Button:
            btn = ui_theme.colored_button(btns, text, command, kind=kind)
            btn.grid(row=row, column=col, **pad)
            return btn

        put(0, 0, "Save configuration", self.save_all, "accent")
        put(0, 1, "Reload", self.reload_all, "ghost")
        self.btn_install = put(0, 2, "Install / Start with Windows", self.install_startup, "accent")
        self.btn_uninstall = put(0, 3, "Uninstall / Stop with Windows", self.uninstall_startup, "ghost")
        put(1, 0, "Punches", self.open_punches, "accent")
        put(1, 1, "Dashboard", self.open_dashboard, "accent")
        put(1, 2, "Minimize to tray", self.hide_to_tray, "ghost")
        put(1, 3, "Help", self.show_help, "ghost")

        self.after(400, self._refresh_install_buttons)

        self.status = tk.StringVar(value="Ready.")
        tk.Label(
            footer,
            textvariable=self.status,
            bg=ui_theme.BG,
            fg=ui_theme.NAVY,
            font=ui_theme.FONT_UI_BOLD,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(fill=tk.X, pady=(8, 0))

    def _apply_app_icon(self) -> None:
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
            img.thumbnail((64, 64))
            self._logo_photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._logo_photo)
        except Exception:
            pass

    def _load_tray_image(self) -> Any:
        from PIL import Image, ImageDraw

        png = logo_png_path()
        if png is not None:
            try:
                img = Image.open(png).convert("RGBA")
                img.thumbnail((64, 64))
                return img
            except Exception:
                pass
        img = Image.new("RGBA", (64, 64), (0, 40, 85, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((8, 8, 56, 56), fill=(0, 180, 220, 255))
        return img

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def _fit_to_screen(self) -> None:
        self.update_idletasks()
        w = min(max(self.winfo_reqwidth(), 520), self.winfo_screenwidth() - 40)
        h = min(max(self.winfo_reqheight(), 380), self.winfo_screenheight() - 80)
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _ensure_appsettings(self) -> dict[str, Any]:
        if not APPSETTINGS.exists():
            example = BUNDLE / "appsettings.example.json"
            if not example.exists():
                example = ROOT / "appsettings.example.json"
            if example.exists():
                APPSETTINGS.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                col.save_json(APPSETTINGS, _default_appsettings())
        boot = col.load_json(APPSETTINGS)
        boot["sql"] = _normalize_sql_block(boot.get("sql"))
        return boot

    def reload_all(self) -> None:
        self.set_status("Loading configuration…")

        def worker() -> None:
            err: str | None = None
            server = ""
            try:
                boot = self._ensure_appsettings()
                sql = boot["sql"]
                server = str(sql.get("server") or "").strip()
                col.save_json(APPSETTINGS, boot)
                conn = col.connect_sql(sql, timeout=5)
                conn.close()
            except Exception as exc:
                err = str(exc)
                try:
                    boot = col.load_json(APPSETTINGS)
                    server = str((boot.get("sql") or {}).get("server") or "").strip()
                except Exception:
                    server = ""

            def apply() -> None:
                self.sql_server.set(server)
                if err:
                    self.set_status(f"Loaded server; SQL test failed: {err}")
                    messagebox.showwarning(
                        "SQL unreachable",
                        f"Server loaded from appsettings.json but connection failed.\n\n{err}",
                        parent=self,
                    )
                else:
                    self.set_status("Configuration loaded.")
                self._refresh_install_buttons()
                self.after(30, self._fit_to_screen)

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def save_all(self) -> None:
        server = self.sql_server.get().strip()
        if not server:
            messagebox.showerror("Save", "Enter a SQL Server name.", parent=self)
            return

        try:
            boot = self._ensure_appsettings()
            sql = _normalize_sql_block(boot.get("sql"))
            sql["server"] = server
            boot["sql"] = sql
            col.save_json(APPSETTINGS, boot)
            conn = col.connect_sql(sql, timeout=8)
            conn.close()
            self.set_status("Configuration saved.")
            messagebox.showinfo(
                "Saved",
                f"SQL Server set to:\n{server}\n\n"
                f"Connection OK (database {SQL_DEFAULT_DATABASE}, table {SQL_DEFAULT_PUNCH_TABLE}).",
                parent=self,
            )
        except Exception as exc:
            msg = self._friendly_sql_error(exc)
            self.set_status(f"Save failed: {msg}")
            messagebox.showerror("Save failed", msg, parent=self)

    def _friendly_sql_error(self, exc: BaseException) -> str:
        msg = str(exc)
        low = msg.lower()
        if "login failed" in low or "18456" in msg:
            return "SQL login failed — check sa password in appsettings.json on the ACS PC."
        if "08001" in msg or "could not open" in low or "network-related" in low:
            return f"Cannot reach SQL Server — check Server name and firewall.\n\n{msg}"
        if "odbc" in low and "driver" in low:
            return "Install ODBC Driver 18 for SQL Server on this PC."
        return msg

    def open_punches(self) -> None:
        try:
            from punches_ui import PunchesWindow

            PunchesWindow(self, APPSETTINGS)
        except Exception as exc:
            messagebox.showerror("Punches", str(exc), parent=self)

    def open_dashboard(self) -> None:
        try:
            from dashboard_ui import DashboardWindow

            DashboardWindow(self, APPSETTINGS)
        except Exception as exc:
            messagebox.showerror("Dashboard", str(exc), parent=self)

    def show_help(self) -> None:
        win = tk.Toplevel(self)
        win.title(f"{APP_TITLE} — Help")
        win.geometry("640x520")
        win.transient(self)
        text = tk.Text(win, wrap=tk.WORD, padx=10, pady=10)
        ui_theme.style_log_text(text)
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", HELP_TEXT)
        text.configure(state=tk.DISABLED)
        ui_theme.colored_button(win, "Close", win.destroy, kind="ghost").pack(pady=8)
        win.focus_force()

    def _startup_lnk(self) -> Path:
        return (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / f"{SHORTCUT_LABEL}.lnk"
        )

    def _is_startup_installed(self) -> bool:
        if self._startup_lnk().exists():
            return True
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", STARTUP_TASK],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return r.returncode == 0

    def _refresh_install_buttons(self) -> None:
        def worker() -> None:
            try:
                installed = self._is_startup_installed()
            except Exception:
                installed = False

            def apply() -> None:
                if installed:
                    self.btn_install.configure(state=tk.DISABLED)
                    self.btn_uninstall.configure(state=tk.NORMAL)
                else:
                    self.btn_install.configure(state=tk.NORMAL)
                    self.btn_uninstall.configure(state=tk.DISABLED)

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def install_startup(self) -> None:
        if self._is_startup_installed():
            messagebox.showinfo(
                "Already installed",
                f"{SHORTCUT_LABEL} is already registered for Windows startup.",
                parent=self,
            )
            self._refresh_install_buttons()
            return
        if not messagebox.askyesno(
            "Install / Start with Windows",
            f"Register {SHORTCUT_LABEL} to:\n"
            "• Start with Windows at logon (tray)\n"
            "• Create Desktop + Start Menu shortcuts\n\n"
            "This does NOT install the punch collector.\n\n"
            "Continue?",
            parent=self,
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Installing startup…"))
                msg = self._install_frozen() if getattr(sys, "frozen", False) else self._install_dev()
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status("Installed — starts with Windows."))
                self.after(
                    0,
                    lambda: messagebox.showinfo("Install complete", msg, parent=self),
                )
            except Exception as exc:
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status(f"Install failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Install failed", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def uninstall_startup(self) -> None:
        if not self._is_startup_installed():
            messagebox.showinfo(
                "Not installed",
                f"{SHORTCUT_LABEL} is not registered for Windows startup.",
                parent=self,
            )
            self._refresh_install_buttons()
            return
        if not messagebox.askyesno(
            "Uninstall / Stop with Windows",
            f"Remove {SHORTCUT_LABEL} from Windows startup?\n\n"
            "This will NOT delete the exe, appsettings.json, or SQL data.",
            parent=self,
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Removing startup…"))
                msg = self._uninstall_startup()
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: self.set_status("Uninstalled — no longer starts with Windows."))
                self.after(0, lambda: messagebox.showinfo("Uninstall complete", msg, parent=self))
            except Exception as exc:
                self.after(0, self._refresh_install_buttons)
                self.after(0, lambda: messagebox.showerror("Uninstall failed", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def _shortcut_ps(self, path: Path, target: Path, args: str = "") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        icon = str(target)
        ico = target.parent / "PeakEnergyBiometrics.ico"
        if ico.exists():
            icon = str(ico)
        ps = (
            f"$w=New-Object -ComObject WScript.Shell; "
            f"$s=$w.CreateShortcut('{path}'); "
            f"$s.TargetPath='{target}'; "
            f"$s.Arguments='{args}'; "
            f"$s.WorkingDirectory='{target.parent}'; "
            f"$s.Description='{SHORTCUT_LABEL}'; "
            f"$s.IconLocation='{icon}'; "
            f"$s.Save()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            check=False,
            capture_output=True,
            text=True,
        )

    def _install_frozen(self) -> str:
        exe = Path(sys.executable).resolve()
        lines: list[str] = []
        startup = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        menu = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / SHORTCUT_LABEL
        )
        desktop = Path.home() / "Desktop"
        self._shortcut_ps(startup / f"{SHORTCUT_LABEL}.lnk", exe)
        self._shortcut_ps(menu / f"{SHORTCUT_LABEL}.lnk", exe)
        self._shortcut_ps(desktop / f"{SHORTCUT_LABEL}.lnk", exe)
        lines.append("Shortcuts: Startup, Start Menu, Desktop")
        tr = f'"{exe}"'
        r = subprocess.run(
            [
                "schtasks",
                "/Create",
                "/TN",
                STARTUP_TASK,
                "/SC",
                "ONLOGON",
                "/RL",
                "LIMITED",
                "/F",
                "/TR",
                tr,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0:
            lines.append(f"Scheduled task: {STARTUP_TASK}")
        else:
            detail = ((r.stderr or "") + (r.stdout or "")).strip()
            lines.append(f"Task registration note: {detail or 'skipped'}")
        return "\n".join(lines)

    def _install_dev(self) -> str:
        py = Path(sys.executable).resolve()
        script = ROOT / "peak_dashboard.py"
        tr = f'"{py}" "{script}"'
        startup = self._startup_lnk()
        self._shortcut_ps(startup, py, f'"{script}"')
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", STARTUP_TASK, "/SC", "ONLOGON", "/RL", "LIMITED", "/F", "/TR", tr],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        msg = f"Dev mode: startup shortcut + task ({STARTUP_TASK})."
        if r.returncode != 0:
            msg += f"\nTask: {(r.stderr or r.stdout or '').strip()}"
        return msg

    def _uninstall_startup(self) -> str:
        lines: list[str] = []
        r = subprocess.run(
            ["schtasks", "/Delete", "/TN", STARTUP_TASK, "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode == 0:
            lines.append(f"Removed task: {STARTUP_TASK}")
        else:
            lines.append(f"Task not present (ok): {STARTUP_TASK}")

        paths = [
            self._startup_lnk(),
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / SHORTCUT_LABEL
            / f"{SHORTCUT_LABEL}.lnk",
            Path.home() / "Desktop" / f"{SHORTCUT_LABEL}.lnk",
        ]
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
            / SHORTCUT_LABEL
        )
        try:
            if menu_dir.exists() and not any(menu_dir.iterdir()):
                menu_dir.rmdir()
        except OSError:
            pass
        return "\n".join(lines) if lines else "Nothing to remove."

    def hide_to_tray(self) -> None:
        self.withdraw()
        try:
            self._ensure_tray()
        except Exception as exc:
            self.deiconify()
            messagebox.showwarning(
                "Tray unavailable",
                f"Could not create tray icon ({exc}). Window stayed open.",
                parent=self,
            )

    def _ensure_tray(self) -> None:
        if self.tray_icon is not None:
            return
        import pystray

        img = self._load_tray_image()

        def show(_icon: Any = None, _item: Any = None) -> None:
            self.after(0, self._show_from_tray)

        def help_item(_icon: Any = None, _item: Any = None) -> None:
            self.after(0, self._show_from_tray)
            self.after(200, self.show_help)

        def quit_app(_icon: Any = None, _item: Any = None) -> None:
            if self.tray_icon is not None:
                self.tray_icon.stop()
                self.tray_icon = None
            self.after(0, self.destroy)

        menu = pystray.Menu(
            pystray.MenuItem(f"Open {APP_TITLE}", show, default=True),
            pystray.MenuItem("Help", help_item),
            pystray.MenuItem("Quit", quit_app),
        )
        self.tray_icon = pystray.Icon("peak_dashboard", img, APP_TITLE, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
        self.after(50, self._fit_to_screen)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument(
        "--window",
        action="store_true",
        help="Open the main window immediately (default is start in tray)",
    )
    args = parser.parse_args()

    mutex = acquire_mutex()
    if mutex is None:
        notify_existing_instance("SHOW")
        return 0

    sock = open_ipc_server()
    app = DashboardApp(start_in_tray=not args.window, singleton_sock=sock, mutex_handle=mutex)
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
