"""Sync device management and status dialog for GLTD Notes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

if TYPE_CHECKING:
    from gltd_notes.services.syncthing_service import SyncthingService


def show_sync_dialog(parent: Gtk.Window, sync_service: SyncthingService) -> None:
    if not sync_service.is_running():
        dlg = Gtk.MessageDialog(
            transient_for=parent,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Syncthing nao esta em execucao.",
        )
        dlg.format_secondary_text(
            "Verifique as configuracoes de sincronizacao em\n"
            "Configuracoes > Sync e reinicie a aplicacao."
        )
        dlg.run()
        dlg.destroy()
        return

    dlg = Gtk.Dialog(
        title="Sincronizacao — GLTD Notes",
        transient_for=parent,
        flags=0,
    )
    dlg.set_default_size(500, 400)
    dlg.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

    content = dlg.get_content_area()
    content.set_spacing(8)
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)

    notebook = Gtk.Notebook()
    notebook.set_vexpand(True)
    content.pack_start(notebook, True, True, 0)

    # ── Tab: Dispositivos ──
    dev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
    notebook.append_page(dev_box, Gtk.Label(label="Dispositivos"))

    store = Gtk.ListStore(str, str, bool)
    tree = Gtk.TreeView(model=store)
    tree.append_column(Gtk.TreeViewColumn("Nome", Gtk.CellRendererText(), text=1))
    tree.append_column(Gtk.TreeViewColumn("ID", Gtk.CellRendererText(), text=0))
    tree.append_column(Gtk.TreeViewColumn("Online", Gtk.CellRendererText(), text=2))

    def _refresh_devices() -> None:
        store.clear()
        for d in sync_service.get_devices():
            store.append([d["deviceID"], d.get("name", d["deviceID"][:12]), d.get("connected", False)])

    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.add(tree)
    dev_box.pack_start(scroll, True, True, 0)

    actions = Gtk.Box(spacing=6)
    dev_box.pack_start(actions, False, False, 0)

    add_btn = Gtk.Button(label="Adicionar dispositivo")
    add_btn.connect("clicked", lambda *_: _add_device(dlg, sync_service, _refresh_devices))
    actions.pack_start(add_btn, False, False, 0)

    rm_btn = Gtk.Button(label="Remover")
    rm_btn.connect("clicked", lambda *_: _remove_device(tree, store, sync_service, _refresh_devices))
    actions.pack_start(rm_btn, False, False, 0)

    refresh_btn = Gtk.Button(label="Atualizar")
    refresh_btn.connect("clicked", lambda *_: _refresh_devices())
    actions.pack_start(refresh_btn, False, False, 0)

    _refresh_devices()

    # ── Tab: Status ──
    status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)
    notebook.append_page(status_box, Gtk.Label(label="Status"))

    status_lbl = Gtk.Label(xalign=0)
    status_lbl.set_line_wrap(True)
    status_box.pack_start(status_lbl, False, False, 0)

    def _refresh_status() -> None:
        try:
            fs = sync_service.get_folder_status()
            ss = sync_service.get_system_status()
            comp = sync_service.get_completion()
            lines = [
                f"Pasta: {fs.get('state', '?')}",
                f"Total de itens: {fs.get('globalFiles', '?')}",
                f"Sincronizado: {comp.get('completion', 0):.0f}%",
                f"Dispositivos conectados: {ss.get('numConnections', '?')}",
                f"Uso de memoria: {ss.get('alloc', 0) / 1024 / 1024:.1f} MB",
                f"Uptime: {ss.get('uptime', 0)}s",
            ]
            status_lbl.set_text("\n".join(lines))
        except Exception:
            status_lbl.set_text("Erro ao obter status.")

    refresh_s_btn = Gtk.Button(label="Atualizar")
    refresh_s_btn.connect("clicked", lambda *_: _refresh_status())
    status_box.pack_start(refresh_s_btn, False, False, 0)
    _refresh_status()

    dlg.show_all()
    dlg.run()
    dlg.destroy()


def _add_device(parent: Gtk.Dialog, sync_service: SyncthingService, refresh_cb) -> None:
    dlg = Gtk.Dialog(
        title="Adicionar dispositivo",
        transient_for=parent,
        flags=0,
    )
    dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
    content = dlg.get_content_area()
    content.set_spacing(6)
    content.set_margin_top(8)
    content.set_margin_bottom(8)
    content.set_margin_start(8)
    content.set_margin_end(8)

    content.pack_start(Gtk.Label(label="Device ID:", xalign=0), False, False, 0)
    id_entry = Gtk.Entry()
    id_entry.set_placeholder_text("ABCDEFG-HIJKLMN-...")
    content.pack_start(id_entry, False, False, 0)

    content.pack_start(Gtk.Label(label="Nome (opcional):", xalign=0), False, False, 0)
    name_entry = Gtk.Entry()
    content.pack_start(name_entry, False, False, 0)

    personal_cb = Gtk.CheckButton(label="Dispositivo da minha rede pessoal (compartilha todas as notas)")
    content.pack_start(personal_cb, False, False, 0)

    dlg.show_all()
    if dlg.run() == Gtk.ResponseType.OK:
        did = id_entry.get_text().strip()
        if did:
            sync_service.add_device(did, name_entry.get_text().strip(), personal_cb.get_active())
            refresh_cb()
    dlg.destroy()


def _remove_device(tree: Gtk.TreeView, store: Gtk.ListStore, sync_service: SyncthingService, refresh_cb) -> None:
    sel = tree.get_selection()
    model, it = sel.get_selected()
    if not it:
        return
    did = model[it][0]
    sync_service.remove_device(did)
    refresh_cb()
