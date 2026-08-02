"""Syncthing dashboard for GLTD Notes — device management and sharing."""

from __future__ import annotations

import socket
import subprocess
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from gltd_notes.config import Config

if TYPE_CHECKING:
    from gltd_notes.services.syncthing_service import SyncthingService


class SyncDashboard(Gtk.Dialog):
    """Full Syncthing management window for GLTD Notes."""

    @classmethod
    def show(cls, parent: Gtk.Window, config: Config, sync_service: Optional[SyncthingService]) -> None:
        dlg = cls(parent, config, sync_service)
        dlg.run()
        dlg.destroy()

    def __init__(self, parent: Gtk.Window, config: Config, sync_service: Optional[SyncthingService]):
        super().__init__(
            title="Syncthing — GLTD Notes",
            transient_for=parent,
            flags=0,
        )
        self.set_default_size(640, 520)
        self.config = config
        self._sync = sync_service or self._make_service()
        self._device_name = f"gltd_notes_{socket.gethostname()}"
        self._my_id = self._get_my_device_id()

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin(12)

        # ── My device info ──
        my_frame = Gtk.Frame(label="Meu dispositivo")
        content.pack_start(my_frame, False, False, 0)
        my_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=8)
        my_frame.add(my_box)

        id_box = Gtk.Box(spacing=6)
        my_box.pack_start(id_box, False, False, 0)
        id_box.pack_start(Gtk.Label(label="ID:"), False, False, 0)
        self._id_entry = Gtk.Entry()
        self._id_entry.set_text(self._my_id or "Aguardando...")
        self._id_entry.set_editable(False)
        self._id_entry.set_width_chars(50)
        id_box.pack_start(self._id_entry, True, True, 0)

        copy_btn = Gtk.Button(label="Copiar ID")
        copy_btn.connect("clicked", lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self._my_id, -1))
        id_box.pack_start(copy_btn, False, False, 0)

        qr_btn = Gtk.Button(label="QR Code")
        qr_btn.connect("clicked", lambda *_: self._show_my_qr())
        id_box.pack_start(qr_btn, False, False, 0)

        name_box = Gtk.Box(spacing=6)
        my_box.pack_start(name_box, False, False, 0)
        name_box.pack_start(Gtk.Label(label="Nome:"), False, False, 0)
        self._name_entry = Gtk.Entry()
        self._name_entry.set_text(self._device_name)
        name_box.pack_start(self._name_entry, True, True, 0)

        # ── Notebook: devices / friends ──
        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        content.pack_start(notebook, True, True, 0)

        # ── Tab 1: Meus dispositivos (full sharing) ──
        net_box = self._build_network_devices_tab()
        notebook.append_page(net_box, Gtk.Label(label="Minha rede"))

        # ── Tab 2: Amigos (partial sharing via @tags) ──
        friends_box = self._build_friends_tab()
        notebook.append_page(friends_box, Gtk.Label(label="Amigos"))

        self.show_all()

        # Start refresh timer
        GLib.timeout_add_seconds(10, self._refresh_network_devices)
        GLib.timeout_add_seconds(15, self._refresh_friends)

    def _make_service(self) -> Optional[SyncthingService]:
        try:
            from gltd_notes.services.syncthing_service import SyncthingService
            return SyncthingService(self.config)
        except Exception:
            return None

    def _get_my_device_id(self) -> str:
        if not self._sync or not self._sync.is_running():
            return "— Syncthing offline —"
        try:
            status = self._sync._api_get("system/status")
            return status.get("myID", "—")
        except Exception:
            pass
        bin_path = self._sync._bin_path()
        if bin_path.exists():
            try:
                r = subprocess.run([str(bin_path), "--device-id"], capture_output=True, text=True, timeout=5)
                return r.stdout.strip().split("\n")[-1].strip()
            except Exception:
                pass
        return "—"

    # ── QR Code ─────────────────────────────────────────────────

    def _show_my_qr(self) -> None:
        if not self._my_id or self._my_id.startswith("—"):
            return
        from gltd_notes.gui.main_window import MainWindow

        mw = self.get_transient_for()
        if isinstance(mw, MainWindow):
            mw._show_qrcode("Syncthing", self._my_id, self)
        else:
            pix = self._generate_qr(self._my_id, 220)
            if pix:
                dlg = Gtk.Dialog(title="QR Code — Syncthing", transient_for=self, flags=Gtk.DialogFlags.MODAL)
                dlg.set_default_size(250, 250)
                dlg.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
                dlg.get_content_area().pack_start(Gtk.Image.new_from_pixbuf(pix), True, True, 0)
                dlg.show_all()
                dlg.run()
                dlg.destroy()

    def _generate_qr(self, data: str, size: int) -> Optional[GdkPixbuf.Pixbuf]:
        try:
            from gltd_notes.gui.main_window import MainWindow
            return MainWindow._generate_qr_pixbuf(data, size)
        except Exception:
            return None

    # ── Network devices tab ─────────────────────────────────────

    def _build_network_devices_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)

        self._net_store = Gtk.ListStore(str, str, str)
        tree = Gtk.TreeView(model=self._net_store)
        tree.append_column(Gtk.TreeViewColumn("Nome", Gtk.CellRendererText(), text=0))
        tree.append_column(Gtk.TreeViewColumn("ID", Gtk.CellRendererText(), text=1))
        tree.append_column(Gtk.TreeViewColumn("Status", Gtk.CellRendererText(), text=2))

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(tree)
        box.pack_start(scroll, True, True, 0)

        actions = Gtk.Box(spacing=6)
        box.pack_start(actions, False, False, 0)

        add_btn = Gtk.Button(label="Adicionar dispositivo")
        add_btn.connect("clicked", lambda *_: self._add_network_device())
        actions.pack_start(add_btn, False, False, 0)

        rm_btn = Gtk.Button(label="Remover")
        rm_btn.connect("clicked", lambda *_: self._remove_network_device(tree))
        actions.pack_start(rm_btn, False, False, 0)

        self._net_tree = tree
        return box

    def _refresh_network_devices(self) -> bool:
        if not self._sync or not self._sync.is_running():
            self._net_store.clear()
            self._net_store.append(["— Syncthing offline —", "", ""])
            return True
        try:
            self._net_store.clear()
            for d in self._sync.get_devices():
                status = "Online" if d.get("connected") else "Offline"
                self._net_store.append([d.get("name", d["deviceID"][:12]), d["deviceID"], status])
        except Exception:
            pass
        return True

    def _add_network_device(self) -> None:
        dlg = Gtk.Dialog(title="Adicionar dispositivo da rede", transient_for=self, flags=0)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Adicionar", Gtk.ResponseType.OK)
        content = dlg.get_content_area()
        content.set_spacing(6)
        content.set_margin(8)

        content.pack_start(Gtk.Label(label="Device ID:", xalign=0), False, False, 0)
        id_entry = Gtk.Entry()
        id_entry.set_placeholder_text("ABCDEFG-HIJKLMN-...")
        content.pack_start(id_entry, False, False, 0)

        content.pack_start(Gtk.Label(label="Nome (opcional):", xalign=0), False, False, 0)
        name_entry = Gtk.Entry()
        content.pack_start(name_entry, False, False, 0)

        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            did = id_entry.get_text().strip()
            if did and self._sync:
                self._sync.add_device(did, name_entry.get_text().strip(), personal_network=True)
                self._refresh_network_devices()
        dlg.destroy()

    def _remove_network_device(self, tree: Gtk.TreeView) -> None:
        sel = tree.get_selection()
        model, it = sel.get_selected()
        if not it or not self._sync:
            return
        did = model[it][1]
        self._sync.remove_device(did)
        self._refresh_network_devices()

    # ── Friends tab (partial sharing via @tags) ──────────────────

    def _build_friends_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=8)

        add_box = Gtk.Box(spacing=6)
        box.pack_start(add_box, False, False, 0)

        add_box.pack_start(Gtk.Label(label="Compartilhar com @"), False, False, 0)
        self._friend_entry = Gtk.Entry()
        self._friend_entry.set_placeholder_text("nome_do_grupo")
        add_box.pack_start(self._friend_entry, True, True, 0)

        friend_dev_entry = Gtk.Entry()
        friend_dev_entry.set_placeholder_text("Device ID (opcional)")
        add_box.pack_start(friend_dev_entry, True, True, 0)
        self._friend_dev_entry = friend_dev_entry

        add_friend_btn = Gtk.Button(label="Compartilhar")
        add_friend_btn.connect("clicked", lambda *_: self._add_friend())
        add_box.pack_start(add_friend_btn, False, False, 0)

        # Friends list
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_vexpand(True)
        box.pack_start(paned, True, True, 0)

        self._friend_store = Gtk.ListStore(str, str, str)
        friend_tree = Gtk.TreeView(model=self._friend_store)
        friend_tree.append_column(Gtk.TreeViewColumn("Amigo @", Gtk.CellRendererText(), text=0))
        friend_tree.append_column(Gtk.TreeViewColumn("Device", Gtk.CellRendererText(), text=1))
        friend_tree.append_column(Gtk.TreeViewColumn("Notas", Gtk.CellRendererText(), text=2))
        friend_tree.get_selection().connect("changed", lambda s: self._on_friend_selected(s, friend_tree))

        friend_scroll = Gtk.ScrolledWindow()
        friend_scroll.add(friend_tree)
        paned.add1(friend_scroll)

        # Shared items for selected friend
        shared_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        paned.add2(shared_box)

        self._shared_store = Gtk.ListStore(str)
        shared_tree = Gtk.TreeView(model=self._shared_store)
        shared_tree.append_column(Gtk.TreeViewColumn("Notas compartilhadas", Gtk.CellRendererText(), text=0))
        shared_scroll = Gtk.ScrolledWindow()
        shared_scroll.set_vexpand(True)
        shared_scroll.add(shared_tree)
        shared_box.pack_start(shared_scroll, True, True, 0)

        unshare_btn = Gtk.Button(label="Parar de compartilhar com selecionado")
        unshare_btn.connect("clicked", lambda *_: self._unshare_friend(friend_tree))
        shared_box.pack_start(unshare_btn, False, False, 0)

        self._friend_tree = friend_tree
        return box

    def _refresh_friends(self) -> bool:
        try:
            self._friend_store.clear()
            uh = self.config.active_user_hash
            if not uh:
                return True
            from gltd_notes.services.notes import NotesService
            from gltd_notes.services.app_context import AppContext
            ctx = AppContext(self.config)
            notes = NotesService(ctx)
            all_notes = notes.list_notes(uh, include_body=False)
            user_tags: Dict[str, List[str]] = {}
            for n in all_notes:
                markers = n.get("markers") or []
                for m in markers:
                    if m.startswith("@"):
                        tag = m[1:]
                        user_tags.setdefault(tag, []).append(n.get("title", "(sem titulo)"))

            sc = self.config.data.get("syncthing", {})
            friends = sc.get("friends", {})
            for tag in sorted(set(list(user_tags.keys()) + list(friends.keys()))):
                dev = friends.get(tag, {}).get("device", "—")
                count = len(user_tags.get(tag, []))
                self._friend_store.append([f"@{tag}", dev, str(count)])
        except Exception:
            pass
        return True

    def _add_friend(self) -> None:
        tag = self._friend_entry.get_text().strip()
        dev_id = self._friend_dev_entry.get_text().strip()
        if not tag:
            return
        sc = self.config.data.setdefault("syncthing", {})
        friends = sc.setdefault("friends", {})
        friends[tag] = {"device": dev_id}
        self.config.save()
        if dev_id and self._sync:
            self._sync.add_device(dev_id, f"gltd-friend-@{tag}", personal_network=False)
            self._sync.add_shared_folder(tag)
        self._friend_entry.set_text("")
        self._friend_dev_entry.set_text("")
        self._refresh_friends()

    def _on_friend_selected(self, selection, tree: Gtk.TreeView) -> None:
        model, it = selection.get_selected()
        if not it:
            return
        tag = model[it][0][1:]
        self._show_shared_items(tag)

    def _show_shared_items(self, tag: str) -> None:
        self._shared_store.clear()
        uh = self.config.active_user_hash
        if not uh:
            return
        try:
            from gltd_notes.services.notes import NotesService
            from gltd_notes.services.app_context import AppContext
            ctx = AppContext(self.config)
            notes_svc = NotesService(ctx)
            all_notes = notes_svc.list_notes(uh, include_body=False)
            for n in all_notes:
                markers = n.get("markers") or []
                if f"@{tag}" in markers:
                    self._shared_store.append([n.get("title", "(sem titulo)")])
        except Exception:
            pass

    def _unshare_friend(self, tree: Gtk.TreeView) -> None:
        sel = tree.get_selection()
        model, it = sel.get_selected()
        if not it:
            return
        tag = model[it][0][1:]
        sc = self.config.data.get("syncthing", {})
        friends = sc.get("friends", {})
        if tag in friends:
            dev_id = friends[tag].get("device", "")
            del friends[tag]
            self.config.save()
            if dev_id and self._sync:
                self._sync.remove_device(dev_id)
        self._refresh_friends()
