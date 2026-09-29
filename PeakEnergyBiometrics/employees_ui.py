#!/usr/bin/env python3
"""Employees management window for Peak Energy Biometrics."""

from __future__ import annotations

import io
import threading
import tkinter as tk
from datetime import date, datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import employees as emp
import collector as col
import theme as ui_theme
from paths import logo_ico_path, logo_png_path
from tkcalendar import DateEntry

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover
    Image = None  # type: ignore
    ImageTk = None  # type: ignore

DEFAULT_FROM = date(2020, 1, 1)
DEFAULT_TO = date(2037, 12, 31)


def _as_date(value: Any, fallback: date) -> date:
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _fmt_dt(value: Any) -> str:
    """Format SQL UTC timestamps in the user's local timezone."""
    if not value:
        return "—"
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")[:26])
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return text[:19].replace("T", " ")


class EmployeesWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, appsettings: Path) -> None:
        super().__init__(master)
        self.title("Peak Energy Biometrics — Employees")
        self.geometry("980x640")
        self.appsettings = appsettings
        self.face_bytes: bytes | None = None
        self.photo_img = None
        self._logo_photo = None
        self._apply_window_icon()
        self._build()
        self.after(100, self.reload_list)

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

    def _cfg(self) -> dict[str, Any]:
        return col.load_runtime_config(self.appsettings)

    def _sql(self) -> dict[str, Any]:
        return col.load_json(self.appsettings)["sql"]

    def _build(self) -> None:
        ui_theme.apply_theme(self)
        outer = tk.Frame(self, bg=ui_theme.BG)
        outer.pack(fill=tk.BOTH, expand=True)

        header, self._header_photo = ui_theme.build_header(
            outer,
            "Employees",
            "SQL master · sync to Entry & Exit readers",
        )
        header.pack(fill=tk.X)

        root = ttk.Frame(outer, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        root.columnconfigure(0, weight=2)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(1, weight=1)

        toolbar = tk.Frame(root, bg=ui_theme.BG)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ui_theme.colored_button(toolbar, "Pull from devices", self.pull, kind="accent").pack(side=tk.LEFT)
        ui_theme.colored_button(toolbar, "Refresh", self.reload_list, kind="ghost").pack(
            side=tk.LEFT, padx=6
        )
        ui_theme.colored_button(toolbar, "New", self.new_employee, kind="ghost").pack(side=tk.LEFT, padx=6)
        ui_theme.colored_button(
            toolbar, "Save + Push to devices", self.save_push, kind="primary"
        ).pack(side=tk.LEFT, padx=6)
        ui_theme.colored_button(
            toolbar, "Delete on devices + SQL", self.delete_emp, kind="danger"
        ).pack(side=tk.LEFT, padx=6)

        # List
        list_f = ttk.LabelFrame(root, text="Employees", padding=6)
        list_f.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        list_f.rowconfigure(0, weight=1)
        list_f.columnconfigure(0, weight=1)

        cols = ("EmployeeNo", "Name", "HasFace", "Entry", "Exit", "Updated")
        self._col_labels = {
            "EmployeeNo": "EmployeeNo",
            "Name": "Name",
            "HasFace": "HasFace",
            "Entry": "Entry",
            "Exit": "Exit",
            "Updated": "Updated (local)",
        }
        self._sort_col: str | None = "EmployeeNo"
        self._sort_reverse = False
        self.tree = ttk.Treeview(list_f, columns=cols, show="headings", selectmode="browse")
        for c, w in (
            ("EmployeeNo", 90),
            ("Name", 160),
            ("HasFace", 60),
            ("Entry", 70),
            ("Exit", 70),
            ("Updated", 140),
        ):
            self.tree.heading(
                c,
                text=self._col_labels[c],
                command=lambda col=c: self.sort_by_column(col),
            )
            self.tree.column(c, width=w, anchor=tk.W)
        scroll = ttk.Scrollbar(list_f, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self._refresh_sort_headings()

        # Detail
        detail = ttk.LabelFrame(root, text="Details", padding=8)
        detail.grid(row=1, column=1, sticky="nsew")
        self.var_no = tk.StringVar()
        self.var_first = tk.StringVar()
        self.var_last = tk.StringVar()
        self.var_gender = tk.StringVar()
        self.var_type = tk.StringVar(value="normal")
        self.var_card = tk.StringVar()
        self.var_enabled = tk.BooleanVar(value=True)
        self.var_notes = tk.StringVar()

        def row(r: int, label: str, widget: tk.Misc) -> None:
            ttk.Label(detail, text=label, width=14).grid(row=r, column=0, sticky=tk.W, pady=2)
            widget.grid(row=r, column=1, sticky=tk.EW, pady=2)

        detail.columnconfigure(1, weight=1)
        row(0, "Employee No", ttk.Entry(detail, textvariable=self.var_no))
        row(1, "First name", ttk.Entry(detail, textvariable=self.var_first))
        row(2, "Last name", ttk.Entry(detail, textvariable=self.var_last))
        row(
            3,
            "Gender",
            ttk.Combobox(detail, textvariable=self.var_gender, values=["", "male", "female"], width=16),
        )
        row(
            4,
            "User type",
            ttk.Combobox(detail, textvariable=self.var_type, values=["normal", "visitor"], width=16),
        )
        row(5, "Card No", ttk.Entry(detail, textvariable=self.var_card))
        ui_theme.colored_checkbutton(detail, "Access enabled", self.var_enabled).grid(
            row=6, column=0, columnspan=2, sticky=tk.W, pady=2
        )
        self.date_from = DateEntry(
            detail,
            width=14,
            date_pattern="yyyy-mm-dd",
            year=DEFAULT_FROM.year,
            month=DEFAULT_FROM.month,
            day=DEFAULT_FROM.day,
            background=ui_theme.NAVY,
            foreground="white",
            headersbackground=ui_theme.NAVY,
            headersforeground="white",
            selectbackground=ui_theme.CYAN,
            selectforeground=ui_theme.NAVY_DARK,
        )
        self.date_to = DateEntry(
            detail,
            width=14,
            date_pattern="yyyy-mm-dd",
            year=DEFAULT_TO.year,
            month=DEFAULT_TO.month,
            day=DEFAULT_TO.day,
            background=ui_theme.NAVY,
            foreground="white",
            headersbackground=ui_theme.NAVY,
            headersforeground="white",
            selectbackground=ui_theme.CYAN,
            selectforeground=ui_theme.NAVY_DARK,
        )
        row(7, "Valid from", self.date_from)
        row(8, "Valid to", self.date_to)
        row(9, "Notes", ttk.Entry(detail, textvariable=self.var_notes))

        photo_f = ttk.Frame(detail)
        photo_f.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.photo_lbl = ttk.Label(photo_f, text="No photo")
        self.photo_lbl.pack(side=tk.TOP)
        bf = ttk.Frame(photo_f)
        bf.pack(side=tk.TOP, pady=4)
        ui_theme.colored_button(bf, "Load photo…", self.load_photo, kind="accent").pack(side=tk.LEFT)
        ui_theme.colored_button(bf, "Clear photo", self.clear_photo, kind="ghost").pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(
            photo_f,
            text=emp.FACE_LIMITS_HINT,
            wraplength=320,
            style="Muted.TLabel",
        ).pack(side=tk.TOP, pady=(2, 0))

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(root, textvariable=self.status, style="Status.TLabel", wraplength=900).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

    def set_status(self, text: str) -> None:
        self.status.set(text)

    def _refresh_sort_headings(self) -> None:
        for col, label in self._col_labels.items():
            mark = ""
            if col == self._sort_col:
                mark = " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(
                col,
                text=f"{label}{mark}",
                command=lambda c=col: self.sort_by_column(c),
            )

    def _sort_key(self, col: str, value: str) -> tuple[Any, ...]:
        text = (value or "").strip()
        if col == "EmployeeNo":
            try:
                return (0, int(text))
            except ValueError:
                return (1, text.casefold())
        if col == "HasFace":
            return (0 if text.lower() == "yes" else 1, text.casefold())
        return (0, text.casefold())

    def sort_by_column(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        rows = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children("")]
        rows.sort(key=lambda item: self._sort_key(col, item[0]), reverse=self._sort_reverse)
        for index, (_val, iid) in enumerate(rows):
            self.tree.move(iid, "", index)
        self._refresh_sort_headings()

    def reload_list(self) -> None:
        try:
            sql = self._sql()
            conn = col.connect_sql(sql)
            try:
                emp.ensure_employee_tables(conn.cursor())
                conn.commit()
            finally:
                conn.close()
            rows = emp.list_employees(sql)
            for i in self.tree.get_children():
                self.tree.delete(i)
            for r in rows:
                sync = r.get("Sync") or {}
                entry = (sync.get("entry") or {}).get("Status") or "—"
                exit_s = (sync.get("exit") or {}).get("Status") or "—"
                self.tree.insert(
                    "",
                    tk.END,
                    iid=str(r["EmployeeNo"]),
                    values=(
                        r["EmployeeNo"],
                        r["Name"],
                        "Yes" if r.get("HasFace") else "No",
                        entry,
                        exit_s,
                        _fmt_dt(r.get("UpdatedAt")),
                    ),
                )
            if self._sort_col:
                # Re-apply current sort without flipping direction
                reverse = self._sort_reverse
                sort_col = self._sort_col
                items = [
                    (self.tree.set(iid, sort_col), iid) for iid in self.tree.get_children("")
                ]
                items.sort(
                    key=lambda item: self._sort_key(sort_col, item[0]), reverse=reverse
                )
                for index, (_val, iid) in enumerate(items):
                    self.tree.move(iid, "", index)
                self._refresh_sort_headings()
            self.set_status(f"Loaded {len(rows)} employee(s).")
        except Exception as exc:
            self.set_status(f"Load failed: {exc}")
            messagebox.showerror("Employees", str(exc), parent=self)

    def on_select(self, _event: Any = None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        employee_no = sel[0]
        try:
            row = emp.get_employee(self._sql(), employee_no)
            if not row:
                return
            self.var_no.set(row["EmployeeNo"])
            first = (row.get("FirstName") or "").strip()
            last = (row.get("LastName") or "").strip()
            if not first and not last:
                first, last = emp.split_person_name(row.get("Name") or "")
            self.var_first.set(first)
            self.var_last.set(last)
            self.var_gender.set(row.get("Gender") or "")
            self.var_type.set(row.get("UserType") or "normal")
            self.var_card.set(row.get("CardNo") or "")
            user_type = str(row.get("UserType") or "").strip().lower()
            access_on = bool(row.get("ValidEnabled", True)) and user_type not in {
                "blacklist",
                "black_list",
                "black-list",
            }
            self.var_enabled.set(access_on)
            self.date_from.set_date(_as_date(row.get("ValidFrom"), DEFAULT_FROM))
            self.date_to.set_date(_as_date(row.get("ValidTo"), DEFAULT_TO))
            self.var_notes.set(row.get("Notes") or "")
            face = row.get("FaceImage")
            self.face_bytes = bytes(face) if face else None
            self._show_photo(self.face_bytes)
        except Exception as exc:
            messagebox.showerror("Employees", str(exc), parent=self)

    def new_employee(self) -> None:
        self.tree.selection_remove(self.tree.selection())
        self.var_no.set("")
        self.var_first.set("")
        self.var_last.set("")
        self.var_gender.set("")
        self.var_type.set("normal")
        self.var_card.set("")
        self.var_enabled.set(True)
        self.date_from.set_date(DEFAULT_FROM)
        self.date_to.set_date(DEFAULT_TO)
        self.var_notes.set("")
        self.face_bytes = None
        self._show_photo(None)
        self.set_status("New employee — fill fields, then Save + Push.")

    def load_photo(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select face photo (JPEG preferred)",
            filetypes=[
                ("JPEG", "*.jpg;*.jpeg"),
                ("Images", "*.jpg;*.jpeg;*.png;*.bmp;*.webp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            raw_kb = len(raw) / 1024.0
            if raw_kb > emp.FACE_MAX_BYTES / 1024:
                # Inform before auto-compress so the limit is visible.
                if not messagebox.askokcancel(
                    "Photo size",
                    f"Selected file is {raw_kb:.0f} KB.\n"
                    f"Maximum for Hikvision face enroll is {emp.FACE_MAX_BYTES // 1024} KB.\n\n"
                    "Auto-resize/compress to fit?",
                    parent=self,
                ):
                    return
            jpeg, summary, soft = emp.prepare_face_photo(raw)
        except emp.FacePhotoError as exc:
            messagebox.showerror("Photo rejected", str(exc), parent=self)
            self.set_status(f"Photo rejected: {exc}")
            return
        except Exception as exc:
            messagebox.showerror("Photo", str(exc), parent=self)
            return

        if soft:
            warn = "\n".join(f"• {w}" for w in soft)
            if not messagebox.askokcancel(
                "Photo warning",
                f"{warn}\n\nContinue with this photo?",
                parent=self,
            ):
                return

        self.face_bytes = jpeg
        self._show_photo(jpeg)
        self.set_status(f"Photo loaded — {summary}")
        if "compressed" in summary.lower() or "resized" in summary.lower():
            messagebox.showinfo(
                "Photo optimized",
                f"{summary}\n\nLimits: JPEG, max {emp.FACE_MAX_BYTES // 1024} KB, "
                f"recommended ≥ {emp.FACE_REC_W}×{emp.FACE_REC_H}.",
                parent=self,
            )

    def clear_photo(self) -> None:
        self.face_bytes = b""
        self._show_photo(None)

    def _show_photo(self, data: bytes | None) -> None:
        if not data or Image is None or ImageTk is None:
            self.photo_img = None
            self.photo_lbl.configure(image="", text="No photo")
            return
        try:
            img = Image.open(io.BytesIO(data))
            img.thumbnail((160, 160))
            self.photo_img = ImageTk.PhotoImage(img)
            self.photo_lbl.configure(image=self.photo_img, text="")
        except Exception:
            self.photo_img = None
            self.photo_lbl.configure(image="", text="(invalid image)")

    def _form_emp(self) -> dict[str, Any]:
        no = self.var_no.get().strip()
        first = self.var_first.get().strip()
        last = self.var_last.get().strip()
        name = emp.combine_person_name(first, last)
        if not no:
            raise ValueError("Employee No is required.")
        if not name:
            raise ValueError("First name or Last name is required.")
        d_from = self.date_from.get_date()
        d_to = self.date_to.get_date()
        if d_to < d_from:
            raise ValueError("Valid to must be on or after Valid from.")
        enabled = bool(self.var_enabled.get())
        user_type = self.var_type.get().strip() or "normal"
        # Re-enabling access clears Hikvision blacklist type
        if enabled and user_type.lower() in {"blacklist", "black_list", "black-list"}:
            user_type = "normal"
            self.var_type.set(user_type)
        return {
            "EmployeeNo": no,
            "Name": name,
            "FirstName": first or None,
            "LastName": last or None,
            "Gender": self.var_gender.get().strip() or None,
            "UserType": user_type,
            "CardNo": self.var_card.get().strip() or None,
            "ValidEnabled": enabled,
            "ValidFrom": datetime.combine(d_from, datetime.min.time()),
            "ValidTo": datetime.combine(d_to, datetime.max.time().replace(microsecond=0)),
            "Notes": self.var_notes.get().strip() or None,
            "HasFace": bool(self.face_bytes),
        }

    def pull(self) -> None:
        if not messagebox.askyesno(
            "Pull from devices",
            "Pull employees from Entry and Exit, merge by Employee No into SQL?\n\n"
            "Existing SQL rows with the same Employee No are updated.",
            parent=self,
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Pulling from devices…"))
                result = emp.pull_from_devices(self._cfg())
                err = result.get("errors") or []
                count = int(result.get("count") or 0)
                faces = int(result.get("faces") or 0)
                if count == 0 and err:
                    msg = (
                        "Could not pull employees from the door readers.\n\n"
                        + "\n\n".join(err)
                        + "\n\nCheck VPN/LAN, device power, and IP addresses in the main window."
                    )
                    self.after(0, lambda: self.set_status("Pull failed — devices unreachable."))
                    self.after(0, self.reload_list)
                    self.after(0, lambda: messagebox.showerror("Pull failed", msg, parent=self))
                    return
                msg = f"Pulled {count} employee(s), {faces} face photo(s)."
                if err:
                    msg += "\n\nSome devices had issues:\n\n" + "\n\n".join(err)
                    title = "Pull complete (with warnings)"
                else:
                    title = "Pull complete"
                self.after(0, lambda: self.set_status(msg.split("\n", 1)[0]))
                self.after(0, self.reload_list)
                self.after(0, lambda: messagebox.showinfo(title, msg, parent=self))
            except Exception as exc:
                _c, detail = col.classify_device_error(exc)
                self.after(0, lambda: self.set_status(f"Pull failed: {detail}"))
                self.after(0, lambda: messagebox.showerror("Pull failed", detail, parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def save_push(self) -> None:
        try:
            data = self._form_emp()
        except ValueError as exc:
            messagebox.showerror("Save", str(exc), parent=self)
            return
        face = self.face_bytes
        if face == b"":
            face = b""  # explicit clear — save_employee treats empty as clear if we pass it
        elif face:
            try:
                face, _summary, soft = emp.prepare_face_photo(face)
                self.face_bytes = face
                if soft:
                    warn = "\n".join(f"• {w}" for w in soft)
                    if not messagebox.askokcancel(
                        "Photo warning",
                        f"{warn}\n\nContinue Save + Push?",
                        parent=self,
                    ):
                        return
            except emp.FacePhotoError as exc:
                messagebox.showerror("Photo rejected", str(exc), parent=self)
                return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status("Saving + pushing to devices…"))
                # empty bytes means clear face; None means leave existing
                face_arg: bytes | None
                if face == b"":
                    face_arg = b""
                else:
                    face_arg = face
                notes = emp.create_or_update_employee(self._cfg(), data, face=face_arg, push=True)
                text = "\n".join(notes)
                self.after(0, lambda: self.set_status("Saved + pushed."))
                self.after(0, self.reload_list)
                self.after(0, lambda: messagebox.showinfo("Save + Push", text, parent=self))
            except Exception as exc:
                self.after(0, lambda: self.set_status(f"Save failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Save failed", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()

    def delete_emp(self) -> None:
        no = self.var_no.get().strip()
        if not no:
            messagebox.showerror("Delete", "Select an employee first.", parent=self)
            return
        if not messagebox.askyesno(
            "Delete",
            f"Delete employee {no} from Entry, Exit, and SQL?\n\nThis cannot be undone.",
            parent=self,
        ):
            return

        def worker() -> None:
            try:
                self.after(0, lambda: self.set_status(f"Deleting {no}…"))
                notes = emp.delete_employee_everywhere(self._cfg(), no)
                text = "\n".join(notes)
                self.after(0, self.new_employee)
                self.after(0, self.reload_list)
                self.after(0, lambda: self.set_status("Deleted."))
                self.after(0, lambda: messagebox.showinfo("Delete", text, parent=self))
            except Exception as exc:
                self.after(0, lambda: self.set_status(f"Delete failed: {exc}"))
                self.after(0, lambda: messagebox.showerror("Delete failed", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()
