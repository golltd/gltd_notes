"""First-run setup: data folders, user account, API key."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from gltd_notes.config import Config
from gltd_notes.services.app_context import AppContext
from gltd_notes.utils.paths import DEFAULT_DATA_ROOT


class SetupWizard(Gtk.Dialog):
    def __init__(self, config: Config, parent: Optional[Gtk.Window] = None):
        super().__init__(title="GLTD Notes — Setup", transient_for=parent, flags=0)
        self.config = config
        self.set_default_size(520, 420)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Finish", Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        box.pack_start(Gtk.Label(label="Welcome to GLTD Notes", xalign=0), False, False, 0)
        box.pack_start(
            Gtk.Label(
                label="Configure data directory (Syncthing-friendly), create your user, and review API settings.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, True, True, 8)

        grid.attach(Gtk.Label(label="Data root:", xalign=1), 0, 0, 1, 1)
        self.data_entry = Gtk.Entry()
        self.data_entry.set_text(str(config.data_root if config.data_root else DEFAULT_DATA_ROOT))
        self.data_entry.set_hexpand(True)
        grid.attach(self.data_entry, 1, 0, 1, 1)
        browse = Gtk.Button(label="Browse…")
        browse.connect("clicked", self._browse)
        grid.attach(browse, 2, 0, 1, 1)

        grid.attach(Gtk.Label(label="Username:", xalign=1), 0, 1, 1, 1)
        self.user_entry = Gtk.Entry()
        import os as _os
        self.user_entry.set_text(_os.environ.get("USER", ""))
        grid.attach(self.user_entry, 1, 1, 2, 1)

        grid.attach(Gtk.Label(label="Display name:", xalign=1), 0, 2, 1, 1)
        self.display_entry = Gtk.Entry()
        self.display_entry.set_text(_os.environ.get("USER", ""))
        grid.attach(self.display_entry, 1, 2, 2, 1)

        self.enable_lock = Gtk.CheckButton(
            label="Definir senha de bloqueio de sessão agora (opcional)"
        )
        self.enable_lock.set_active(False)
        grid.attach(self.enable_lock, 1, 3, 2, 1)

        grid.attach(Gtk.Label(label="Senha (lock):", xalign=1), 0, 4, 1, 1)
        self.pass_entry = Gtk.Entry()
        self.pass_entry.set_visibility(False)
        self.pass_entry.set_placeholder_text("Opcional — só se marcar acima")
        self.pass_entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        grid.attach(self.pass_entry, 1, 4, 2, 1)

        grid.attach(Gtk.Label(label="Confirmar:", xalign=1), 0, 5, 1, 1)
        self.pass2_entry = Gtk.Entry()
        self.pass2_entry.set_visibility(False)
        grid.attach(self.pass2_entry, 1, 5, 2, 1)

        grid.attach(Gtk.Label(label="API host:", xalign=1), 0, 6, 1, 1)
        self.api_host = Gtk.Entry()
        self.api_host.set_text(config.data["api"]["host"])
        grid.attach(self.api_host, 1, 6, 2, 1)

        grid.attach(Gtk.Label(label="API port:", xalign=1), 0, 7, 1, 1)
        self.api_port = Gtk.Entry()
        self.api_port.set_text(str(config.data["api"]["port"]))
        grid.attach(self.api_port, 1, 7, 2, 1)

        self.enable_web = Gtk.CheckButton(label="Enable optional web UI")
        self.enable_web.set_active(True)
        grid.attach(self.enable_web, 1, 8, 2, 1)

        self.status = Gtk.Label(label="", xalign=0)
        box.pack_start(self.status, False, False, 0)
        self.show_all()

    def _browse(self, *_args) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Select data directory",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.data_entry.set_text(dialog.get_filename())
        dialog.destroy()

    def apply(self) -> bool:
        data_root = self.data_entry.get_text().strip()
        username = self.user_entry.get_text().strip()
        display = self.display_entry.get_text().strip() or username
        pw = self.pass_entry.get_text()
        pw2 = self.pass2_entry.get_text()
        if not data_root:
            self.status.set_text("Data root is required.")
            return False
        if not username:
            self.status.set_text("Username is required.")
            return False
        enable_lock = self.enable_lock.get_active()
        if enable_lock:
            if not pw or pw != pw2:
                self.status.set_text("Senhas de bloqueio não coincidem ou estão vazias.")
                return False
            if len(pw) < 4:
                self.status.set_text("Senha de bloqueio: mínimo 4 caracteres.")
                return False
        try:
            port = int(self.api_port.get_text().strip())
        except ValueError:
            self.status.set_text("API port must be a number.")
            return False

        self.config.data_root = Path(data_root)
        self.config.data["api"]["host"] = self.api_host.get_text().strip() or "127.0.0.1"
        self.config.data["api"]["port"] = port
        self.config.data["web"]["enabled"] = self.enable_web.get_active()
        if not self.config.get_user_by_name(username):
            self.config.add_user(
                username,
                password=pw if enable_lock else None,
                display_name=display,
                enable_lock_password=enable_lock,
            )
        self.config.setup_complete = True
        self.config.save()

        ctx = AppContext(self.config)
        ctx.ensure_data_tree()
        # materialize user dirs
        for u in self.config.list_users():
            ctx.user_layout(u["user_hash"]).ensure()
        return True


def run_setup_if_needed(config: Config) -> bool:
    """Return True if setup is complete (or completed now)."""
    if config.setup_complete and config.list_users():
        return True
    wizard = SetupWizard(config)
    while True:
        response = wizard.run()
        if response != Gtk.ResponseType.OK:
            wizard.destroy()
            return False
        if wizard.apply():
            wizard.destroy()
            return True
        # stay open on validation error
