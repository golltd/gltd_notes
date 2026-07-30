"""System tray / app indicator for Linux Mint."""

from __future__ import annotations

from typing import Callable, Optional

from gltd_notes.gui.icons import icon_path
from gltd_notes.i18n import t


class TrayIcon:
    def __init__(
        self,
        on_new_note: Optional[Callable[[], None]] = None,
        on_new_event: Optional[Callable[[], None]] = None,
        on_show: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_settings: Optional[Callable[[], None]] = None,
        on_lock: Optional[Callable[[], None]] = None,
        on_new_tasklist: Optional[Callable[[], None]] = None,
        on_hide: Optional[Callable[[], None]] = None,
    ):
        self.on_new_note = on_new_note
        self.on_new_event = on_new_event
        self.on_show = on_show
        self.on_hide = on_hide
        self.on_quit = on_quit
        self.on_settings = on_settings
        self.on_lock = on_lock
        self.on_new_tasklist = on_new_tasklist
        self._indicator = None
        self._ok = False
        self._build()

    def _build(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            try:
                gi.require_version("AyatanaAppIndicator3", "0.1")
                from gi.repository import AyatanaAppIndicator3 as AppIndicator3
            except (ValueError, ImportError):
                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3  # type: ignore
            from gi.repository import Gtk

            custom = icon_path("app", 48)
            if custom.exists():
                try:
                    indicator = AppIndicator3.Indicator.new_with_path(
                        "gltd-notes",
                        "gltd-notes",
                        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                        str(custom.parent),
                    )
                except Exception:
                    indicator = AppIndicator3.Indicator.new(
                        "gltd-notes",
                        "accessories-text-editor",
                        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                    )
                    if hasattr(indicator, "set_icon_full"):
                        indicator.set_icon_full(str(custom), "GLTD Notes")
            else:
                indicator = AppIndicator3.Indicator.new(
                    "gltd-notes",
                    "accessories-text-editor",
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )

            indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            menu = Gtk.Menu()

            def add_item(label: str, cb: Optional[Callable[[], None]]) -> None:
                item = Gtk.MenuItem(label=label)
                if cb:
                    item.connect("activate", lambda *_: cb())
                item.show()
                menu.append(item)

            add_item(t("show_window"), self.on_show)
            if self.on_hide:
                add_item(t("hide_window"), self.on_hide)
            add_item(t("new_note"), self.on_new_note)
            add_item(t("new_tasklist"), self.on_new_tasklist)
            add_item(t("new_event"), self.on_new_event)
            add_item(t("preferences"), self.on_settings)
            add_item(t("lock"), self.on_lock)
            sep = Gtk.SeparatorMenuItem()
            sep.show()
            menu.append(sep)
            add_item(t("quit_app"), self.on_quit)
            menu.show_all()
            indicator.set_menu(menu)
            self._indicator = indicator
            self._ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[tray] app indicator unavailable: {e}")

    @property
    def available(self) -> bool:
        return self._ok
