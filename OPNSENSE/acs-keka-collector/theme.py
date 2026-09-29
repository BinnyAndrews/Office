#!/usr/bin/env python3
"""Peak Energy visual theme for Peak Attendance.

Uses classic tk widgets for colored chrome (header / buttons / checkboxes)
because Windows ttk themes often ignore colors, and clam draws checkboxes as ✕.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

# Brand palette sampled from PeakEnergyLogo.png
NAVY = "#0F4D81"
NAVY_DARK = "#0A3A62"
CYAN = "#49C2E0"
CYAN_HOVER = "#6AD0E8"
CYAN_SOFT = "#B8E6F4"
BG = "#EAF2F8"
BG_PANEL = "#F7FBFD"
BG_INPUT = "#FFFFFF"
FG = "#1A2B3C"
FG_MUTED = "#5A6F82"
BORDER = "#C5D5E4"
SUCCESS = "#1B7A4E"
SUCCESS_HOVER = "#14633F"
DANGER = "#B42318"
DANGER_HOVER = "#8F1A12"
GHOST = "#D9E6F0"
GHOST_HOVER = "#C5D5E4"
LOG_BG = "#0F2438"
LOG_FG = "#D7E8F5"

FONT_UI = ("Segoe UI", 9)
FONT_UI_BOLD = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_SUB = ("Segoe UI", 9)
FONT_SECTION = ("Segoe UI", 10, "bold")


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Force clam theme + Peak colors on a Tk / Toplevel window."""
    try:
        root.configure(bg=BG)
    except tk.TclError:
        pass

    style = ttk.Style(root)
    # vista/xpnative ignore most color options — clam is required on Windows
    for name in ("clam", "alt", "default"):
        try:
            style.theme_use(name)
            break
        except tk.TclError:
            continue

    style.configure(
        ".",
        background=BG,
        foreground=FG,
        fieldbackground=BG_INPUT,
        bordercolor=BORDER,
        lightcolor=BG,
        darkcolor=BORDER,
        troughcolor=CYAN_SOFT,
        focuscolor=CYAN,
        font=FONT_UI,
    )
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG, font=FONT_UI)
    style.configure("Muted.TLabel", background=BG, foreground=FG_MUTED, font=FONT_UI)
    style.configure("Status.TLabel", background=BG, foreground=NAVY, font=FONT_UI_BOLD)

    style.configure(
        "TLabelframe",
        background=BG,
        foreground=NAVY,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=BG,
        foreground=NAVY,
        font=FONT_SECTION,
    )

    style.configure(
        "TEntry",
        fieldbackground=BG_INPUT,
        foreground=FG,
        insertcolor=FG,
        bordercolor=BORDER,
        lightcolor=CYAN_SOFT,
        darkcolor=BORDER,
        padding=4,
    )
    style.map("TEntry", bordercolor=[("focus", CYAN)], lightcolor=[("focus", CYAN)])

    style.configure(
        "TCombobox",
        fieldbackground=BG_INPUT,
        foreground=FG,
        bordercolor=BORDER,
        arrowcolor=NAVY,
        padding=3,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", BG_INPUT)],
        bordercolor=[("focus", CYAN)],
    )

    style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT_UI)
    style.map("TCheckbutton", background=[("active", BG)], foreground=[("disabled", FG_MUTED)])

    for name, bg, fg, active in (
        ("TButton", NAVY, "#FFFFFF", NAVY_DARK),
        ("Primary.TButton", NAVY, "#FFFFFF", NAVY_DARK),
        ("Accent.TButton", CYAN, NAVY_DARK, CYAN_HOVER),
        ("Success.TButton", SUCCESS, "#FFFFFF", SUCCESS_HOVER),
        ("Danger.TButton", DANGER, "#FFFFFF", DANGER_HOVER),
        ("Ghost.TButton", GHOST, NAVY, GHOST_HOVER),
    ):
        style.configure(
            name,
            background=bg,
            foreground=fg,
            bordercolor=bg,
            lightcolor=bg,
            darkcolor=bg,
            focusthickness=1,
            focuscolor=CYAN,
            padding=(10, 5),
            font=FONT_UI_BOLD,
        )
        style.map(
            name,
            background=[("pressed", active), ("active", active), ("disabled", BORDER)],
            foreground=[("disabled", FG_MUTED)],
            bordercolor=[("disabled", BORDER)],
            lightcolor=[("pressed", active), ("active", active)],
            darkcolor=[("pressed", active), ("active", active)],
        )

    style.configure(
        "Treeview",
        background=BG_INPUT,
        fieldbackground=BG_INPUT,
        foreground=FG,
        bordercolor=BORDER,
        rowheight=26,
        font=FONT_UI,
    )
    style.configure(
        "Treeview.Heading",
        background=NAVY,
        foreground="#FFFFFF",
        relief="flat",
        font=FONT_UI_BOLD,
    )
    style.map(
        "Treeview",
        background=[("selected", NAVY)],
        foreground=[("selected", "#FFFFFF")],
    )
    style.map("Treeview.Heading", background=[("active", NAVY_DARK)])

    style.configure(
        "Vertical.TScrollbar",
        background=CYAN_SOFT,
        troughcolor=BG,
        bordercolor=BORDER,
        arrowcolor=NAVY,
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=CYAN_SOFT,
        troughcolor=BG,
        bordercolor=BORDER,
        arrowcolor=NAVY,
    )

    return style


def colored_checkbutton(
    parent: tk.Misc,
    text: str,
    variable: tk.Variable,
    **kwargs: Any,
) -> tk.Checkbutton:
    """Classic tk checkbox — shows a real ✓ on Windows (clam ttk uses ✕)."""
    onvalue = kwargs.pop("onvalue", True)
    offvalue = kwargs.pop("offvalue", False)
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        onvalue=onvalue,
        offvalue=offvalue,
        bg=BG,
        fg=FG,
        activebackground=BG,
        activeforeground=FG,
        selectcolor=BG_INPUT,
        highlightthickness=0,
        bd=0,
        font=FONT_UI,
        cursor="hand2",
        **kwargs,
    )


def colored_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], Any] | None = None,
    *,
    kind: str = "primary",
    padx: int = 12,
    pady: int = 5,
) -> tk.Button:
    """Classic tk.Button with guaranteed brand colors on Windows."""
    colors = {
        "primary": (NAVY, "#FFFFFF", NAVY_DARK),
        "accent": (CYAN, NAVY_DARK, CYAN_HOVER),
        "success": (SUCCESS, "#FFFFFF", SUCCESS_HOVER),
        "danger": (DANGER, "#FFFFFF", DANGER_HOVER),
        "ghost": (GHOST, NAVY, GHOST_HOVER),
    }
    bg, fg, hover = colors.get(kind, colors["primary"])
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=hover,
        activeforeground=fg,
        disabledforeground=FG_MUTED,
        relief=tk.FLAT,
        borderwidth=0,
        padx=padx,
        pady=pady,
        font=FONT_UI_BOLD,
        cursor="hand2",
        highlightthickness=0,
    )

    def _enter(_e: tk.Event) -> None:
        if str(btn["state"]) != "disabled":
            btn.configure(bg=hover)

    def _leave(_e: tk.Event) -> None:
        if str(btn["state"]) != "disabled":
            btn.configure(bg=bg)

    btn.bind("<Enter>", _enter)
    btn.bind("<Leave>", _leave)
    return btn


def build_header(
    parent: tk.Misc,
    title: str,
    subtitle: str = "Peak Energy · Attendance",
) -> tuple[tk.Frame, Any]:
    """Brand header bar (classic tk — colors always visible). Returns (frame, photo_ref)."""
    apply_theme(parent)
    bar = tk.Frame(parent, bg=NAVY, padx=14, pady=12)
    photo = None
    try:
        from PIL import Image, ImageTk
        from paths import logo_png_path

        png = logo_png_path()
        if png is not None:
            img = Image.open(png).convert("RGBA")
            img.thumbnail((48, 48))
            photo = ImageTk.PhotoImage(img)
            lbl = tk.Label(bar, image=photo, bg=NAVY, bd=0)
            lbl.image = photo  # type: ignore[attr-defined]
            lbl.pack(side=tk.LEFT, padx=(0, 12))
    except Exception:
        photo = None

    text_f = tk.Frame(bar, bg=NAVY)
    text_f.pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Label(
        text_f,
        text=title,
        bg=NAVY,
        fg="#FFFFFF",
        font=FONT_TITLE,
        anchor=tk.W,
    ).pack(anchor=tk.W)
    tk.Label(
        text_f,
        text=subtitle,
        bg=NAVY,
        fg=CYAN_SOFT,
        font=FONT_SUB,
        anchor=tk.W,
    ).pack(anchor=tk.W)
    # cyan accent strip under header
    tk.Frame(bar, bg=CYAN, height=3).pack(side=tk.BOTTOM, fill=tk.X)
    return bar, photo


def style_log_text(widget: tk.Text) -> None:
    """Dark professional log pane."""
    widget.configure(
        background=LOG_BG,
        foreground=LOG_FG,
        insertbackground=LOG_FG,
        selectbackground=CYAN,
        selectforeground=NAVY_DARK,
        relief=tk.FLAT,
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=NAVY,
        highlightcolor=CYAN,
        font=("Consolas", 9),
        padx=8,
        pady=6,
    )
