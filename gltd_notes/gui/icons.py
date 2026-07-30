"""Application icon paths and GTK helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk  # noqa: E402

# /var/PROGRAMAS/gltd_notes/icons
ICONS_DIR = Path(__file__).resolve().parents[2] / "icons"

# Logical name → file stem under icons/
ICON_FILES = {
    "app": "gltd-notes",
    "note-new": "gltd-note-new",
    "note-save": "gltd-note-save",
    "note-delete": "gltd-note-delete",
    "share": "gltd-share",
    "attach": "gltd-attach",
    "event": "gltd-event",
    "refresh": "gltd-refresh",
    "lock": "gltd-lock",
    "settings": "gltd-settings",
    "search": "gltd-search",
    "history": "gltd-history",
    "agent-task": "gltd-agent-task",
}


def icons_dir() -> Path:
    return ICONS_DIR


def icon_path(name: str, size: int = 64) -> Path:
    """Prefer sized PNG, then base PNG."""
    stem = ICON_FILES.get(name, name)
    sized = ICONS_DIR / f"{stem}-{size}.png"
    if sized.exists():
        return sized
    base = ICONS_DIR / f"{stem}.png"
    return base


def icon_image(name: str, size: int = 24) -> Gtk.Image:
    path = icon_path(name, size)
    if path.exists():
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
            return Gtk.Image.new_from_pixbuf(pb)
        except Exception:
            pass
    # fallback to theme
    fallback = {
        "app": "accessories-text-editor",
        "note-new": "document-new",
        "note-save": "document-save",
        "note-delete": "edit-delete",
        "share": "mail-send",
        "attach": "mail-attachment",
        "event": "appointment-new",
        "refresh": "view-refresh",
        "lock": "system-lock-screen",
        "settings": "preferences-system",
        "search": "edit-find",
        "history": "document-open-recent",
        "agent-task": "system-run",
    }.get(name, "image-missing")
    return Gtk.Image.new_from_icon_name(fallback, Gtk.IconSize.BUTTON)


def load_pixbuf(name: str, size: int = 48) -> Optional[GdkPixbuf.Pixbuf]:
    path = icon_path(name, size)
    if not path.exists():
        path = icon_path(name, 256 if size > 64 else 64)
    if path.exists():
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), size, size)
        except Exception:
            return None
    return None
