"""Desktop notifications via libnotify (Linux Mint / GNOME)."""

from __future__ import annotations

from typing import Optional


class Notifier:
    def __init__(self, app_name: str = "GLTD Notes"):
        self.app_name = app_name
        self._ok = False
        try:
            import gi

            gi.require_version("Notify", "0.7")
            from gi.repository import Notify

            if not Notify.is_initted():
                Notify.init(app_name)
            self._Notify = Notify
            self._ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[notify] libnotify unavailable: {e}")
            self._Notify = None

    @property
    def available(self) -> bool:
        return self._ok

    def notify(self, title: str, body: str = "", urgency: str = "normal") -> None:
        if not self._ok:
            print(f"[notify-fallback] {title}: {body}")
            return
        n = self._Notify.Notification.new(title, body, "appointment-soon")
        try:
            from gi.repository import Notify

            levels = {
                "low": Notify.Urgency.LOW,
                "normal": Notify.Urgency.NORMAL,
                "critical": Notify.Urgency.CRITICAL,
            }
            n.set_urgency(levels.get(urgency, Notify.Urgency.NORMAL))
        except Exception:
            pass
        n.show()
