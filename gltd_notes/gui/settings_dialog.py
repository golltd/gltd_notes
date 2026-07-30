"""Settings dialog: password, API, paths, lock policy."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from gltd_notes.config import Config
from gltd_notes.gui.icons import icon_image, icon_path
from gltd_notes.i18n import get_i18n, t


class SettingsDialog(Gtk.Dialog):
    def __init__(self, config: Config, parent: Optional[Gtk.Window] = None):
        super().__init__(title=f"{t('settings')} — {t('app_name')}", transient_for=parent, flags=0)
        self.config = config
        self.set_default_size(560, 520)
        self.add_button("OK", Gtk.ResponseType.CLOSE)
        app_icon = icon_path("app", 64)
        if app_icon.exists():
            try:
                self.set_icon_from_file(str(app_icon))
            except Exception:
                pass

        nb = Gtk.Notebook()
        self.get_content_area().set_border_width(8)
        self.get_content_area().pack_start(nb, True, True, 0)

        nb.append_page(self._page_interface(), Gtk.Label(label=t("interface")))
        nb.append_page(self._page_security(), Gtk.Label(label=t("security")))
        nb.append_page(self._page_api(), Gtk.Label(label=t("api_web")))
        nb.append_page(self._page_paths(), Gtk.Label(label=t("paths")))
        nb.append_page(self._page_about(), Gtk.Label(label=t("about_tab")))
        self.show_all()

    def _page_interface(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        gui = self.config.data.setdefault("gui", {})

        box.pack_start(Gtk.Label(label=t("language"), xalign=0), False, False, 0)
        self.lang_combo = Gtk.ComboBoxText()
        self._lang_codes = []
        current = gui.get("language") or "auto"
        active = 0
        for i, (code, label) in enumerate(get_i18n().language_choices()):
            self.lang_combo.append_text(label)
            self._lang_codes.append(code)
            if code == current:
                active = i
        self.lang_combo.set_active(active)
        box.pack_start(self.lang_combo, False, False, 0)

        box.pack_start(Gtk.Label(label=t("theme"), xalign=0), False, False, 0)
        self.theme_combo = Gtk.ComboBoxText()
        themes = [
            ("default", t("theme_default")),
            ("light", t("theme_light")),
            ("dark", t("theme_dark")),
        ]
        self._theme_codes = []
        current_theme = gui.get("theme") or "default"
        active_theme = 0
        for i, (code, label) in enumerate(themes):
            self.theme_combo.append_text(label)
            self._theme_codes.append(code)
            if code == current_theme:
                active_theme = i
        self.theme_combo.set_active(active_theme)
        box.pack_start(self.theme_combo, False, False, 0)

        self.close_tray_cb = Gtk.CheckButton(label=t("close_to_tray"))
        self.close_tray_cb.set_active(bool(gui.get("close_to_tray", True)))
        box.pack_start(self.close_tray_cb, False, False, 0)

        save = Gtk.Button(label=t("save_language"))
        save.connect("clicked", self._on_save_interface)
        box.pack_start(save, False, False, 0)
        self.iface_status = Gtk.Label(label="", xalign=0)
        box.pack_start(self.iface_status, False, False, 0)
        return box

    def _on_save_interface(self, *_args) -> None:
        idx = self.lang_combo.get_active()
        code = self._lang_codes[idx] if 0 <= idx < len(self._lang_codes) else "auto"
        self.config.data.setdefault("gui", {})["language"] = code
        self.config.data["gui"]["close_to_tray"] = self.close_tray_cb.get_active()
        tidx = self.theme_combo.get_active()
        theme_code = self._theme_codes[tidx] if 0 <= tidx < len(self._theme_codes) else "default"
        changed = (self.config.data["gui"].get("theme") != theme_code)
        self.config.data["gui"]["theme"] = theme_code
        self.config.save()
        get_i18n(code)
        if changed:
            from gltd_notes.gui.main_window import MainWindow
            mw = self.get_transient_for()
            if isinstance(mw, MainWindow):
                mw._apply_theme()
        self.iface_status.set_text(t("language_saved"))
        self.emit("response", Gtk.ResponseType.APPLY)

    def _page_security(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        uh = self.config.active_user_hash
        user = self.config.get_user(uh) if uh else None
        uname = (user or {}).get("username") or "—"
        has_pw = self.config.user_has_password(uh)

        header = Gtk.Box(spacing=8)
        try:
            header.pack_start(icon_image("lock", 32), False, False, 0)
        except Exception:
            pass
        header.pack_start(
            Gtk.Label(
                label=f"Usuário: {uname}\nSenha de bloqueio: {'definida' if has_pw else 'não definida'}",
                xalign=0,
            ),
            True,
            True,
            0,
        )
        box.pack_start(header, False, False, 0)

        info = Gtk.Label(
            label=(
                "A senha protege o bloqueio da sessão (Lock). "
                "Enquanto não houver senha definida, o botão Bloquear "
                "pedirá que você crie uma aqui — não inventa senha antiga."
            ),
            xalign=0,
            wrap=True,
        )
        box.pack_start(info, False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        row = 0
        if has_pw:
            grid.attach(Gtk.Label(label="Senha atual:", xalign=1), 0, row, 1, 1)
            self.cur_entry = Gtk.Entry(visibility=False)
            self.cur_entry.set_hexpand(True)
            grid.attach(self.cur_entry, 1, row, 1, 1)
            row += 1
        else:
            self.cur_entry = None

        grid.attach(Gtk.Label(label="Nova senha:", xalign=1), 0, row, 1, 1)
        self.new_entry = Gtk.Entry(visibility=False)
        grid.attach(self.new_entry, 1, row, 1, 1)
        row += 1

        grid.attach(Gtk.Label(label="Confirmar:", xalign=1), 0, row, 1, 1)
        self.confirm_entry = Gtk.Entry(visibility=False)
        grid.attach(self.confirm_entry, 1, row, 1, 1)
        row += 1

        btn_row = Gtk.Box(spacing=8)
        save_btn = Gtk.Button(label="Salvar senha")
        save_btn.connect("clicked", self._on_save_password)
        btn_row.pack_start(save_btn, False, False, 0)
        if has_pw:
            clear_btn = Gtk.Button(label="Remover senha (desativa lock)")
            clear_btn.connect("clicked", self._on_clear_password)
            btn_row.pack_start(clear_btn, False, False, 0)
        box.pack_start(btn_row, False, False, 0)

        self.sec_status = Gtk.Label(label="", xalign=0)
        box.pack_start(self.sec_status, False, False, 0)
        return box

    def _page_api(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        api = self.config.data["api"]
        web = self.config.data["web"]

        box.pack_start(Gtk.Label(label="API REST (somente localhost)", xalign=0), False, False, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Host:", xalign=1), 0, 0, 1, 1)
        self.api_host = Gtk.Entry()
        self.api_host.set_text(str(api.get("host", "127.0.0.1")))
        grid.attach(self.api_host, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="Porta:", xalign=1), 0, 1, 1, 1)
        self.api_port = Gtk.Entry()
        self.api_port.set_text(str(api.get("port", 8765)))
        grid.attach(self.api_port, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Web host:", xalign=1), 0, 2, 1, 1)
        self.web_host = Gtk.Entry()
        self.web_host.set_text(str(web.get("host", "127.0.0.1")))
        grid.attach(self.web_host, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Web porta:", xalign=1), 0, 3, 1, 1)
        self.web_port = Gtk.Entry()
        self.web_port.set_text(str(web.get("port", 8766)))
        grid.attach(self.web_port, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="API key:", xalign=1), 0, 4, 1, 1)
        self.key_entry = Gtk.Entry()
        self.key_entry.set_text(self.config.api_key)
        self.key_entry.set_editable(False)
        self.key_entry.set_hexpand(True)
        grid.attach(self.key_entry, 1, 4, 1, 1)

        row = Gtk.Box(spacing=8)
        save = Gtk.Button(label="Salvar API/Web")
        save.connect("clicked", self._on_save_api)
        row.pack_start(save, False, False, 0)
        regen = Gtk.Button(label="Gerar nova API key")
        regen.connect("clicked", self._on_regen_key)
        row.pack_start(regen, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.api_status = Gtk.Label(label="Reinicie a API/web para aplicar host/porta.", xalign=0)
        box.pack_start(self.api_status, False, False, 0)
        return box

    def _page_paths(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=12)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        def row(r, label, value):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, r, 1, 1)
            e = Gtk.Entry()
            e.set_text(value)
            e.set_editable(False)
            e.set_hexpand(True)
            grid.attach(e, 1, r, 1, 1)

        row(0, "Data root:", str(self.config.data_root))
        row(1, "Install root:", str(self.config.data.get("install_root", "")))
        row(2, "Config file:", str(self.config.path))
        row(3, "Hostname:", self.config.hostname)
        row(4, "Machine id:", (self.config.machine_id or "")[:24] + "…")
        uh = self.config.active_user_hash or ""
        row(5, "User hash:", uh[:24] + ("…" if len(uh) > 24 else ""))

        note = Gtk.Label(
            label="Pastas de dados são escolhidas no setup inicial. "
            "Para Syncthing, sincronize o data root.",
            xalign=0,
            wrap=True,
        )
        box.pack_start(note, False, False, 0)
        return box

    def _page_about(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        try:
            box.pack_start(icon_image("app", 96), False, False, 0)
        except Exception:
            pass
        box.pack_start(Gtk.Label(label="<b>GLTD Notes</b>", use_markup=True), False, False, 0)
        box.pack_start(
            Gtk.Label(
                label="Alternativa privada e open source ao GNote.\n"
                "Python · GTK · REST local · sync via Syncthing",
                justify=Gtk.Justification.CENTER,
            ),
            False,
            False,
            0,
        )
        from gltd_notes import __version__

        box.pack_start(Gtk.Label(label=f"Versão {__version__}"), False, False, 0)
        return box

    def _on_save_password(self, *_args) -> None:
        uh = self.config.active_user_hash
        if not uh:
            self.sec_status.set_text("Nenhum usuário ativo.")
            return
        new_pw = self.new_entry.get_text()
        conf = self.confirm_entry.get_text()
        if new_pw != conf:
            self.sec_status.set_text("As senhas não coincidem.")
            return
        cur = self.cur_entry.get_text() if self.cur_entry else None
        try:
            self.config.set_user_password(uh, new_pw, current_password=cur)
            self.sec_status.set_text("Senha salva. O bloqueio de sessão está disponível.")
            # refresh fields: parent may want to update lock button
            self.emit("response", Gtk.ResponseType.APPLY)
        except (ValueError, PermissionError, KeyError) as e:
            self.sec_status.set_text(str(e))

    def _on_clear_password(self, *_args) -> None:
        uh = self.config.active_user_hash
        if not uh or not self.cur_entry:
            return
        try:
            self.config.clear_user_password(uh, self.cur_entry.get_text())
            self.sec_status.set_text("Senha removida. Lock desativado.")
            self.emit("response", Gtk.ResponseType.APPLY)
        except (PermissionError, KeyError) as e:
            self.sec_status.set_text(str(e))

    def _on_save_api(self, *_args) -> None:
        try:
            self.config.data["api"]["host"] = self.api_host.get_text().strip() or "127.0.0.1"
            self.config.data["api"]["port"] = int(self.api_port.get_text().strip())
            self.config.data["web"]["host"] = self.web_host.get_text().strip() or "127.0.0.1"
            self.config.data["web"]["port"] = int(self.web_port.get_text().strip())
            self.config.save()
            self.api_status.set_text("Salvo. Reinicie API/web se estiverem rodando.")
        except ValueError:
            self.api_status.set_text("Portas devem ser números.")

    def _on_regen_key(self, *_args) -> None:
        key = self.config.regenerate_api_key()
        self.config.save()
        self.key_entry.set_text(key)
        self.api_status.set_text("Nova API key gerada e salva.")


def set_password_prompt(config: Config, parent: Optional[Gtk.Window] = None) -> bool:
    """Modal to define first lock password. Returns True if password is now set."""
    if config.user_has_password():
        return True
    dialog = Gtk.Dialog(title="Definir senha de bloqueio", transient_for=parent, flags=0)
    dialog.set_modal(True)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL,
        Gtk.ResponseType.CANCEL,
        "Salvar senha",
        Gtk.ResponseType.OK,
    )
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(16)
    box.pack_start(
        Gtk.Label(
            label="Ainda não há senha de bloqueio.\n"
            "Defina uma senha para poder trancar a sessão.",
            xalign=0,
        ),
        False,
        False,
        0,
    )
    e1 = Gtk.Entry(visibility=False, placeholder_text="Nova senha (mín. 4 caracteres)")
    e2 = Gtk.Entry(visibility=False, placeholder_text="Confirmar senha")
    box.pack_start(e1, False, False, 0)
    box.pack_start(e2, False, False, 0)
    status = Gtk.Label(label="", xalign=0)
    box.pack_start(status, False, False, 0)
    dialog.show_all()
    while True:
        resp = dialog.run()
        if resp != Gtk.ResponseType.OK:
            dialog.destroy()
            return False
        if e1.get_text() != e2.get_text():
            status.set_text("As senhas não coincidem.")
            continue
        try:
            uh = config.active_user_hash
            if not uh:
                status.set_text("Nenhum usuário ativo.")
                continue
            config.set_user_password(uh, e1.get_text())
            dialog.destroy()
            return True
        except ValueError as e:
            status.set_text(str(e))
