"""Main GTK window for GLTD Notes."""

from __future__ import annotations

import fcntl
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import List, Optional

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango  # noqa: E402

from gltd_notes.api.server import APIServer
from gltd_notes.config import Config
from gltd_notes.gui.icons import icon_image, load_pixbuf
from gltd_notes.gui.notifications import Notifier
from gltd_notes.gui.settings_dialog import SettingsDialog, set_password_prompt
from gltd_notes.gui.setup_wizard import run_setup_if_needed
from gltd_notes.gui.agent_editor import AgentTaskEditor
from gltd_notes.gui.html_editor import HtmlNoteEditor, html_to_plain
from gltd_notes.gui.task_editor import TaskEditor
from gltd_notes.gui.tray import TrayIcon
from gltd_notes.i18n import get_i18n, t
from gltd_notes.services.agent_tasks import AgentTasksService, parse_agent_body, serialize_agent
from gltd_notes.services.app_context import AppContext
from gltd_notes.services.auto_markers import AutoMarkerService
from gltd_notes.services.events import EventsService
from gltd_notes.services.notes import NotesService, normalize_markers
from gltd_notes.services.tasks import TasksService
from gltd_notes.utils.logger import list_log_files, log_exception, setup_logging
from gltd_notes.utils.paths import CONFIG_DIR

_log = logging.getLogger("gltd_notes.gui")


def _qr_format_info(ecl, mask):
    data = (ecl << 3) | mask
    gen = 0x537
    d = data << 10
    for i in range(4, -1, -1):
        if d & (1 << (i + 10)):
            d ^= gen << i
    return ((data << 10) | (d & 0x3FF)) ^ 0x5412


def _generate_pure_qr(data: str, size: int):
    """Minimal QR Code generator — pure Python, no dependencies."""
    # --- QR constants ---
    CAPACITY = [17, 32, 53, 78, 106, 134, 154, 192, 230, 271]

    ALIGN_POS = {
        1: [], 2: [18], 3: [22], 4: [26], 5: [30],
        6: [34], 7: [22, 38], 8: [24, 42], 9: [26, 46], 10: [28, 50],
    }

    EC_COUNT = [10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
    TOTAL_CW = [26, 44, 70, 100, 134, 172, 196, 242, 292, 346]

    _GEN_POLY = {
        10: [1, 216, 194, 159, 111, 199, 94, 95, 113, 157, 193],
        16: [1, 119, 66, 83, 120, 119, 22, 197, 83, 249, 41, 143, 134, 85, 53, 125, 99],
        18: [1, 146, 217, 67, 32, 75, 173, 82, 73, 220, 240, 215, 199, 175, 149, 113, 183, 251, 239],
        22: [1, 239, 68, 40, 183, 64, 13, 181, 64, 188, 48, 250, 119, 40, 191, 210, 32, 189, 30, 33, 97, 42, 224],
        24: [1, 44, 202, 20, 174, 188, 229, 157, 151, 175, 199, 196, 184, 192, 251, 209, 15, 119, 222, 228, 31, 174, 228, 159, 187],
        26: [1, 173, 251, 51, 207, 114, 36, 246, 6, 58, 88, 90, 56, 12, 189, 44, 39, 215, 47, 74, 151, 187, 189, 141, 117, 35, 174],
    }

    EXP = [1] * 512
    LOG = [0] * 256
    x = 1
    for i in range(1, 255):
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
        EXP[i] = x
        LOG[x] = i
    for i in range(255, 512):
        EXP[i] = EXP[i - 255]

    def gf_mul(a, b):
        if a == 0 or b == 0:
            return 0
        return EXP[(LOG[a] + LOG[b]) % 255]

    def gf_poly_mul(p, q):
        r = [0] * (len(p) + len(q) - 1)
        for i, a in enumerate(p):
            for j, b in enumerate(q):
                r[i + j] ^= gf_mul(a, b)
        return r

    data_bytes = data.encode("utf-8")
    ver = 1
    for cap in CAPACITY:
        if len(data_bytes) <= cap:
            break
        ver += 1
    if ver > len(CAPACITY):
        return None

    ec_count = EC_COUNT[ver - 1]
    total = TOTAL_CW[ver - 1]
    data_cw = total - ec_count

    bits = []
    bits.extend([4 >> (3 - i) & 1 for i in range(4)])
    bits.extend([len(data_bytes) >> (7 - i) & 1 for i in range(8)])
    for byte in data_bytes:
        bits.extend([byte >> (7 - i) & 1 for i in range(8)])

    terminator = min(4, data_cw * 8 - len(bits))
    bits.extend([0] * terminator)
    while len(bits) % 8 != 0:
        bits.append(0)

    pad = [0xEC, 0x11]
    pi = 0
    while len(bits) < data_cw * 8:
        bits.extend([pad[pi] >> (7 - i) & 1 for i in range(8)])
        pi = (pi + 1) % 2

    data_bytes_cw = []
    for i in range(0, len(bits), 8):
        val = 0
        for b in bits[i:i + 8]:
            val = (val << 1) | b
        data_bytes_cw.append(val)

    gen = _GEN_POLY.get(ec_count, [1] * (ec_count + 1))
    msg = data_bytes_cw + [0] * ec_count
    for i in range(len(data_bytes_cw)):
        factor = msg[i]
        if factor == 0:
            continue
        for j in range(ec_count + 1):
            msg[i + j] ^= gf_mul(gen[j], factor)
    ec_codewords = msg[len(data_bytes_cw):]

    final = data_bytes_cw + ec_codewords

    size_qr = ver * 4 + 17
    m = [[0] * size_qr for _ in range(size_qr)]

    for r, c in [(0, 0), (0, size_qr - 7), (size_qr - 7, 0)]:
        for i in range(7):
            for j in range(7):
                m[r + i][c + j] = 1 if i in (0, 6) or j in (0, 6) or (2 <= i <= 4 and 2 <= j <= 4) else 0

    for i in range(8, size_qr - 8):
        m[6][i] = m[i][6] = 1 if i % 2 == 0 else 0

    m[size_qr - 8][8] = 1

    pos = ALIGN_POS.get(ver, [])
    for ar in pos:
        for ac in pos:
            for i in range(-2, 3):
                for j in range(-2, 3):
                    m[ar + i][ac + j] = 1 if i in (-2, 2) or j in (-2, 2) else (0 if i == 0 and j == 0 else 1)

    for i in range(9):
        m[i][8] = m[8][i] = -1
        if i < 8:
            m[size_qr - 1 - i][8] = -1
            m[8][size_qr - 1 - i] = -1
    m[size_qr - 8][8] = -1

    dir_up = -1
    c = size_qr - 1
    r = size_qr - 1
    idx = 0
    bits_final = []
    for byte in final:
        bits_final.extend([byte >> (7 - i) & 1 for i in range(8)])

    while c > 0:
        if c == 6:
            c -= 1
        for _ in range(2):
            rr = r
            for _ in range(size_qr):
                if m[rr][c] == 0:
                    m[rr][c] = bits_final[idx] if idx < len(bits_final) else 0
                    idx += 1
                rr += dir_up
            c -= 1
            rr = r
            for _ in range(size_qr):
                if m[rr][c] == 0:
                    m[rr][c] = bits_final[idx] if idx < len(bits_final) else 0
                    idx += 1
                rr += dir_up
            dir_up = -dir_up
            r = (r + dir_up + size_qr) % size_qr
            c -= 1

    for i in range(size_qr):
        for j in range(size_qr):
            if m[i][j] <= 0:
                m[i][j] = 0
            if i % 3 == 0:
                m[i][j] ^= 1

    fi = _qr_format_info(1, 2)
    for i in range(6):
        m[i][8] = (fi >> i) & 1
        m[8][size_qr - 1 - i] = (fi >> i) & 1
    for i in range(2):
        m[7 - i][8] = (fi >> (7 + i)) & 1
        m[8][i + 1] = (fi >> (9 + i)) & 1
        m[8][7 - i] = (fi >> (11 + i)) & 1
        m[size_qr - 1 - i][8] = (fi >> (13 + i)) & 1
    m[size_qr - 7][8] = (fi >> 6) & 1

    border = 4
    total_size = size_qr + 2 * border
    scale = max(1, size // total_size)
    img_w = total_size * scale
    img_h = total_size * scale

    rowstride = img_w * 3
    pixels = bytearray(img_h * rowstride)

    for row in range(total_size):
        for col in range(total_size):
            qr_row = row - border
            qr_col = col - border
            v = 0
            if 0 <= qr_row < size_qr and 0 <= qr_col < size_qr:
                v = m[qr_row][qr_col]
            rgb = (0, 0, 0) if v else (255, 255, 255)
            for dy in range(scale):
                for dx in range(scale):
                    py = row * scale + dy
                    px = col * scale + dx
                    off = py * rowstride + px * 3
                    pixels[off] = rgb[0]
                    pixels[off + 1] = rgb[1]
                    pixels[off + 2] = rgb[2]

    return GdkPixbuf.Pixbuf.new_from_data(bytes(pixels), GdkPixbuf.Colorspace.RGB, False, 8, img_w, img_h, rowstride)


class MainWindow(Gtk.Window):
    def __init__(self, config: Config):
        super().__init__(title=t("app_name"))
        self.config = config
        self.config.migrate_password_flags()
        get_i18n(self.config.data.get("gui", {}).get("language") or "auto")
        self.ctx = AppContext(config)
        self.ctx.ensure_data_tree()
        self.ctx.auth.ensure_open_session()
        self.notes = NotesService(self.ctx)
        self.tasks = TasksService(self.ctx)
        self.agents = AgentTasksService(self.ctx)
        self.auto_markers = AutoMarkerService(self.ctx)
        self.events = EventsService(self.ctx)
        self.notifier = Notifier()
        self.api_server: Optional[APIServer] = None
        self._current_note_id: Optional[str] = None
        self._current_kind: str = "note"
        self._note_list: List[dict] = []
        self._ui_locked: bool = False
        self._note_id_before_lock: Optional[str] = None
        self._autosave_id: Optional[int] = None
        self._loading_note: bool = False
        self._really_quit: bool = False
        self._open_tabs: Dict[str, dict] = {}  # note_id -> {title, kind}
        self._tab_switching: bool = False
        self._opening_note: bool = False
        self._refreshing_notes: bool = False
        self._agent_timer_id: Optional[int] = None
        self._agent_start_time: float = 0.0
        self._agent_nav_stack: List[tuple] = []  # (note_id, body, children)
        self._agent_note_id: Optional[str] = None  # note currently being executed
        self._agent_flush_id: Optional[int] = None
        self._context_tab_page: int = -1
        self._current_view_kind: Optional[str] = None  # "note", "agent_task", "event"
        self._note_owner: Dict[str, str] = {}
        self._current_note_owner: Optional[str] = None

        self._tab_context_menu = Gtk.Menu()
        mi = Gtk.MenuItem(label="Fechar aba")
        mi.connect("activate", lambda *_: self._on_context_close_tab())
        self._tab_context_menu.append(mi)
        mi = Gtk.MenuItem(label="Fechar todas")
        mi.connect("activate", lambda *_: self._on_context_close_all())
        self._tab_context_menu.append(mi)
        mi = Gtk.MenuItem(label="Fechar todas à esquerda")
        mi.connect("activate", lambda *_: self._on_context_close_left())
        self._tab_context_menu.append(mi)
        mi = Gtk.MenuItem(label="Fechar todas à direita")
        mi.connect("activate", lambda *_: self._on_context_close_right())
        self._tab_context_menu.append(mi)
        sep = Gtk.SeparatorMenuItem()
        self._tab_context_menu.append(sep)
        mi = Gtk.MenuItem(label="Mover para esquerda")
        mi.connect("activate", lambda *_: self._on_context_move_left())
        self._tab_context_menu.append(mi)
        mi = Gtk.MenuItem(label="Mover para direita")
        mi.connect("activate", lambda *_: self._on_context_move_right())
        self._tab_context_menu.append(mi)
        self._tab_context_menu.show_all()

        self.set_default_size(1100, 720)
        pb = load_pixbuf("app", 64)
        if pb:
            self.set_icon(pb)
        # Close → tray by default
        self.connect("delete-event", self._on_delete_event)
        self.connect("destroy", self._on_destroy)

        self._build_ui()
        self._setup_paned_positions()
        self._setup_theme()
        self._set_editor_chrome_visible(False)
        self._update_lock_ui()
        self._start_api()
        self._tray = TrayIcon(
            on_new_note=self._new_note,
            on_new_event=self._new_event_dialog,
            on_show=self._show_from_tray,
            on_hide=self._hide_to_tray,
            on_quit=self._quit,
            on_settings=self._open_settings,
            on_lock=self._lock_session,
            on_new_tasklist=self._new_tasklist,
        )
        self._refresh_notes()
        self._refresh_dashboard()
        self._refresh_home_filter_tags()
        self._start_sync()
        GLib.timeout_add_seconds(
            int(config.data.get("notifications", {}).get("check_interval_seconds", 60)),
            self._poll_events,
        )
        self._ensure_session()
        sess = self.ctx.auth.get_session()
        if sess and sess.locked and self.config.user_has_password():
            self._enter_lock_screen()

    # ── theme ─────────────────────────────────────────────────
    _DARK_CSS = b"""
    * {
        background-color: #1e1e2e;
        color: #cdd6f4;
    }
    toolbar, toolbutton, .toolbar, headerbar {
        background-color: #181825;
        color: #cdd6f4;
        border-color: #313244;
    }
    toolbutton:hover, button:hover {
        background-color: #313244;
    }
    menubar, menu, menuitem {
        background-color: #1e1e2e;
        color: #cdd6f4;
    }
    menuitem:hover {
        background-color: #313244;
    }
    entry, textview {
        background-color: #313244;
        color: #cdd6f4;
        border-color: #45475a;
    }
    treeview {
        background-color: #1e1e2e;
        color: #cdd6f4;
    }
    treeview:selected {
        background-color: #45475a;
        color: #cdd6f4;
    }
    notebook {
        background-color: #1e1e2e;
    }
    notebook tab {
        background-color: #181825;
        color: #cdd6f4;
    }
    notebook tab:checked {
        background-color: #313244;
        color: #cdd6f4;
    }
    frame, scrolledwindow {
        border-color: #313244;
    }
    statusbar {
        background-color: #181825;
        color: #a6adc8;
    }
    paned separator {
        background-color: #313244;
    }
    combobox window, combobox menu {
        background-color: #1e1e2e;
        color: #cdd6f4;
    }
    .error { color: #f38ba8; }
    .success { color: #a6e3a1; }
    """

    _LIGHT_CSS = b"""
    entry, textview {
        background-color: #ffffff;
        color: #1e1e2e;
    }
    """

    def _setup_theme(self) -> None:
        self._css_provider = Gtk.CssProvider()
        screen = Gdk.Screen.get_default()
        style = Gtk.StyleContext()
        style.add_provider_for_screen(screen, self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme = self.config.data.get("gui", {}).get("theme") or "default"
        if theme == "dark":
            self._css_provider.load_from_data(self._DARK_CSS)
        elif theme == "light":
            self._css_provider.load_from_data(self._LIGHT_CSS)
        else:
            self._css_provider.load_from_data(b"")
        self.html_editor._apply_editor_theme(theme)

    def _setup_paned_positions(self) -> None:
        def _set_positions():
            if hasattr(self, "_main_paned"):
                self._main_paned.set_position(210)
            if hasattr(self, "_editor_paned"):
                width = self.get_allocated_width()
                if width < 800:
                    self._side_panel.set_visible(False)
                else:
                    side_w = 170
                    target = width - side_w - 220
                    self._editor_paned.set_position(max(350, target))
            return False
        GLib.idle_add(_set_positions)

    def _tool_button(self, icon_name: str, label: str, cb) -> Gtk.ToolButton:
        img = icon_image(icon_name, 24)
        btn = Gtk.ToolButton.new(img, label)
        btn.set_tooltip_text(label)
        btn.connect("clicked", lambda *_: cb())
        return btn

    def _mnemonic_menu(self, menubar: Gtk.MenuBar, label: str) -> Gtk.Menu:
        item = Gtk.MenuItem.new_with_mnemonic(label)
        m = Gtk.Menu()
        item.set_submenu(m)
        menubar.append(item)
        return m

    def _mnemonic_item(self, menu: Gtk.Menu, label: str, cb, sensitive: bool = True) -> Gtk.MenuItem:
        # plain labels (no underscore) unless caller passes mnemonic
        if "_" in label and not label.startswith("_") and "(_" not in label:
            it = Gtk.MenuItem(label=label)
        elif label.startswith("_") or "(_" in label:
            it = Gtk.MenuItem.new_with_mnemonic(label)
        else:
            it = Gtk.MenuItem(label=label)
        it.connect("activate", lambda *_: cb())
        it.set_sensitive(sensitive)
        menu.append(it)
        return it

    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)

        menubar = Gtk.MenuBar()
        outer.pack_start(menubar, False, False, 0)
        self._sensitive_menu_items: List[Gtk.MenuItem] = []

        def add_guarded(m, label, cb):
            it = self._mnemonic_item(m, label, cb)
            self._sensitive_menu_items.append(it)
            return it

        file_m = self._mnemonic_menu(menubar, t("menu_file"))
        add_guarded(file_m, "Início (Home)", self._go_home)
        add_guarded(file_m, t("new_note"), self._new_note)
        add_guarded(file_m, t("new_tasklist"), self._new_tasklist)
        add_guarded(file_m, t("save"), self._save_current)
        add_guarded(file_m, t("delete"), self._delete_current)
        file_m.append(Gtk.SeparatorMenuItem())
        add_guarded(file_m, t("attach"), self._attach_file)
        add_guarded(file_m, t("share"), self._share_current)
        file_m.append(Gtk.SeparatorMenuItem())
        add_guarded(file_m, t("hide_window"), self._hide_to_tray)
        self._mnemonic_item(file_m, t("exit"), self._quit)

        edit_m = self._mnemonic_menu(menubar, t("menu_edit"))
        add_guarded(edit_m, t("refresh"), self._refresh_all)
        add_guarded(edit_m, t("history_revert"), self._history_dialog)
        add_guarded(edit_m, "Negrito (Ctrl+B no editor)", lambda: self._fmt("bold"))
        add_guarded(edit_m, "Título H1", lambda: self._fmt("h1"))
        add_guarded(edit_m, "Lista com marcadores", lambda: self._fmt("ul"))

        tasks_m = self._mnemonic_menu(menubar, t("menu_tasks"))
        add_guarded(tasks_m, t("new_tasklist"), self._new_tasklist)
        add_guarded(tasks_m, t("new_agent_task"), self._new_agent_task)
        add_guarded(tasks_m, "Gerar marcadores (#) nas notas…", self._run_auto_markers)

        events_m = self._mnemonic_menu(menubar, t("menu_events"))
        add_guarded(events_m, t("new_event"), self._new_event_dialog)

        session_m = self._mnemonic_menu(menubar, t("menu_session"))
        self._menu_lock = self._mnemonic_item(session_m, t("lock"), self._lock_session)
        self._mnemonic_item(session_m, t("set_password"), self._open_password_settings)

        conf_m = self._mnemonic_menu(menubar, t("menu_settings"))
        self._menu_settings = self._mnemonic_item(conf_m, t("preferences"), self._open_settings)
        self._mnemonic_item(conf_m, "Syncthing", self._open_sync_dashboard)
        self._menu_api = self._mnemonic_item(conf_m, t("api_key"), self._show_api_key)

        web_m = self._mnemonic_menu(menubar, "Interface _Web")
        self._mnemonic_item(web_m, "Abrir no navegador", self._web_open)
        self._mnemonic_item(web_m, "Status…", self._web_status_dialog)
        web_m.append(Gtk.SeparatorMenuItem())
        self._mnemonic_item(web_m, "Iniciar", self._web_start)
        self._mnemonic_item(web_m, "Reiniciar", self._web_restart)
        self._mnemonic_item(web_m, "Finalizar", self._web_stop)

        help_m = self._mnemonic_menu(menubar, t("menu_help"))
        self._mnemonic_item(help_m, t("about"), self._about)
        self._mnemonic_item(help_m, "Logs", self._logs_dialog)

        # Toolbar
        self._toolbar = Gtk.Toolbar()
        outer.pack_start(self._toolbar, False, False, 0)
        self._sensitive_tool_buttons: List[Gtk.ToolButton] = []

        self._home_btn = self._tool_button("refresh", "Início (Home)", self._go_home)
        # prefer go-home icon name if available via theme
        try:
            self._home_btn.set_icon_widget(
                Gtk.Image.new_from_icon_name("go-home", Gtk.IconSize.LARGE_TOOLBAR)
            )
            self._home_btn.set_label("Home")
            self._home_btn.set_tooltip_text("Tela inicial")
        except Exception:
            pass
        self._toolbar.insert(self._home_btn, -1)
        self._toolbar.insert(Gtk.SeparatorToolItem(), -1)

        for icon, key, cb in (
            ("note-new", "new_note", self._new_note),
            ("event", "new_tasklist", self._new_tasklist),
            ("agent-task", "new_agent_task", self._new_agent_task),
            ("note-save", "save", self._save_current),
            ("note-delete", "delete", self._delete_current),
            ("share", "share", self._share_current),
            ("attach", "attach", self._attach_file),
            ("event", "new_event", self._new_event_dialog),
            ("refresh", "refresh", self._refresh_all),
            ("history", "history", self._history_dialog),
        ):
            btn = self._tool_button(icon, t(key), cb)
            self._toolbar.insert(btn, -1)
            self._sensitive_tool_buttons.append(btn)
        self._toolbar.insert(Gtk.SeparatorToolItem(), -1)
        self._lock_btn = self._tool_button("lock", t("lock"), self._lock_session)
        self._toolbar.insert(self._lock_btn, -1)
        self._settings_btn = self._tool_button("settings", t("settings"), self._open_settings)
        self._toolbar.insert(self._settings_btn, -1)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        outer.pack_start(self._stack, True, True, 0)

        # ── Home (tela inicial) ──
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self._stack.add_named(home, "home")
        self._home_welcome = Gtk.Label()
        self._home_welcome.set_markup(
            f"<span size='xx-large' weight='bold'>{t('app_name')}</span>\n"
            f"<span size='large'>{t('dashboard')}</span>"
        )
        self._home_welcome.set_justify(Gtk.Justification.CENTER)
        home.pack_start(self._home_welcome, False, False, 8)

        self._home_quick = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        home.pack_start(self._home_quick, False, False, 0)

        def navbtn(label, kind):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _, k=kind: self._open_kind_view(k))
            self._home_quick.pack_start(b, False, False, 0)

        navbtn("Notas", "note")
        navbtn("Tarefas", "tasklist")
        navbtn("Tarefas IA", "agent_task")
        navbtn("Eventos", "event")

        # Home search: generic text + tag/type filter (always visible)
        home_search = Gtk.Box(spacing=8)
        home_search.set_margin_top(4)
        home_search.set_margin_bottom(4)
        home.pack_start(home_search, False, False, 0)
        self._home_search_entry = Gtk.Entry()
        self._home_search_entry.set_placeholder_text("Pesquisar notas…")
        self._home_search_entry.set_hexpand(True)
        self._home_search_entry.connect("activate", lambda *_: self._home_search())
        home_search.pack_start(self._home_search_entry, True, True, 0)

        self._home_filter_combo = Gtk.ComboBoxText()
        self._home_filter_combo.append("all", "Todos os tipos")
        self._home_filter_combo.append("kind:note", "Tipo: nota")
        self._home_filter_combo.append("kind:tasklist", "Tipo: lista de tarefas")
        self._home_filter_combo.append("kind:agent_task", "Tipo: tarefa agente")
        self._home_filter_combo.set_active_id("all")
        self._home_filter_combo.set_size_request(200, -1)
        home_search.pack_start(self._home_filter_combo, False, False, 0)

        home_search_btn = Gtk.Button(label="Pesquisar")
        home_search_btn.connect("clicked", lambda *_: self._home_search())
        home_search.pack_start(home_search_btn, False, False, 0)
        home_clear_btn = Gtk.Button(label="Limpar")
        home_clear_btn.connect("clicked", lambda *_: self._home_search_clear())
        home_search.pack_start(home_clear_btn, False, False, 0)

        # Dashboard on home (hidden during search)
        dash = Gtk.Frame(label=t("dashboard"))
        home.pack_start(dash, True, True, 0)
        dash_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin=8)
        dash.add(dash_box)

        left_d = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_d.set_hexpand(True)
        self._dash_tasks_title = Gtk.Label(xalign=0)
        self._dash_tasks_title.set_markup(f"<b>{t('open_tasks')}</b>")
        left_d.pack_start(self._dash_tasks_title, False, False, 0)
        self._dash_tasks_list = Gtk.ListBox()
        self._dash_tasks_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll_t = Gtk.ScrolledWindow()
        scroll_t.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_t.set_vexpand(True)
        scroll_t.add(self._dash_tasks_list)
        left_d.pack_start(scroll_t, True, True, 0)
        dash_box.pack_start(left_d, True, True, 0)

        right_d = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right_d.set_hexpand(True)
        self._dash_events_title = Gtk.Label(xalign=0)
        self._dash_events_title.set_markup(f"<b>{t('upcoming_events')}</b>")
        right_d.pack_start(self._dash_events_title, False, False, 0)
        self._dash_events_list = Gtk.ListBox()
        self._dash_events_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll_e = Gtk.ScrolledWindow()
        scroll_e.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll_e.set_vexpand(True)
        scroll_e.add(self._dash_events_list)
        right_d.pack_start(scroll_e, True, True, 0)
        dash_box.pack_start(right_d, True, True, 0)
        self._dash_frame = dash

        # Recent / search results — expands to fill home when searching
        self._home_results_frame = Gtk.Frame(label="Notas recentes")
        home.pack_start(self._home_results_frame, False, False, 0)
        self._recent_box = Gtk.ListBox()
        self._recent_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._recent_box.set_activate_on_single_click(True)
        self._recent_box.connect("row-activated", self._on_home_result_activated)
        self._home_results_scroll = Gtk.ScrolledWindow()
        self._home_results_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._home_results_scroll.set_min_content_height(140)
        self._home_results_scroll.set_max_content_height(220)
        self._home_results_scroll.set_vexpand(True)
        self._home_results_scroll.set_hexpand(True)
        self._home_results_scroll.add(self._recent_box)
        self._home_results_frame.add(self._home_results_scroll)
        self._home_search_active = False

        # ── Notes workspace ──
        workspace = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack.add_named(workspace, "workspace")
        self._stack.set_visible_child_name("home")

        # Search
        search_box = Gtk.Box(spacing=6, margin=6)
        workspace.pack_start(search_box, False, False, 0)
        search_box.pack_start(icon_image("search", 20), False, False, 0)
        self.search_entry = Gtk.Entry()
        self.search_entry.set_placeholder_text(t("search_placeholder"))
        self.search_entry.connect("activate", lambda *_: self._refresh_notes())
        search_box.pack_start(self.search_entry, True, True, 0)
        search_btn = Gtk.Button(label=t("search"))
        search_btn.set_image(icon_image("search", 18))
        search_btn.set_always_show_image(True)
        search_btn.connect("clicked", lambda *_: self._refresh_notes())
        search_box.pack_start(search_btn, False, False, 0)
        self._search_btn = search_btn

        self._ws_kind_header = Gtk.Box(spacing=8, margin=6)
        self._ws_kind_header.hide()
        workspace.pack_start(self._ws_kind_header, False, False, 0)
        back_btn = Gtk.Button.new_from_icon_name("go-previous", Gtk.IconSize.BUTTON)
        back_btn.set_tooltip_text("Voltar ao painel")
        back_btn.connect("clicked", lambda *_: self._go_home())
        self._ws_kind_header.pack_start(back_btn, False, False, 0)
        self._ws_kind_label = Gtk.Label(xalign=0)
        self._ws_kind_header.pack_start(self._ws_kind_label, True, True, 0)
        self._ws_new_btn = Gtk.Button()
        self._ws_new_btn.connect("clicked", lambda *_: self._on_ws_new_clicked())
        self._ws_kind_header.pack_start(self._ws_new_btn, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._main_paned = paned
        workspace.pack_start(paned, True, True, 0)

        scroll_list = Gtk.ScrolledWindow()
        scroll_list.set_size_request(200, -1)
        # id, title, updated, kind, favorite
        self.store = Gtk.ListStore(str, str, str, str, bool)
        self.tree = Gtk.TreeView(model=self.store)
        for i, key in enumerate(("col_title", "col_updated")):
            r = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(t(key), r, text=i + 1)
            col.set_expand(i == 0)
            col.set_cell_data_func(r, self._tree_cell_data, None)
            self.tree.append_column(col)
        self.tree.get_selection().connect("changed", self._on_select)
        self.tree.connect("button-press-event", self._on_tree_button_press)
        scroll_list.add(self.tree)
        paned.add1(scroll_list)

        self._tree_context_menu = Gtk.Menu()
        mi_fav = Gtk.MenuItem(label="Salvar como favorito")
        mi_fav.connect("activate", lambda *_: self._toggle_tree_favorite(True))
        self._tree_context_menu.append(mi_fav)
        mi_unfav = Gtk.MenuItem(label="Remover dos favoritos")
        mi_unfav.connect("activate", lambda *_: self._toggle_tree_favorite(False))
        self._tree_context_menu.append(mi_unfav)
        sep = Gtk.SeparatorMenuItem()
        self._tree_context_menu.append(sep)
        mi_del = Gtk.MenuItem(label=t("delete"))
        mi_del.connect("activate", lambda *_: self._tree_context_delete())
        self._tree_context_menu.append(mi_del)
        self._tree_context_menu.show_all()

        # center editor + right meta/history
        center_right = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._editor_paned = center_right
        paned.add2(center_right)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        center_right.pack1(right, True, True)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.set_show_tabs(True)
        self.notebook.connect("switch-page", self._on_tab_switch)
        right.pack_start(self.notebook, False, False, 0)

        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text(t("title"))
        self.title_entry.connect("changed", lambda *_: self._schedule_autosave())
        right.pack_start(self.title_entry, False, False, 0)

        markers_box = Gtk.Box(spacing=6)
        markers_box.pack_start(Gtk.Label(label="#"), False, False, 0)
        self.markers_entry = Gtk.Entry()
        self.markers_entry.set_placeholder_text("Marcadores: #linux #php #rede …")
        self.markers_entry.connect("changed", lambda *_: self._on_markers_changed())
        markers_box.pack_start(self.markers_entry, True, True, 0)
        right.pack_start(markers_box, False, False, 0)
        self._markers_box = markers_box

        self.meta_label = Gtk.Label(label="", xalign=0)
        self.meta_label.set_line_wrap(True)
        right.pack_start(self.meta_label, False, False, 0)

        self._editor_stack = Gtk.Stack()
        self._editor_stack.set_hexpand(True)
        self._editor_stack.set_vexpand(True)
        right.pack_start(self._editor_stack, True, True, 0)

        # plain note — HTML rich editor
        self.html_editor = HtmlNoteEditor(on_change=self._schedule_autosave)
        self._editor_stack.add_named(self.html_editor, "note")

        # task list
        self.task_editor = TaskEditor(
            on_change=self._schedule_autosave,
            on_open_note=self._open_note_by_id,
            get_notes=lambda: self._note_list,
            on_create_note=self._task_create_note,
            on_add_progress=self._task_add_progress,
            on_view_progress=self._task_view_progress,
            on_add_subtask=self._task_add_subtask,
        )
        self._editor_stack.add_named(self.task_editor, "tasklist")

        # agent task
        self.agent_editor = AgentTaskEditor(
            on_change=self._schedule_autosave,
            on_play=self._play_agent_task,
            on_add_related=self._add_related_inline,
            on_clear_output=self._clear_agent_output,
            on_cancel=self._cancel_agent_task,
            on_navigate_to_child=self._agent_nav_to_child,
            on_navigate_back=self._agent_nav_back,
            on_play_subtask=self._play_agent_subtask,
        )
        self._editor_stack.add_named(self.agent_editor, "agent_task")

        placeholder = Gtk.Box()
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.pack_start(Gtk.Label(label="Selecione uma nota na lista"), True, False, 0)
        placeholder.show_all()
        self._editor_stack.add_named(placeholder, "empty")
        self._editor_stack.set_visible_child_name("empty")

        hist_btn = Gtk.Button(label=t("history_revert"))
        hist_btn.set_image(icon_image("history", 18))
        hist_btn.set_always_show_image(True)
        hist_btn.connect("clicked", lambda *_: self._history_dialog())
        right.pack_start(hist_btn, False, False, 0)
        self._hist_btn = hist_btn

        self._side_toggle_btn = Gtk.Button()
        self._side_toggle_btn.set_image(Gtk.Image.new_from_icon_name("go-previous", Gtk.IconSize.BUTTON))
        self._side_toggle_btn.set_tooltip_text("Mostrar/Ocultar detalhes")
        self._side_toggle_btn.set_always_show_image(True)
        self._side_toggle_btn.connect("clicked", lambda *_: self._toggle_side_panel())
        self._side_toggle_btn.hide()
        right.pack_start(self._side_toggle_btn, False, False, 0)

        # ── Side panel: created + versions ──
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        side.set_size_request(180, -1)
        center_right.pack2(side, False, True)
        side.pack_start(Gtk.Label(label="<b>Detalhes</b>", use_markup=True, xalign=0), False, False, 0)
        self._side_created = Gtk.Label(label="Criada: —", xalign=0)
        self._side_created.set_line_wrap(True)
        side.pack_start(self._side_created, False, False, 0)
        self._side_updated = Gtk.Label(label="Atualizada: —", xalign=0)
        self._side_updated.set_line_wrap(True)
        side.pack_start(self._side_updated, False, False, 0)
        self._side_host = Gtk.Label(label="Host: —", xalign=0)
        self._side_host.set_line_wrap(True)
        side.pack_start(self._side_host, False, False, 0)
        self._side_markers = Gtk.Label(label="Marcadores: —", xalign=0)
        self._side_markers.set_line_wrap(True)
        side.pack_start(self._side_markers, False, False, 0)
        self._side_fav_btn = Gtk.Button()
        self._side_fav_btn.set_image(Gtk.Image.new_from_icon_name("starred", Gtk.IconSize.BUTTON))
        self._side_fav_btn.set_always_show_image(True)
        self._side_fav_btn.connect("clicked", lambda *_: self._on_side_fav_clicked())
        side.pack_start(self._side_fav_btn, False, False, 0)
        side.pack_start(Gtk.Separator(), False, False, 4)
        side.pack_start(Gtk.Label(label="<b>Versões anteriores</b>", use_markup=True, xalign=0), False, False, 0)
        self._hist_store = Gtk.ListStore(str, str, str)  # block_hash, when, action
        self._hist_tree = Gtk.TreeView(model=self._hist_store)
        self._hist_tree.append_column(Gtk.TreeViewColumn("Quando", Gtk.CellRendererText(), text=1))
        self._hist_tree.append_column(Gtk.TreeViewColumn("Ação", Gtk.CellRendererText(), text=2))
        self._hist_tree.connect("row-activated", self._on_hist_activated)
        scroll_h = Gtk.ScrolledWindow()
        scroll_h.set_vexpand(True)
        scroll_h.add(self._hist_tree)
        side.pack_start(scroll_h, True, True, 0)
        rev_btn = Gtk.Button(label="Reverter para selecionada")
        rev_btn.connect("clicked", lambda *_: self._revert_selected_side())
        side.pack_start(rev_btn, False, False, 0)
        self._side_panel = side

        # ── Events view ──
        events_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self._stack.add_named(events_view, "events_view")
        ev_header = Gtk.Box(spacing=8)
        ev_back = Gtk.Button.new_from_icon_name("go-previous", Gtk.IconSize.BUTTON)
        ev_back.connect("clicked", lambda *_: self._go_home())
        ev_header.pack_start(ev_back, False, False, 0)
        ev_header.pack_start(Gtk.Label(label="<b>Eventos</b>", use_markup=True, xalign=0), True, True, 0)
        ev_new = Gtk.Button(label="Novo evento")
        ev_new.connect("clicked", lambda *_: self._new_event_dialog())
        ev_header.pack_start(ev_new, False, False, 0)
        events_view.pack_start(ev_header, False, False, 0)
        ev_search_box = Gtk.Box(spacing=6)
        self._ev_search_entry = Gtk.Entry()
        self._ev_search_entry.set_placeholder_text("Pesquisar eventos…")
        self._ev_search_entry.connect("activate", lambda *_: self._refresh_events_view())
        ev_search_box.pack_start(self._ev_search_entry, True, True, 0)
        ev_search_btn = Gtk.Button(label=t("search"))
        ev_search_btn.connect("clicked", lambda *_: self._refresh_events_view())
        ev_search_box.pack_start(ev_search_btn, False, False, 0)
        events_view.pack_start(ev_search_box, False, False, 0)
        ev_scroll = Gtk.ScrolledWindow()
        ev_scroll.set_vexpand(True)
        self._ev_listbox = Gtk.ListBox()
        ev_scroll.add(self._ev_listbox)
        events_view.pack_start(ev_scroll, True, True, 0)

        # Lock page
        lock_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lock_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        lock_inner.set_halign(Gtk.Align.CENTER)
        lock_inner.set_valign(Gtk.Align.CENTER)
        for m in (40, 40, 40, 40):
            pass
        lock_inner.set_margin_top(40)
        lock_inner.set_margin_bottom(40)
        try:
            lock_inner.pack_start(icon_image("lock", 96), False, False, 0)
        except Exception:
            pass
        self._lock_title = Gtk.Label()
        self._lock_title.set_markup(f"<span size='xx-large' weight='bold'>{t('session_locked')}</span>")
        lock_inner.pack_start(self._lock_title, False, False, 0)
        self._lock_sub = Gtk.Label(label=t("notes_hidden"), justify=Gtk.Justification.CENTER)
        lock_inner.pack_start(self._lock_sub, False, False, 0)
        self._unlock_entry = Gtk.Entry(visibility=False)
        self._unlock_entry.set_placeholder_text(t("password"))
        self._unlock_entry.set_width_chars(28)
        self._unlock_entry.connect("activate", lambda *_: self._try_unlock())
        lock_inner.pack_start(self._unlock_entry, False, False, 0)
        unlock_btn = Gtk.Button(label=t("unlock"))
        unlock_btn.connect("clicked", lambda *_: self._try_unlock())
        lock_inner.pack_start(unlock_btn, False, False, 0)
        self._unlock_btn = unlock_btn
        self._unlock_error = Gtk.Label(label="")
        lock_inner.pack_start(self._unlock_error, False, False, 0)
        lock_page.pack_start(lock_inner, True, True, 0)
        self._stack.add_named(lock_page, "locked")
        self._stack.set_visible_child_name("workspace")

        self.agent_status_label = Gtk.Label()
        self.agent_status_label.set_use_markup(True)
        self.agent_status_label.set_no_show_all(True)
        self.agent_status_label.set_halign(Gtk.Align.START)
        self.agent_status_label.set_margin_start(8)
        self.agent_status_label.set_margin_end(8)
        self.agent_status_label.hide()
        outer.pack_start(self.agent_status_label, False, False, 0)

        self._sync_btn = Gtk.Button(label="  Sync: —  ")
        self._sync_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._sync_btn.set_tooltip_text("Status de sincronizacao — clique para abrir painel Syncthing")
        self._sync_btn.connect("clicked", lambda *_: self._open_sync_dashboard())
        self._sync_btn.hide()
        outer.pack_start(self._sync_btn, False, False, 0)

        self.status = Gtk.Statusbar()
        self.status_ctx = self.status.get_context_id("main")
        outer.pack_start(self.status, False, False, 0)
        self.show_all()

    # ── lock UI helpers (same pattern as before) ─────────────
    def _update_lock_ui(self) -> None:
        has_pw = self.config.user_has_password()
        tip = t("lock") if has_pw else t("lock") + "…"
        if self._ui_locked:
            tip = t("session_locked")
        self._lock_btn.set_tooltip_text(tip)
        if hasattr(self, "_menu_lock"):
            self._menu_lock.set_sensitive(not self._ui_locked)

    def _require_unlocked(self) -> bool:
        if self._ui_locked:
            self._set_status(t("session_locked"))
            return False
        return True

    def _wipe_visible_note_data(self) -> None:
        self.store.clear()
        self._note_list = []
        self.title_entry.set_text("")
        self.markers_entry.set_text("")
        self.meta_label.set_text("")
        self.html_editor.clear()
        self.task_editor.load_from_body('{"tasks":[]}')
        self.agent_editor.load_full("{}")
        self.search_entry.set_text("")
        self._hist_store.clear()
        self._side_created.set_text("Criada: —")
        self._side_updated.set_text("Atualizada: —")
        self._side_host.set_text("Host: —")
        self._side_markers.set_text("Marcadores: —")
        self._clear_listbox(self._dash_tasks_list)
        self._clear_listbox(self._dash_events_list)
        self._clear_listbox(self._recent_box)
        while self.notebook.get_n_pages() > 0:
            self.notebook.remove_page(0)
        self._open_tabs.clear()
        sel = self.tree.get_selection()
        if sel:
            sel.unselect_all()

    def _set_controls_sensitive(self, enabled: bool) -> None:
        for it in getattr(self, "_sensitive_menu_items", []):
            it.set_sensitive(enabled)
        for btn in getattr(self, "_sensitive_tool_buttons", []):
            btn.set_sensitive(enabled)
        self.search_entry.set_sensitive(enabled)
        self._search_btn.set_sensitive(enabled)
        self.title_entry.set_sensitive(enabled)
        self.html_editor.set_sensitive(enabled)
        self.tree.set_sensitive(enabled)
        self._hist_btn.set_sensitive(enabled)
        self.task_editor.set_sensitive(enabled)
        self.agent_editor.set_sensitive(enabled)
        self.markers_entry.set_sensitive(enabled)
        self._settings_btn.set_sensitive(enabled)
        self._home_btn.set_sensitive(enabled)
        self.notebook.set_sensitive(enabled)
        if hasattr(self, "_menu_settings"):
            self._menu_settings.set_sensitive(enabled)
        if hasattr(self, "_menu_api"):
            self._menu_api.set_sensitive(enabled)
        self._lock_btn.set_sensitive(enabled)

    def _enter_lock_screen(self) -> None:
        self._cancel_autosave()
        self._cancel_agent_timer()
        self._cancel_agent_flush()
        self._agent_nav_stack.clear()
        self.agent_editor.hide_nav_bar()
        self.agent_status_label.hide()
        self._note_id_before_lock = self._current_note_id
        self._tabs_before_lock = list(self._open_tabs.keys())
        self._current_note_id = None
        self._wipe_visible_note_data()
        self._ui_locked = True
        self._set_controls_sensitive(False)
        self._unlock_entry.set_text("")
        self._unlock_error.set_text("")
        self._stack.set_visible_child_name("locked")
        self.set_title(f"{t('app_name')} — {t('session_locked')}")
        self._set_status(t("session_locked"))
        self._update_lock_ui()
        GLib.idle_add(self._unlock_entry.grab_focus)

    def _leave_lock_screen(self) -> None:
        self._ui_locked = False
        self._set_controls_sensitive(True)
        self.set_title(t("app_name"))
        self._update_lock_ui()
        restore_tabs = getattr(self, "_tabs_before_lock", [])
        self._tabs_before_lock = []
        restore_id = self._note_id_before_lock
        self._note_id_before_lock = None
        if restore_tabs or restore_id:
            self._stack.set_visible_child_name("workspace")
            self._refresh_all()
            if restore_tabs:
                for nid in restore_tabs:
                    try:
                        self._open_note_by_id(nid)
                    except Exception:
                        pass
            if restore_id:
                self._open_note_by_id(restore_id)
        else:
            self._go_home()
        self._set_status(t("unlock"))

    def _try_unlock(self) -> None:
        if not self._ui_locked:
            return
        try:
            self.ctx.auth.unlock(self._unlock_entry.get_text())
        except PermissionError:
            self._unlock_error.set_markup(
                f'<span foreground="#e06060">{t("wrong_password")}</span>'
            )
            self._unlock_entry.set_text("")
            self._unlock_entry.grab_focus()
            return
        self._leave_lock_screen()

    def _user_hash(self) -> str:
        uh = self.config.active_user_hash
        if not uh and self.config.list_users():
            uh = self.config.list_users()[0]["user_hash"]
            self.config.active_user_hash = uh
            self.config.save()
        if not uh:
            raise RuntimeError("No user configured")
        return uh

    def _ensure_session(self) -> None:
        s = self.ctx.auth.ensure_open_session()
        self._set_status(f"{s.username}")

    def _start_api(self) -> None:
        if not self.config.data["api"].get("enabled", True):
            return
        try:
            self.api_server = APIServer(self.ctx)
            self.api_server.start_background()
        except OSError:
            pass

    def _set_status(self, msg: str) -> None:
        self.status.pop(self.status_ctx)
        self.status.push(self.status_ctx, msg)

    # ── dashboard ────────────────────────────────────────────
    @staticmethod
    def _clear_listbox(lb: Gtk.ListBox) -> None:
        for row in lb.get_children():
            lb.remove(row)

    def _refresh_dashboard(self) -> None:
        if self._ui_locked:
            return
        uh = self._user_hash()
        self._clear_listbox(self._dash_tasks_list)
        open_tasks = self.tasks.list_open_tasks_summary(uh, limit=15)
        if not open_tasks:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label=t("no_open_tasks"), xalign=0))
            self._dash_tasks_list.add(row)
        else:
            for item in open_tasks:
                row = Gtk.ListBoxRow()
                box = Gtk.Box(spacing=6)
                due = item.get("due_date") or ""
                due_s = f" · até {due}" if due else ""
                pc = item.get("progress_count") or 0
                prog_s = f" · {pc} and." if pc else ""
                lab = Gtk.Label(
                    label=f"☐ {item.get('text') or '…'}{due_s}{prog_s}  —  {item.get('list_title') or ''}",
                    xalign=0,
                )
                lab.set_ellipsize(Pango.EllipsizeMode.END)
                box.pack_start(lab, True, True, 0)
                btn = Gtk.Button(label="→")
                lid = item["list_id"]
                btn.connect("clicked", lambda _b, i=lid: self._open_note_by_id(i))
                box.pack_start(btn, False, False, 0)
                row.add(box)
                self._dash_tasks_list.add(row)

        self._clear_listbox(self._dash_events_list)
        try:
            evs = self.events.list_events(uh, include_completed=False)[:12]
        except Exception:
            evs = []
        if not evs:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label=t("no_events"), xalign=0))
            self._dash_events_list.add(row)
        else:
            for ev in evs:
                row = Gtk.ListBoxRow()
                when = (ev.get("due_at") or ev.get("remind_at") or "")[:16].replace("T", " ")
                lab = Gtk.Label(
                    label=f"📅 {when}  {ev.get('title') or ''}",
                    xalign=0,
                )
                lab.set_ellipsize(Pango.EllipsizeMode.END)
                row.add(lab)
                self._dash_events_list.add(row)
        self._dash_tasks_list.show_all()
        self._dash_events_list.show_all()
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        if self._ui_locked:
            return
        if getattr(self, "_home_search_active", False):
            return
        self._populate_home_results(self.notes.list_notes(self._user_hash())[:12], "Notas recentes")

    def _populate_home_results(self, notes: list, frame_title: str) -> None:
        self._home_results_frame.set_label(frame_title)
        self._clear_listbox(self._recent_box)
        if not notes:
            row = Gtk.ListBoxRow()
            row.add(Gtk.Label(label="Nenhum resultado — ajuste a busca ou clique em Home", xalign=0))
            self._recent_box.add(row)
            self._recent_box.show_all()
            return
        for n in notes:
            row = Gtk.ListBoxRow()
            row._note_id = n["entity_id"]  # type: ignore[attr-defined]
            box = Gtk.Box(spacing=10, margin_top=4, margin_bottom=4, margin_start=6, margin_end=6)
            kind = n.get("kind") or "note"
            prefix = {"tasklist": "☑ ", "agent_task": "🤖 "}.get(kind, "📝 ")
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            vbox.set_hexpand(True)
            title = prefix + (n.get("title") or t("untitled"))
            lab = Gtk.Label(label=title, xalign=0)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            lab.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
            vbox.pack_start(lab, False, False, 0)
            markers = " ".join((n.get("markers") or [])[:6])
            updated = (n.get("updated_at") or "")[:19].replace("T", " ")
            sub = f"{updated} · {kind}"
            if markers:
                sub += f" · {markers}"
            meta = Gtk.Label(label=sub, xalign=0)
            meta.set_ellipsize(Pango.EllipsizeMode.END)
            meta.set_opacity(0.75)
            vbox.pack_start(meta, False, False, 0)
            box.pack_start(vbox, True, True, 0)
            btn = Gtk.Button(label="Abrir")
            nid = n["entity_id"]
            btn.connect("clicked", lambda _b, i=nid: self._open_from_home(i))
            box.pack_start(btn, False, False, 0)
            row.add(box)
            self._recent_box.add(row)
        self._recent_box.show_all()

    def _on_home_result_activated(self, _listbox, row) -> None:
        nid = getattr(row, "_note_id", None)
        if nid:
            self._open_from_home(nid)

    def _refresh_home_filter_tags(self) -> None:
        """Rebuild tag options in home filter combo (keep kind options)."""
        if not hasattr(self, "_home_filter_combo"):
            return
        current = self._home_filter_combo.get_active_id() or "all"
        # remove old tag:* entries by rebuilding
        model = self._home_filter_combo.get_model()
        # ComboBoxText: clear and re-add fixed + dynamic tags
        self._home_filter_combo.remove_all()
        self._home_filter_combo.append("all", "Todos os tipos / tags")
        self._home_filter_combo.append("kind:note", "Tipo: nota")
        self._home_filter_combo.append("kind:tasklist", "Tipo: lista de tarefas")
        self._home_filter_combo.append("kind:agent_task", "Tipo: tarefa agente")
        tags: dict[str, int] = {}
        try:
            for n in self.notes.list_notes(self._user_hash())[:500]:
                for m in n.get("markers") or []:
                    tags[m] = tags.get(m, 0) + 1
                for tg in n.get("tags") or []:
                    if not str(tg).startswith("system:"):
                        key = tg if str(tg).startswith("#") else f"#{tg}"
                        tags[key] = tags.get(key, 0) + 1
        except Exception:
            pass
        for tag, cnt in sorted(tags.items(), key=lambda x: (-x[1], x[0].lower()))[:40]:
            self._home_filter_combo.append(f"tag:{tag}", f"Tag: {tag} ({cnt})")
        if current and self._home_filter_combo.get_active_id() is None:
            # try restore
            self._home_filter_combo.set_active_id(current)
        if self._home_filter_combo.get_active_id() is None:
            self._home_filter_combo.set_active_id("all")

    def _set_home_dashboard_visible(self, visible: bool) -> None:
        """Hide dashboard chrome; expand search results to use the full home area."""
        for wname in ("_dash_frame", "_home_welcome", "_home_quick"):
            w = getattr(self, wname, None)
            if w is None:
                continue
            if visible:
                w.show()
            else:
                w.hide()
        frame = getattr(self, "_home_results_frame", None)
        scroll = getattr(self, "_home_results_scroll", None)
        if frame is not None:
            # When searching: pack expand + fill the remaining home height
            parent = frame.get_parent()
            if parent is not None:
                parent.set_child_packing(frame, expand=not visible, fill=True, padding=0, pack_type=Gtk.PackType.START)
            frame.set_vexpand(not visible)
            frame.set_hexpand(True)
        if scroll is not None:
            if visible:
                scroll.set_min_content_height(140)
                scroll.set_max_content_height(220)
            else:
                # remove cap so results use the whole window
                scroll.set_min_content_height(320)
                scroll.set_max_content_height(4096)
            scroll.set_vexpand(True)

    def _home_search(self) -> None:
        if self._ui_locked:
            return
        q = (self._home_search_entry.get_text() or "").strip()
        filt = self._home_filter_combo.get_active_id() or "all"
        # empty search + all filter → back to normal home
        if not q and filt == "all":
            self._home_search_clear()
            return
        try:
            notes = self.notes.list_notes(self._user_hash(), query=q or None)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"Busca: {e}")
            return
        if filt.startswith("kind:"):
            kind = filt.split(":", 1)[1]
            notes = [n for n in notes if (n.get("kind") or "note") == kind]
        elif filt.startswith("tag:"):
            tag = filt.split(":", 1)[1].lower()

            def has_tag(n):
                marks = [m.lower() for m in (n.get("markers") or [])]
                tags = [str(t).lower() for t in (n.get("tags") or [])]
                return (
                    tag in marks
                    or tag.lstrip("#") in [t.lstrip("#") for t in tags]
                    or tag in tags
                )

            notes = [n for n in notes if has_tag(n)]
        self._home_search_active = True
        self._set_home_dashboard_visible(False)
        label = "Resultados da pesquisa"
        if q:
            label += f" · “{q}”"
        if filt != "all":
            active_text = self._home_filter_combo.get_active_text() or filt
            label += f" · {active_text}"
        label += f" ({len(notes)})"
        self._populate_home_results(notes[:100], label)
        self._set_status(f"{len(notes)} resultado(s) — Home para voltar ao painel")

    def _home_search_clear(self) -> None:
        if hasattr(self, "_home_search_entry"):
            self._home_search_entry.set_text("")
        if hasattr(self, "_home_filter_combo"):
            self._home_filter_combo.set_active_id("all")
        self._home_search_active = False
        self._set_home_dashboard_visible(True)
        self._refresh_recent()
        self._set_status(t("dashboard"))

    def _open_from_home(self, note_id: str) -> None:
        self._open_note_by_id(note_id)

    def _go_home(self) -> None:
        if self._ui_locked:
            return
        self._autosave_now(silent=True)
        self._agent_nav_stack.clear()
        self.agent_editor.hide_nav_bar()
        self._current_note_id = None
        sel = self.tree.get_selection()
        if sel:
            sel.unselect_all()
        while self.notebook.get_n_pages() > 0:
            self.notebook.remove_page(0)
        self._open_tabs.clear()
        self._current_view_kind = None
        self._ws_kind_header.hide()
        self.search_entry.set_text("")
        self._stack.set_visible_child_name("home")
        # Full home again: clear search mode and show dashboard panels
        if hasattr(self, "_home_search_entry"):
            self._home_search_entry.set_text("")
        if hasattr(self, "_home_filter_combo"):
            self._home_filter_combo.set_active_id("all")
        self._home_search_active = False
        self._set_home_dashboard_visible(True)
        self._refresh_dashboard()
        self._refresh_home_filter_tags()
        self._set_status(t("dashboard"))

    def _open_notes_view(self) -> None:
        if self._ui_locked:
            return
        self._stack.set_visible_child_name("workspace")
        self._refresh_notes()

    def _open_kind_view(self, kind: str) -> None:
        if self._ui_locked:
            return
        self._autosave_now(silent=True)
        self._agent_nav_stack.clear()
        self.agent_editor.hide_nav_bar()
        self._current_note_id = None
        self._current_kind = "note"
        sel = self.tree.get_selection()
        if sel:
            sel.unselect_all()
        while self.notebook.get_n_pages() > 0:
            self.notebook.remove_page(0)
        self._open_tabs.clear()
        self.title_entry.set_text("")
        self.markers_entry.set_text("")
        self._editor_stack.set_visible_child_name("empty")
        self._set_editor_chrome_visible(False)
        self._current_view_kind = kind
        if kind == "event":
            self._stack.set_visible_child_name("events_view")
            self._refresh_events_view()
        else:
            self._ws_kind_header.show()
            if kind == "note":
                self._ws_kind_label.set_markup("<b>Notas</b>")
                self._ws_new_btn.set_label("Nova nota")
            elif kind == "agent_task":
                self._ws_kind_label.set_markup("<b>Tarefas IA</b>")
                self._ws_new_btn.set_label("Nova tarefa")
            elif kind == "tasklist":
                self._ws_kind_label.set_markup("<b>Tarefas</b>")
                self._ws_new_btn.set_label("Nova lista de tarefas")
            self._stack.set_visible_child_name("workspace")
            self._refresh_notes()

    def _on_ws_new_clicked(self) -> None:
        if not self._require_unlocked():
            return
        if self._current_view_kind == "note":
            self._new_note()
        elif self._current_view_kind == "agent_task":
            self._new_agent_task()
        elif self._current_view_kind == "tasklist":
            self._new_tasklist()

    def _refresh_events_view(self) -> None:
        if self._ui_locked:
            return
        self._clear_listbox(self._ev_listbox)
        try:
            uh = self._user_hash()
            evs = self.events.list_events(uh, include_completed=False)
        except Exception:
            return
        q = (self._ev_search_entry.get_text() or "").strip().lower()
        if q:
            evs = [e for e in evs if q in (e.get("title") or "").lower() or q in (e.get("body") or "").lower()]
        for ev in evs:
            row = Gtk.ListBoxRow()
            when = (ev.get("due_at") or ev.get("remind_at") or "")[:16].replace("T", " ")
            title = ev.get("title") or ""
            body = ev.get("body") or ""
            suffix = f" — {body[:60]}" if body else ""
            lab = Gtk.Label(label=f"📅 {when}  {title}{suffix}", xalign=0)
            lab.set_ellipsize(Pango.EllipsizeMode.END)
            row.add(lab)
            self._ev_listbox.add(row)
        self._ev_listbox.show_all()
        self._set_status(f"{len(evs)} evento(s)")

    def _set_editor_chrome_visible(self, visible: bool) -> None:
        self.title_entry.set_visible(visible)
        self._markers_box.set_visible(visible)
        self.meta_label.set_visible(visible)
        self._side_panel.set_visible(visible)
        self._hist_btn.set_visible(visible)
        if hasattr(self, "_side_toggle_btn"):
            self._side_toggle_btn.set_visible(visible)

    def _toggle_side_panel(self) -> None:
        visible = not self._side_panel.get_visible()
        self._side_panel.set_visible(visible)
        if visible:
            self._side_toggle_btn.set_tooltip_text("Ocultar detalhes")
            self._side_toggle_btn.set_image(Gtk.Image.new_from_icon_name("go-previous", Gtk.IconSize.BUTTON))
        else:
            self._side_toggle_btn.set_tooltip_text("Mostrar detalhes")
            self._side_toggle_btn.set_image(Gtk.Image.new_from_icon_name("go-next", Gtk.IconSize.BUTTON))

    # ── tabs ─────────────────────────────────────────────────
    def _active_tab_note_id(self) -> Optional[str]:
        page_num = self.notebook.get_current_page()
        if page_num < 0:
            return None
        page = self.notebook.get_nth_page(page_num)
        return getattr(page, "_note_id", None)

    def _find_tab_page(self, note_id: str) -> int:
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if getattr(page, "_note_id", None) == note_id:
                return i
        return -1

    def _open_note_in_tab(self, note_id: str, note_title: str = "", kind: str = "note") -> None:
        if self._ui_locked:
            return
        if note_id == self._current_note_id:
            return

        self._autosave_now(silent=True)

        existing = self._find_tab_page(note_id)
        if existing >= 0:
            self._tab_switching = True
            self.notebook.set_current_page(existing)
            self._tab_switching = False
            self._load_note(note_id)
            return

        is_fav = False
        for row in self.store:
            if row[0] == note_id:
                is_fav = bool(row[4])
                break

        tab_label_box = Gtk.Box(spacing=4)
        title_lbl = Gtk.Label()
        self._set_tab_label_text(title_lbl, note_title, is_fav)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_lbl.set_max_width_chars(28)

        title_eb = Gtk.EventBox()
        title_eb.set_visible_window(True)
        title_eb.add(title_lbl)
        title_eb.connect("button-press-event", self._on_tab_button_press)
        tab_label_box.pack_start(title_eb, True, True, 0)

        close_lbl = Gtk.Label(label=" ✕ ")
        close_eb = Gtk.EventBox()
        close_eb.set_visible_window(True)
        close_eb.set_tooltip_text("Fechar aba")
        close_eb.add(close_lbl)
        close_eb.connect("button-press-event", self._on_tab_close_press)
        tab_label_box.pack_start(close_eb, False, False, 0)
        tab_label_box.show_all()

        page = Gtk.Box()
        page._note_id = note_id
        page._note_kind = kind
        page._tab_title = title_lbl
        page._note_fav = is_fav
        page.show()

        self.notebook.append_page(page, tab_label_box)
        self.notebook.set_show_tabs(True)
        self._open_tabs[note_id] = {"title": note_title, "kind": kind}

        self._tab_switching = True
        self.notebook.set_current_page(self.notebook.get_n_pages() - 1)
        self._tab_switching = False
        self._load_note(note_id)

    def _find_tab_by_child(self, widget: Gtk.Widget) -> int:
        for i in range(self.notebook.get_n_pages()):
            tab = self.notebook.get_tab_label(self.notebook.get_nth_page(i))
            if tab is None:
                continue
            if widget is tab or tab.is_ancestor(widget):
                return i
        w = widget.get_parent()
        while w is not None:
            for i in range(self.notebook.get_n_pages()):
                if self.notebook.get_tab_label(self.notebook.get_nth_page(i)) is w:
                    return i
            w = w.get_parent()
        return -1

    def _on_tab_close_press(self, eb: Gtk.EventBox, event: Gdk.EventButton) -> bool:
        if event.button == 3:
            self._context_tab_page = self._find_tab_by_child(eb)
            if self._context_tab_page >= 0:
                self._tab_context_menu.popup(None, None, None, None, event.button, event.time)
            return True
        if event.button != 1:
            return False
        idx = self._find_tab_by_child(eb)
        if idx >= 0:
            self._close_tab(idx)
            return True
        return False

    def _on_tab_button_press(self, widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        idx = self._find_tab_by_child(widget)
        if idx >= 0:
            self._context_tab_page = idx
            self._tab_context_menu.popup(None, None, None, None, event.button, event.time)
            return True
        return False

    def _on_context_close_tab(self) -> None:
        if self._context_tab_page >= 0:
            self._close_tab(self._context_tab_page)

    def _on_context_close_all(self) -> None:
        for i in range(self.notebook.get_n_pages() - 1, -1, -1):
            self._close_tab(i)

    def _on_context_close_left(self) -> None:
        for i in range(self._context_tab_page - 1, -1, -1):
            self._close_tab(i)

    def _on_context_close_right(self) -> None:
        start = self._context_tab_page + 1
        for i in range(self.notebook.get_n_pages() - 1, start - 1, -1):
            self._close_tab(i)

    def _on_context_move_left(self) -> None:
        n = self._context_tab_page
        if n > 0:
            page = self.notebook.get_nth_page(n)
            self.notebook.reorder_child(page, n - 1)
            self._context_tab_page = n - 1

    def _on_context_move_right(self) -> None:
        n = self._context_tab_page
        if n < self.notebook.get_n_pages() - 1:
            page = self.notebook.get_nth_page(n)
            self.notebook.reorder_child(page, n + 1)
            self._context_tab_page = n + 1

    def _close_tab(self, page_num: int) -> None:
        if page_num < 0 or page_num >= self.notebook.get_n_pages():
            return
        page = self.notebook.get_nth_page(page_num)
        note_id = getattr(page, "_note_id", None)

        was_active = (self.notebook.get_current_page() == page_num)

        if was_active and note_id and self._current_note_id:
            self._autosave_now(silent=True)

        if note_id:
            self._open_tabs.pop(note_id, None)

        self._tab_switching = True
        self.notebook.remove_page(page_num)
        self._tab_switching = False

        if self.notebook.get_n_pages() == 0:
            self._current_note_id = None
            self._current_kind = "note"
            self._go_home()
        elif was_active:
            new_page = min(page_num, self.notebook.get_n_pages() - 1)
            new_note_id = getattr(self.notebook.get_nth_page(new_page), "_note_id", None)
            if new_note_id:
                self._load_note(new_note_id)

    def _on_tab_switch(self, _notebook: Gtk.Notebook, page: Gtk.Box, page_num: int) -> None:
        if self._tab_switching or self._loading_note:
            return
        note_id = getattr(page, "_note_id", None)
        if not note_id or note_id == self._current_note_id:
            return
        self._autosave_now(silent=True)
        self._load_note(note_id)

    def _update_tab_title(self, note_id: str, title: str) -> None:
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if getattr(page, "_note_id", None) == note_id:
                lbl = getattr(page, "_tab_title", None)
                if lbl:
                    fav = getattr(page, "_note_fav", False)
                    self._set_tab_label_text(lbl, title, fav)
                if note_id in self._open_tabs:
                    self._open_tabs[note_id]["title"] = title
                return

    def _set_tab_label_text(self, lbl: Gtk.Label, title: str, fav: bool) -> None:
        text = (title or "Sem título")[:40]
        if fav:
            lbl.set_markup(f'<span foreground="#b8860b" weight="bold">★ {GLib.markup_escape_text(text)}</span>')
        else:
            lbl.set_text(text)

    def _update_tab_fav_style(self, note_id: str, fav: bool) -> None:
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            if getattr(page, "_note_id", None) == note_id:
                page._note_fav = fav
                lbl = getattr(page, "_tab_title", None)
                if lbl:
                    title = self._open_tabs.get(note_id, {}).get("title", "Sem título")
                    self._set_tab_label_text(lbl, title, fav)
                return

    def _fmt(self, what: str) -> None:
        if self._current_kind != "note" or self._ui_locked:
            return
        if what == "bold":
            self.html_editor.exec_cmd("bold")
        elif what == "h1":
            self.html_editor.exec_cmd("formatBlock", "h1")
        elif what == "ul":
            self.html_editor.exec_cmd("insertUnorderedList")

    def _refresh_all(self) -> None:
        self._refresh_notes()
        self._refresh_dashboard()

    # ── notes list / editor ──────────────────────────────────
    def _refresh_notes(self) -> None:
        if self._ui_locked:
            return
        self._refreshing_notes = True
        try:
            uh = self._user_hash()
            q = self.search_entry.get_text().strip() or None
            self._note_list = self.notes.list_notes(uh, query=q)
            if self._current_view_kind and self._current_view_kind != "event":
                self._note_list = [n for n in self._note_list if (n.get("kind") or "note") == self._current_view_kind]
            self._note_list.sort(key=lambda n: (0 if n.get("favorite") else 1, n.get("updated_at") or ""), reverse=False)
            self._note_owner = {}
            self.store.clear()
            for n in self._note_list:
                updated = (n.get("updated_at") or "")[:19].replace("T", " ")
                title = n.get("title") or t("untitled")
                kind = n.get("kind") or "note"
                if n.get("source") == "peer":
                    self._note_owner[n["entity_id"]] = n.get("peer_hash", uh)
                else:
                    self._note_owner[n["entity_id"]] = uh
                if kind == "tasklist":
                    open_c = n.get("task_open_count")
                    if open_c is None:
                        prefix = f"☑ {t('kind_tasklist')}: "
                    else:
                        prefix = f"☑ [{open_c}] "
                    title = prefix + title
                elif kind == "agent_task":
                    st = n.get("agent_status") or "?"
                    ag = n.get("agent") or "agent"
                    title = f"🤖 [{st}] {ag}: {title}"
                elif n.get("source") == "shared":
                    title = f"[shared] {title}"
                markers = n.get("markers") or []
                if markers and not title.startswith("🤖") and not title.startswith("☑"):
                    title = f"{title}  {' '.join(markers[:3])}"
                self.store.append([n["entity_id"], title, updated, kind, bool(n.get("favorite"))])
            if self._current_note_id:
                self._select_id(self._current_note_id)
            q = self.search_entry.get_text().strip()
            self._set_status(f"{len(self._note_list)} notas" + (f" · busca: {q}" if q else ""))
        except Exception as e:
            log_exception(_log, "Erro ao pesquisar notas", e)
            self._set_status(f"Erro: {e}")
        finally:
            self._refreshing_notes = False

    def _on_select(self, selection) -> None:
        if self._ui_locked or self._loading_note or self._refreshing_notes:
            return
        model, it = selection.get_selected()
        if not it:
            return
        note_id = model[it][0]
        if note_id == self._current_note_id:
            return
        title = model[it][1] or ""
        kind = model[it][3] or "note"
        self._open_note_in_tab(note_id, title, kind)

    def _tree_cell_data(self, _col, renderer, model, it, _data) -> None:
        favorite = model[it][4]
        if favorite:
            renderer.set_property("foreground", "#b8860b")
            renderer.set_property("weight", Pango.Weight.BOLD)
        else:
            renderer.set_property("foreground", None)
            renderer.set_property("weight", Pango.Weight.NORMAL)

    def _on_tree_button_press(self, tree: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        path_info = tree.get_path_at_pos(int(event.x), int(event.y))
        if path_info:
            path, _col, _cx, _cy = path_info
            sel = tree.get_selection()
            if not sel.path_is_selected(path):
                sel.unselect_all()
                sel.select_path(path)
            self._context_tree_note_ids = self._get_selected_note_ids()
            model = tree.get_model()
            has_fav = False
            all_fav = True
            for nid in self._context_tree_note_ids:
                for row in model:
                    if row[0] == nid:
                        if row[4]:
                            has_fav = True
                        else:
                            all_fav = False
                        break
            self._tree_context_menu.get_children()[0].set_visible(not all_fav)
            self._tree_context_menu.get_children()[1].set_visible(has_fav)
            self._tree_context_menu.popup_at_pointer(event)
            return True
        return False

    def _get_selected_note_ids(self) -> list:
        sel = self.tree.get_selection()
        try:
            model, paths = sel.get_selected_rows()
        except Exception:
            model, it = sel.get_selected()
            return [model[it][0]] if it else []
        if not paths:
            return []
        return [model[model.get_iter(p)][0] for p in paths]

    def _toggle_tree_favorite(self, fav: bool) -> None:
        note_ids = getattr(self, "_context_tree_note_ids", [])
        for nid in note_ids:
            self._toggle_favorite(nid, fav)

    def _tree_context_delete(self) -> None:
        note_ids = getattr(self, "_context_tree_note_ids", [])
        if not note_ids:
            return
        n = len(note_ids)
        label = f"Excluir {n} nota(s)?" if n > 1 else t("delete") + "?"
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=label,
        )
        if dialog.run() == Gtk.ResponseType.OK:
            for nid in note_ids:
                self._delete_note(nid)
        dialog.destroy()

    def _on_side_fav_clicked(self) -> None:
        if not self._current_note_id or self._ui_locked:
            return
        note = self.notes.get_note(self._user_hash(), self._current_note_id, include_body=False)
        fav = bool(note.get("favorite"))
        self._toggle_favorite(self._current_note_id, not fav)

    def _toggle_favorite(self, note_id: str, fav: bool) -> None:
        if not self._require_unlocked():
            return
        self.notes.update_note(
            self._user_hash(),
            note_id,
            extra_payload={"favorite": fav},
        )
        self._refresh_notes()
        self._update_tab_fav_style(note_id, fav)
        if note_id == self._current_note_id:
            note = self.notes.get_note(self._user_hash(), note_id, include_body=False)
            self._fill_side_panel(note)

    def _open_note_by_id(self, note_id: str) -> None:
        if self._ui_locked:
            return
        if self._opening_note:
            return
        self._opening_note = True
        try:
            self._ensure_workspace_visible()
            try:
                note = self.notes.get_note(self._user_hash(), note_id, include_body=False)
                title = note.get("title") or ""
                kind = note.get("kind") or "note"
            except KeyError:
                title, kind = "", "note"
            self._open_note_in_tab(note_id, title, kind)
        finally:
            self._opening_note = False

    def _ensure_workspace_visible(self) -> None:
        if self._stack.get_visible_child_name() != "workspace":
            self._stack.set_visible_child_name("workspace")
        self._refresh_notes()

    def _load_note(self, note_id: str) -> None:
        if self._ui_locked:
            return
        self._loading_note = True
        try:
            try:
                owner_hash = getattr(self, "_note_owner", {}).get(note_id, self._user_hash())
                note = self.notes.get_note(owner_hash, note_id, include_body=True)
            except KeyError:
                return
            self._current_note_id = note_id
            self._current_note_owner = owner_hash
            self._current_kind = note.get("kind") or "note"
            self._set_editor_chrome_visible(True)
            self._select_id(note_id)
            self._update_tab_title(note_id, note.get("title") or "")
            self.title_entry.set_text(note.get("title") or "")
            markers = note.get("markers") or []
            self.markers_entry.set_text(" ".join(markers))
            body = note.get("body") or ""
            if self._current_kind == "tasklist":
                self.task_editor.load_from_body(body)
                self._editor_stack.set_visible_child_name("tasklist")
            elif self._current_kind == "agent_task":
                self.agent_editor.load_full(body)
                self._editor_stack.set_visible_child_name("agent_task")
            else:
                self.html_editor.set_html(body)
                self._editor_stack.set_visible_child_name("note")
            files = note.get("file_hashes") or []
            kind_map = {
                "tasklist": t("kind_tasklist"),
                "agent_task": "Agente",
                "note": t("kind_note"),
            }
            kind_label = kind_map.get(self._current_kind, self._current_kind)
            self.meta_label.set_text(
                f"{kind_label} · id: {note_id[:12]}… · host: {note.get('updated_by_host', '?')} · "
                f"files: {len(files)}"
            )
            self._fill_side_panel(note)
        finally:
            self._loading_note = False

    def _fill_side_panel(self, note: dict) -> None:
        created = (note.get("created_at") or note.get("gnote_create_date") or "—")
        updated = (note.get("updated_at") or "—")
        self._side_created.set_text(f"Criada: {str(created)[:22].replace('T', ' ')}")
        self._side_updated.set_text(f"Atualizada: {str(updated)[:22].replace('T', ' ')}")
        host = note.get("created_by_host") or note.get("updated_by_host") or "?"
        machine = (note.get("updated_by_machine") or note.get("created_by_machine") or "")[:12]
        self._side_host.set_text(
            f"Host: {host}\nMáquina: {machine}"
        )
        owner_hash = self._current_note_owner or self._user_hash()
        if owner_hash != self._user_hash():
            self._side_host.set_text(
                f"Origem: outra máquina ({owner_hash[:12]}…)\n"
                f"Host: {host}\nMáquina: {machine}"
            )
        markers = note.get("markers") or []
        self._side_markers.set_text("Marcadores: " + (" ".join(markers) if markers else "—"))
        fav = note.get("favorite") or False
        if fav:
            self._side_fav_btn.set_label("★ Remover favorito")
        else:
            self._side_fav_btn.set_label("☆ Salvar como favorito")
        self._hist_store.clear()
        try:
            hist = self.notes.history_grouped(owner_hash, note["entity_id"])
        except Exception:
            hist = []
        for b in reversed(hist[-40:]):
            when = (b.get("timestamp") or "")[:19].replace("T", " ")
            action = b.get("action") or ""
            host_b = b.get("hostname") or ""
            gsz = int(b.get("group_size") or 1)
            if gsz > 1:
                label = f"{when} @{host_b} (×{gsz})"
            else:
                label = f"{when} @{host_b}"
            # mark checkpoint versions clearly
            act = action
            if b.get("payload", {}).get("checkpoint"):
                act = f"◆ {action}"
            self._hist_store.append([b.get("block_hash") or "", label, act])

    def _on_hist_activated(self, _tree, path, _col) -> None:
        it = self._hist_store.get_iter(path)
        block_hash = self._hist_store[it][0]
        if block_hash:
            self._preview_or_revert(block_hash)

    def _revert_selected_side(self) -> None:
        model, it = self._hist_tree.get_selection().get_selected()
        if not it or not self._current_note_id:
            return
        block_hash = model[it][0]
        self._preview_or_revert(block_hash)

    def _preview_or_revert(self, block_hash: str) -> None:
        if not self._current_note_id:
            return
        ask = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Reverter esta nota para a versão selecionada?",
        )
        if ask.run() != Gtk.ResponseType.OK:
            ask.destroy()
            return
        ask.destroy()
        try:
            self.notes.revert(self._user_hash(), self._current_note_id, block_hash)
            self._load_note(self._current_note_id)
            self._refresh_all()
            self._set_status("Revertido")
        except Exception as e:  # noqa: BLE001
            self._msg(str(e))

    def _parse_markers_field(self) -> list:
        raw = self.markers_entry.get_text() or ""
        parts = [p for p in raw.replace(",", " ").split() if p.strip()]
        return normalize_markers(parts)

    def _on_markers_changed(self) -> None:
        try:
            self._schedule_autosave()
        except Exception as e:
            log_exception(_log, "Erro ao processar mudança nos marcadores", e)

    def _select_id(self, note_id: str) -> None:
        if self._ui_locked:
            return
        for i, row in enumerate(self.store):
            if row[0] == note_id:
                self.tree.get_selection().select_path(Gtk.TreePath.new_from_indices([i]))
                break

    def _new_note(self) -> None:
        if not self._require_unlocked():
            return
        self._autosave_now(silent=True)
        note = self.notes.create_note(
            self._user_hash(),
            title=t("new_note"),
            body="<h1>Título</h1><p>Escreva aqui…</p>",
            kind="note",
        )
        self._refresh_dashboard()
        self._open_note_by_id(note["entity_id"])

    def _new_tasklist(self) -> None:
        if not self._require_unlocked():
            return
        self._autosave_now(silent=True)
        note = self.tasks.create_tasklist(self._user_hash(), title=t("new_tasklist"))
        self._refresh_dashboard()
        self._open_note_by_id(note["entity_id"])

    def _task_list_id(self) -> Optional[str]:
        if self._current_kind != "tasklist" or not self._current_note_id:
            return None
        return self._current_note_id

    def _task_create_note(self, task_id: str) -> None:
        list_id = self._task_list_id()
        if not list_id:
            return
        # persist current rows first
        self._autosave_now(silent=True)
        try:
            note = self.tasks.create_linked_note(self._user_hash(), list_id, task_id)
            self.task_editor.set_linked_note(task_id, note["entity_id"])
            self._autosave_now(silent=True)
            self._refresh_notes()
            ask = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Nota criada e vinculada. Abrir agora?",
            )
            if ask.run() == Gtk.ResponseType.YES:
                ask.destroy()
                self._open_note_by_id(note["entity_id"])
            else:
                ask.destroy()
                self._set_status("Nota vinculada à tarefa")
        except Exception as e:  # noqa: BLE001
            self._msg(str(e))

    def _task_add_progress(self, task_id: str) -> None:
        list_id = self._task_list_id()
        if not list_id:
            return
        dialog = Gtk.Dialog(title="Novo andamento", transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_default_size(480, 280)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(Gtk.Label(label="Descreva o andamento da tarefa:", xalign=0), False, False, 0)
        title_e = Gtk.Entry()
        title_e.set_placeholder_text("Título (opcional)")
        box.pack_start(title_e, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll.add(tv)
        box.pack_start(scroll, True, True, 0)
        dialog.show_all()
        if dialog.run() != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        buf = tv.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        title = title_e.get_text().strip() or None
        dialog.destroy()
        self._autosave_now(silent=True)
        try:
            prog = self.tasks.add_progress(
                self._user_hash(), list_id, task_id, text=text, title=title
            )
            # reload task editor body so progress_ids stick
            full = self.notes.get_note(self._user_hash(), list_id, include_body=True)
            self.task_editor.load_from_body(full.get("body") or "")
            self._set_status(f"Andamento registrado ({prog['entity_id'][:8]}…)")
            self._refresh_dashboard()
        except Exception as e:  # noqa: BLE001
            self._msg(str(e))

    def _task_view_progress(self, task_id: str) -> None:
        list_id = self._task_list_id()
        if not list_id:
            return
        try:
            items = self.tasks.list_progress(self._user_hash(), list_id, task_id)
        except Exception as e:  # noqa: BLE001
            self._msg(str(e))
            return
        dialog = Gtk.Dialog(title="Andamentos da tarefa", transient_for=self, flags=0)
        dialog.add_buttons(
            "Novo andamento",
            Gtk.ResponseType.APPLY,
            Gtk.STOCK_CLOSE,
            Gtk.ResponseType.CLOSE,
        )
        dialog.set_default_size(520, 360)
        store = Gtk.ListStore(str, str, str)  # id, when, title
        for n in items:
            when = (n.get("created_at") or n.get("updated_at") or "")[:19].replace("T", " ")
            store.append([n["entity_id"], when, n.get("title") or ""])
        tree = Gtk.TreeView(model=store)
        tree.append_column(Gtk.TreeViewColumn("Quando", Gtk.CellRendererText(), text=1))
        tree.append_column(Gtk.TreeViewColumn("Título", Gtk.CellRendererText(), text=2))
        scroll = Gtk.ScrolledWindow()
        scroll.add(tree)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        # body preview
        preview = Gtk.TextView()
        preview.set_editable(False)
        preview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        pscroll = Gtk.ScrolledWindow()
        pscroll.set_min_content_height(120)
        pscroll.add(preview)
        dialog.get_content_area().pack_start(pscroll, False, False, 0)

        def on_sel(sel):
            m, it = sel.get_selected()
            if not it:
                return
            nid = m[it][0]
            try:
                note = self.notes.get_note(self._user_hash(), nid, include_body=True)
                preview.get_buffer().set_text(note.get("body") or "")
            except KeyError:
                preview.get_buffer().set_text("")

        tree.get_selection().connect("changed", on_sel)
        dialog.show_all()
        while True:
            resp = dialog.run()
            if resp == Gtk.ResponseType.APPLY:
                dialog.destroy()
                self._task_add_progress(task_id)
                return
            break
        dialog.destroy()

    def _task_add_subtask(self, parent_task_id: str) -> None:
        list_id = self._task_list_id()
        if not list_id:
            return
        dialog = Gtk.Dialog(title="Nova subtarefa", transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Texto da subtarefa")
        box.pack_start(entry, False, False, 0)
        due_e = Gtk.Entry()
        due_e.set_placeholder_text("Data conclusão AAAA-MM-DD (opcional)")
        box.pack_start(due_e, False, False, 0)
        dialog.show_all()
        if dialog.run() != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        text = entry.get_text().strip() or "Subtarefa"
        due = due_e.get_text().strip() or None
        dialog.destroy()
        self._autosave_now(silent=True)
        try:
            self.tasks.add_subtask(
                self._user_hash(), list_id, parent_task_id, text=text, due_date=due
            )
            full = self.notes.get_note(self._user_hash(), list_id, include_body=True)
            self.task_editor.load_from_body(full.get("body") or "")
            self._set_status("Subtarefa criada")
            self._refresh_dashboard()
        except Exception as e:  # noqa: BLE001
            self._msg(str(e))

    def _new_agent_task(self) -> None:
        if not self._require_unlocked():
            return
        self._autosave_now(silent=True)
        note = self.agents.create(
            self._user_hash(),
            title="Tarefa para agente",
            description="Descreva o que o agente deve fazer…",
            agent="grok",
        )
        self._refresh_dashboard()
        self._open_note_by_id(note["entity_id"])

    def _play_agent_subtask(self, sub_id: str) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        if self._current_kind != "agent_task":
            return
        self._autosave_now(silent=True)
        note_id = self._current_note_id
        base = getattr(self.agent_editor, "_base", {}) or {}
        parent_desc = base.get("description", "")
        subtasks = base.get("subtasks", [])
        sub = next((s for s in subtasks if s.get("id") == sub_id), {})
        sub_desc = sub.get("description", "")
        prompt = f"Contexto da tarefa principal:\n{parent_desc}\n\nTarefa específica:\n{sub_desc}"
        edited = self._confirm_agent_prompt(prompt, "Confirmar prompt da subtarefa")
        if edited is None:
            return
        self._agent_note_id = note_id
        self.agent_editor.set_running(True)
        self._start_agent_timer()
        self._start_agent_flush()

        def on_chunk(chunk: str) -> None:
            GLib.idle_add(self._on_subtask_chunk, chunk)

        def work():
            try:
                result = self.agents.run_agent(
                    self._user_hash(), note_id, timeout=600,
                    on_output=on_chunk, subtask_id=sub_id,
                    prompt_override=edited,
                )
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            GLib.idle_add(self._after_subtask_run, result, note_id, sub_id)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _on_subtask_chunk(self, chunk: str) -> bool:
        self.agent_editor.append_output(chunk)
        return False

    def _after_subtask_run(self, result: dict, note_id: str, sub_id: str) -> bool:
        self._stop_agent_timer()
        self._cancel_agent_flush()
        self._agent_note_id = None
        self.agent_editor.set_running(False)
        self._load_note(note_id)
        self._refresh_all()
        if result.get("ok"):
            self._set_agent_label("✓ Subtarefa concluída", "#9ece6a")
            self._set_status("Subtarefa concluída — output salvo")
        else:
            reason = result.get("reason") or result.get("error") or "falha"
            self._set_agent_label(f"✗ Subtarefa: {reason}", "#f7768e")
            self._set_status(f"Subtarefa: {reason}")
        GLib.timeout_add_seconds(6, self._clear_agent_label)
        return False

    def _confirm_agent_prompt(self, prompt: str, title: str = "Confirmar prompt") -> Optional[str]:
        """Show dialog with editable prompt. Returns edited prompt or None if cancelled."""
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Executar", Gtk.ResponseType.OK)
        dialog.set_default_size(600, 400)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        box.pack_start(Gtk.Label(label="Prompt que será enviado ao agente:", xalign=0), False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.get_buffer().set_text(prompt)
        scroll.add(tv)
        box.pack_start(scroll, True, True, 0)

        dialog.show_all()
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return None

        buf = tv.get_buffer()
        edited = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        dialog.destroy()
        return edited.strip() or None

    def _play_agent_task(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        if self._current_kind != "agent_task":
            return
        self._autosave_now(silent=True)
        note_id = self._current_note_id
        prompt = self.agent_editor.get_data().get("description", "").strip()
        if not prompt:
            self._set_status("A descrição da tarefa está vazia", False)
            return
        edited = self._confirm_agent_prompt(prompt, "Confirmar prompt do agente")
        if edited is None:
            return
        self._agent_note_id = note_id
        self.agent_editor.set_running(True)
        self._start_agent_timer()
        self._start_agent_flush()

        def on_chunk(chunk: str) -> None:
            GLib.idle_add(self._on_agent_chunk, chunk)

        def work():
            try:
                result = self.agents.run_agent(
                    self._user_hash(), note_id, timeout=600, on_output=on_chunk,
                    prompt_override=edited,
                )
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "error": str(e)}
            GLib.idle_add(self._after_agent_run, result, note_id)

        import threading

        threading.Thread(target=work, daemon=True).start()

    def _on_agent_chunk(self, chunk: str) -> bool:
        self.agent_editor.append_output(chunk)
        return False

    def _cancel_agent_task(self) -> None:
        self.agents.cancel()
        self._set_status("Cancelando agente…")

    def _after_agent_run(self, result: dict, note_id: str) -> bool:
        self._stop_agent_timer()
        self._cancel_agent_flush()
        self._agent_note_id = None
        self.agent_editor.set_running(False)
        self._load_note(note_id)
        self._refresh_all()
        if result.get("ok"):
            self._set_agent_label("✓ Agente concluído", "#9ece6a")
            self._set_status("Agente concluído — output salvo")
        else:
            reason = result.get("reason") or result.get("error") or "falha"
            self._set_agent_label(f"✗ Agente: {reason}", "#f7768e")
            self._set_status(f"Agente: {reason} (status/output atualizados)")
        GLib.timeout_add_seconds(6, self._clear_agent_label)
        return False

    def _start_agent_timer(self) -> None:
        import time

        self._agent_start_time = time.time()
        self._set_agent_label("🤖 Executando agente... [0s]", "#e0af68")
        self._cancel_agent_timer()
        self._agent_timer_id = GLib.timeout_add(1000, self._tick_agent_timer)

    def _tick_agent_timer(self) -> bool:
        import time

        elapsed = int(time.time() - self._agent_start_time)
        m = elapsed // 60
        s = elapsed % 60
        ts = f"{m}m{s:02d}s" if m else f"{s}s"
        self._set_agent_label(f"🤖 Executando agente... [{ts}]", "#e0af68")
        return True

    def _set_agent_label(self, text: str, color: str) -> None:
        self.agent_status_label.set_markup(
            f'<span foreground="{color}" weight="bold">{GLib.markup_escape_text(text)}</span>'
        )
        self.agent_status_label.show()

    def _clear_agent_label(self) -> bool:
        self.agent_status_label.hide()
        return False

    def _cancel_agent_timer(self) -> None:
        if self._agent_timer_id is not None:
            try:
                GLib.source_remove(self._agent_timer_id)
            except Exception:
                pass
            self._agent_timer_id = None

    def _stop_agent_timer(self) -> None:
        self._cancel_agent_timer()

    def _start_agent_flush(self) -> None:
        self._cancel_agent_flush()
        self._agent_flush_id = GLib.timeout_add(5000, self._flush_agent_output)

    def _cancel_agent_flush(self) -> None:
        if self._agent_flush_id is not None:
            try:
                GLib.source_remove(self._agent_flush_id)
            except Exception:
                pass
            self._agent_flush_id = None

    def _flush_agent_output(self) -> bool:
        nid = self._agent_note_id
        if not nid:
            self._agent_flush_id = None
            return False
        try:
            data = self.agents.get_data(self._user_hash(), nid)
            data.pop("_note", None)
            body = self.agent_editor.to_body(data)
            from gltd_notes.services.agent_tasks import parse_agent_body
            self.agents.save_data(self._user_hash(), nid, parse_agent_body(body))
        except Exception:
            pass
        self._agent_flush_id = GLib.timeout_add(5000, self._flush_agent_output)
        return False

    def _add_related_inline(self, title: str, description: str, agent: str) -> Optional[dict]:
        return None

    def _agent_nav_to_child(self, child_note_id: str) -> None:
        if not self._current_note_id:
            return
        self._autosave_now(silent=True)
        current_body = self.agent_editor.to_body()
        self._agent_nav_stack.append((self._current_note_id, current_body))
        try:
            cnote = self.notes.get_note(self._user_hash(), child_note_id, include_body=True)
        except KeyError:
            return
        self._current_note_id = child_note_id
        self._current_kind = "agent_task"
        self.agent_editor.load_full(cnote.get("body") or "{}")
        self.agent_editor.hide_nav_bar()
        self.agent_editor.show_nav_bar(cnote.get("title") or "Subtarefa")
        self.title_entry.set_text(cnote.get("title") or "")
        markers = cnote.get("markers") or []
        self.markers_entry.set_text(" ".join(markers))
        self._fill_side_panel(cnote)
        self.meta_label.set_text(f"id: {child_note_id[:12]}… · agente: subtarefa")

    def _agent_nav_back(self) -> None:
        self._autosave_now(silent=True)
        if self._agent_nav_stack:
            parent_id, parent_body = self._agent_nav_stack.pop()
            self._current_note_id = parent_id
            self._current_kind = "agent_task"
            self.agent_editor.load_full(parent_body)
            self.agent_editor.hide_nav_bar()
            try:
                pnote = self.notes.get_note(self._user_hash(), parent_id, include_body=False)
                self.title_entry.set_text(pnote.get("title") or "")
                markers = pnote.get("markers") or []
                self.markers_entry.set_text(" ".join(markers))
                self._fill_side_panel(pnote)
            except KeyError:
                pass
        self._refresh_all()

    def _clear_agent_output(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        if self._current_kind != "agent_task":
            return
        self.agent_editor.clear_output()
        self._schedule_autosave()
        self._set_status("Output limpo")

    def _run_auto_markers(self) -> None:
        if not self._require_unlocked():
            return
        self._set_status("Gerando marcadores…")

        def work():
            try:
                report = self.auto_markers.analyze_and_apply(self._user_hash(), only_missing=True)
            except Exception as e:  # noqa: BLE001
                report = {"error": str(e)}
            GLib.idle_add(self._after_auto_markers, report)

        import threading

        threading.Thread(target=work, daemon=True).start()

    def _after_auto_markers(self, report: dict) -> bool:
        if report.get("error"):
            self._msg(report["error"])
            return False
        self._refresh_all()
        if self._current_note_id:
            try:
                self._load_note(self._current_note_id)
            except Exception:
                pass
        self._msg(
            f"Marcadores aplicados em {report.get('updated', 0)} notas "
            f"(ignoradas: {report.get('skipped', 0)})."
        )
        return False

    # ── autosave ─────────────────────────────────────────────
    def _schedule_autosave(self) -> None:
        if self._loading_note or self._ui_locked or not self._current_note_id:
            return
        self._cancel_autosave()
        ms = int(self.config.data.get("gui", {}).get("autosave_ms") or 4000)
        self._autosave_id = GLib.timeout_add(ms, self._autosave_timeout)

    def _cancel_autosave(self) -> None:
        if self._autosave_id is not None:
            try:
                GLib.source_remove(self._autosave_id)
            except Exception:
                pass
            self._autosave_id = None

    def _autosave_timeout(self) -> bool:
        self._autosave_id = None
        self._autosave_now(silent=False)
        return False

    def _autosave_now(self, silent: bool = False) -> None:
        if self._ui_locked or not self._current_note_id or self._loading_note:
            return
        title = self.title_entry.get_text()
        markers = self._parse_markers_field()
        note_id = self._current_note_id
        kind = self._current_kind
        owner = self._current_note_owner or self._user_hash()

        def finish_ok() -> None:
            if not silent:
                self._set_status(t("autosaved"))
                cur = self._current_note_id
                self._refresh_notes()
                self._refresh_dashboard()
                if cur:
                    self._select_id(cur)

        try:
            if kind == "tasklist":
                tasks = self.task_editor.get_tasks()
                self.tasks.save_tasks(owner, note_id, tasks, title=title)
                self.notes.update_note(
                    owner,
                    note_id,
                    extra_payload={"markers": markers},
                    kind="tasklist",
                )
                finish_ok()
            elif kind == "agent_task":
                base = getattr(self.agent_editor, "_base", None) or {}
                body = self.agent_editor.to_body(base)
                data = parse_agent_body(body)
                for k in ("parent_id", "related_ids", "executed_at"):
                    if base.get(k) is not None and not data.get(k):
                        data[k] = base[k]
                self.agents.save_data(owner, note_id, data, title=title)
                self.notes.update_note(
                    owner,
                    note_id,
                    extra_payload={"markers": markers},
                    kind="agent_task",
                )
                finish_ok()
            else:
                # HTML body via WebKit (async)
                def got_html(html: str) -> None:
                    try:
                        if self._current_note_id != note_id:
                            return
                        self.notes.update_note(
                            owner,
                            note_id,
                            title=title,
                            body=html or "",
                            kind="note",
                            extra_payload={"markers": markers},
                        )
                        finish_ok()
                    except Exception as e:
                        log_exception(_log, "Erro no autosave HTML", e)
                        self._set_status(f"autosave error: {e}")

                self.html_editor.get_html_async(got_html)
        except Exception as e:
            log_exception(_log, "Erro no autosave", e)
            self._set_status(f"autosave error: {e}")

    def _save_current(self) -> None:
        if not self._require_unlocked():
            return
        if not self._current_note_id:
            self._new_note()
            return
        self._autosave_now(silent=False)

    def _delete_current(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=t("delete") + "?",
        )
        if dialog.run() == Gtk.ResponseType.OK:
            self._delete_note(self._current_note_id)
        dialog.destroy()

    def _delete_note(self, note_id: str) -> None:
        self._cancel_autosave()
        self._cancel_agent_timer()
        self._cancel_agent_flush()
        self._agent_note_id = None
        was_current = (note_id == self._current_note_id)
        owner = getattr(self, "_note_owner", {}).get(note_id, self._user_hash())
        self._current_note_id = None
        self.notes.delete_note(owner, note_id)
        self._refresh_all()
        page = self._find_tab_page(note_id)
        if page >= 0:
            self._close_tab(page)
        elif was_current:
            self.title_entry.set_text("")
            self.html_editor.clear()
            self.task_editor.load_from_body('{"tasks":[]}')
            self._go_home()

    def _share_current(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        users = [u for u in self.config.list_users() if u["user_hash"] != self._user_hash()]
        if not users:
            self._msg("No other local users")
            return
        dialog = Gtk.Dialog(title=t("share"), transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        checks = []
        for u in users:
            cb = Gtk.CheckButton(label=f"{u['username']}")
            cb._user_hash = u["user_hash"]  # type: ignore[attr-defined]
            box.pack_start(cb, False, False, 4)
            checks.append(cb)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            targets = [c._user_hash for c in checks if c.get_active()]  # type: ignore[attr-defined]
            if targets:
                self.notes.share_note(self._user_hash(), self._current_note_id, targets)
                self._load_note(self._current_note_id)
        dialog.destroy()

    def _attach_file(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        dialog = Gtk.FileChooserDialog(
            title=t("attach"), parent=self, action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            self.notes.attach_file(self._user_hash(), self._current_note_id, dialog.get_filename())
            self._load_note(self._current_note_id)
        dialog.destroy()

    def _history_dialog(self) -> None:
        if not self._require_unlocked() or not self._current_note_id:
            return
        hist = self.notes.history_grouped(self._user_hash(), self._current_note_id)
        dialog = Gtk.Dialog(title=t("history"), transient_for=self, flags=0)
        dialog.set_default_size(640, 400)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        store = Gtk.ListStore(str, str, str, str)
        for b in reversed(hist):
            gsz = int(b.get("group_size") or 1)
            when = (b.get("timestamp") or "")[:19]
            if gsz > 1:
                when = f"{when} (×{gsz} eds)"
            store.append(
                [
                    b.get("block_hash") or "",
                    when,
                    b.get("hostname") or "",
                    b.get("action") or "",
                ]
            )
        tree = Gtk.TreeView(model=store)
        for i, title in enumerate(("When", "Host", "Action")):
            tree.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i + 1))
        scroll = Gtk.ScrolledWindow()
        scroll.add(tree)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            model, it = tree.get_selection().get_selected()
            if it:
                self.notes.revert(self._user_hash(), self._current_note_id, model[it][0])
                self._load_note(self._current_note_id)
                self._refresh_all()
        dialog.destroy()

    def _new_event_dialog(self) -> None:
        if not self._require_unlocked():
            return
        dialog = Gtk.Dialog(title=t("new_event"), transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        dialog.get_content_area().pack_start(grid, True, True, 0)
        title_e = Gtk.Entry()
        body_e = Gtk.Entry()
        due_e = Gtk.Entry()
        due_e.set_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        grid.attach(Gtk.Label(label=t("title")), 0, 0, 1, 1)
        grid.attach(title_e, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Body"), 0, 1, 1, 1)
        grid.attach(body_e, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="UTC"), 0, 2, 1, 1)
        grid.attach(due_e, 1, 2, 1, 1)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self.events.create_event(
                self._user_hash(),
                title=title_e.get_text() or t("new_event"),
                body=body_e.get_text() or "",
                due_at=due_e.get_text() or None,
                remind_at=due_e.get_text() or None,
            )
            self.notifier.notify(t("new_event"), title_e.get_text() or "")
            self._refresh_dashboard()
            if self._current_view_kind == "event":
                self._refresh_events_view()
        dialog.destroy()

    def _poll_events(self) -> bool:
        if self._ui_locked:
            return True
        try:
            uh = self._user_hash()
            for ev in self.events.due_for_notification(uh):
                self.notifier.notify(ev.get("title") or "Reminder", "GLTD Notes", urgency="critical")
                self.events.mark_notified(uh, ev["entity_id"])
        except Exception as e:  # noqa: BLE001
            print(f"[events] {e}")
        return True

    def _open_settings(self) -> None:
        if not self._require_unlocked():
            return
        dialog = SettingsDialog(self.config, parent=self)
        while True:
            resp = dialog.run()
            if resp == Gtk.ResponseType.APPLY:
                self.config.load()
                get_i18n(self.config.data.get("gui", {}).get("language") or "auto")
                self._update_lock_ui()
                continue
            break
        dialog.destroy()
        self.config.load()
        get_i18n(self.config.data.get("gui", {}).get("language") or "auto")
        self._update_lock_ui()
        self.set_title(t("app_name"))

    def _open_password_settings(self) -> None:
        if self._ui_locked:
            return
        if not self.config.user_has_password():
            if set_password_prompt(self.config, parent=self):
                self._update_lock_ui()
            return
        self._open_settings()

    def _lock_session(self) -> None:
        if self._ui_locked:
            return
        if not self.config.user_has_password():
            dialog = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=t("set_password"),
            )
            if dialog.run() == Gtk.ResponseType.OK:
                dialog.destroy()
                if set_password_prompt(self.config, parent=self):
                    self._do_lock()
            else:
                dialog.destroy()
            return
        self._do_lock()

    def _do_lock(self) -> None:
        self._autosave_now(silent=True)
        try:
            self.ctx.auth.lock()
        except PermissionError as e:
            self._msg(str(e))
            return
        self._enter_lock_screen()

    def _show_api_key(self) -> None:
        if not self._require_unlocked():
            return
        key = self.config.api_key
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=t("api_key"),
        )
        dialog.format_secondary_text(
            f"X-API-Key: {key}\nhttp://{self.config.data['api']['host']}:{self.config.data['api']['port']}/api/v1/"
        )
        dialog.run()
        dialog.destroy()

    def _about(self) -> None:
        from gltd_notes import __version__

        d = Gtk.Dialog(title=t("about"), transient_for=self, flags=0)
        d.set_default_size(520, 480)
        d.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

        content = d.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        content.pack_start(notebook, True, True, 0)

        # ── Tab: Sobre ──
        about_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        notebook.append_page(about_box, Gtk.Label(label="Sobre"))

        # Logo + name
        header = Gtk.Box(spacing=12)
        about_box.pack_start(header, False, False, 0)
        pb = load_pixbuf("app", 64)
        if pb:
            img = Gtk.Image.new_from_pixbuf(pb)
            header.pack_start(img, False, False, 0)
        name_lbl = Gtk.Label()
        name_lbl.set_markup(f"<span size='x-large' weight='bold'>{t('app_name')}</span>\n<small>v{__version__} — Estágio Alpha</small>")
        name_lbl.set_xalign(0)
        header.pack_start(name_lbl, False, False, 0)

        # Info
        info_text = (
            "Desenvolvido por Golltd Tecnologia da Informação\n"
            "Desenvolvedor: Roger Goll\n"
            "Contato: suporte@golltd.com\n"
            "Tipo de uso: Open source — livre uso e modificação\n"
            "Desenvolvido utilizando os modelos Grok e DeepSeek4"
        )
        info_lbl = Gtk.Label(label=info_text, xalign=0)
        info_lbl.set_line_wrap(True)
        about_box.pack_start(info_lbl, False, False, 0)

        # ── Tab: Doações ──
        donate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=12)
        notebook.append_page(donate_box, Gtk.Label(label="Doações"))

        # Pix
        pix_frame = Gtk.Frame(label="Pix (Brasil)")
        pix_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        pix_frame.add(pix_box)
        donate_box.pack_start(pix_frame, False, False, 0)

        pix_key = "1f57a276-dc0e-44a0-a4e0-4a2349833958"
        pix_lbl = Gtk.Label(label=f"Chave: {pix_key}", xalign=0)
        pix_lbl.set_selectable(True)
        pix_lbl.set_line_wrap(True)
        pix_box.pack_start(pix_lbl, False, False, 0)

        pix_actions = Gtk.Box(spacing=6)
        pix_box.pack_start(pix_actions, False, False, 0)

        pix_copy = Gtk.Button(label="Copiar chave Pix")
        pix_copy.connect("clicked", lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(pix_key, -1))
        pix_actions.pack_start(pix_copy, False, False, 0)

        pix_qr = Gtk.Button(label="QR Code")
        pix_qr.connect("clicked", lambda *_: self._show_qrcode("Pix", pix_key, d))
        pix_actions.pack_start(pix_qr, False, False, 0)

        # Monero
        xmr_frame = Gtk.Frame(label="Monero (XMR)")
        xmr_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        xmr_frame.add(xmr_box)
        donate_box.pack_start(xmr_frame, False, False, 0)

        xmr_addr = "84pnTEwRrFLPUqSNQdCLFw6X6gjQeQtdNNVxkYAfvgd229DHgNYzzQ9VgpquUG8RfAJJ5Py556KrAiG47PqKYxPM1mzpAtb"
        xmr_lbl = Gtk.Label(label=xmr_addr, xalign=0)
        xmr_lbl.set_selectable(True)
        xmr_lbl.set_line_wrap(True)
        xmr_box.pack_start(xmr_lbl, False, False, 0)

        xmr_actions = Gtk.Box(spacing=6)
        xmr_box.pack_start(xmr_actions, False, False, 0)

        xmr_copy = Gtk.Button(label="Copiar endereço XMR")
        xmr_copy.connect("clicked", lambda *_: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(xmr_addr, -1))
        xmr_actions.pack_start(xmr_copy, False, False, 0)

        xmr_qr = Gtk.Button(label="QR Code")
        xmr_qr.connect("clicked", lambda *_: self._show_qrcode("Monero", xmr_addr, d))
        xmr_actions.pack_start(xmr_qr, False, False, 0)

        # ── Tab: Licencas ──
        license_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        notebook.append_page(license_box, Gtk.Label(label="Licencas"))

        license_text = (
            "GLTD Notes — MIT License\n"
            "Copyright (c) 2026 GLTD\n\n"
            "Este software inclui Syncthing (https://syncthing.net/),\n"
            "licenciado sob Mozilla Public License 2.0 (MPL-2.0).\n"
            "Copyright (c) 2014-2025 The Syncthing Authors.\n\n"
            "Texto completo da licenca MPL-2.0:\n"
            "https://www.mozilla.org/en-US/MPL/2.0/\n\n"
            "O codigo-fonte do Syncthing esta disponivel em:\n"
            "https://github.com/syncthing/syncthing\n\n"
            "GLTD Notes NAO modifica o binario do Syncthing.\n"
            "Apenas o distribui e gerencia como componente independente."
        )
        license_lbl = Gtk.Label(label=license_text, xalign=0)
        license_lbl.set_selectable(True)
        license_box.pack_start(license_lbl, False, False, 0)

        d.show_all()
        d.run()
        d.destroy()

    def _show_qrcode(self, title: str, data: str, parent=None) -> None:
        pixbuf = self._generate_qr_pixbuf(data, 260)
        if pixbuf is None:
            self._msg("Falha ao gerar QR Code.")
            return
        qr_win = Gtk.Dialog(
            title=f"QR Code — {title}",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        qr_win.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        qr_win.set_default_size(300, 300)
        qr_win.set_position(Gtk.WindowPosition.CENTER)
        qr_win.connect("response", lambda d, _r: d.destroy())
        qr_win.connect("delete-event", lambda w, _e: w.destroy())
        content = qr_win.get_content_area()
        img = Gtk.Image.new_from_pixbuf(pixbuf)
        content.pack_start(img, True, True, 0)
        qr_win.show_all()

    @staticmethod
    def _generate_qr_pixbuf(data: str, size: int):  # type: ignore
        try:
            import subprocess
            import tempfile
            r = subprocess.run(
                ["qrencode", "-o", "/dev/stdout", "-s", "8", "-l", "M", data],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(r.stdout)
                    tmp.flush()
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(tmp.name)
                os.unlink(tmp.name)
                return pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            pass
        return _generate_pure_qr(data, size)



    def _logs_dialog(self) -> None:
        try:
            self._show_logs_dialog()
        except Exception as e:
            log_exception(_log, "Erro ao abrir diálogo de logs", e)
            self._set_status(f"Erro ao abrir logs: {e}")

    def _show_logs_dialog(self) -> None:
        files = list_log_files()
        dialog = Gtk.Dialog(
            title="Logs da aplicação",
            transient_for=self,
            flags=0,
        )
        dialog.set_default_size(650, 480)
        dialog.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        label = Gtk.Label(
            label="<b>Arquivos de log</b> (clique para abrir em nova janela)",
            use_markup=True,
            xalign=0,
        )
        content.pack_start(label, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        store = Gtk.ListStore(str, str)
        tree = Gtk.TreeView(model=store)
        col_name = Gtk.TreeViewColumn("Arquivo", Gtk.CellRendererText(), text=0)
        col_name.set_expand(True)
        tree.append_column(col_name)
        col_date = Gtk.TreeViewColumn("Data", Gtk.CellRendererText(), text=1)
        tree.append_column(col_date)

        for f in files:
            name = f.name
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                mtime = "—"
            store.append([name, mtime])

        if not files:
            store.append(["Nenhum arquivo de log encontrado.", ""])

        tree.connect("row-activated", lambda tree, path, col: self._on_log_row_activated(tree, path, col, store, dialog))
        scroll.add(tree)
        content.pack_start(scroll, True, True, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_log_row_activated(self, _tree: Gtk.TreeView, path: Gtk.TreePath, _col: Gtk.TreeViewColumn, store: Gtk.ListStore, parent=None) -> None:
        it = store.get_iter(path)
        if it:
            filename = store[it][0]
            if filename and "Nenhum" not in filename:
                self._open_log_file(filename, parent)

    def _open_log_file(self, filename: str, parent=None) -> None:
        from gltd_notes.utils.logger import get_log_dir

        log_dir = get_log_dir()
        if not log_dir:
            return
        file_path = log_dir / filename
        if not file_path.exists():
            return

        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            text = "(erro ao ler arquivo)"

        win = Gtk.Dialog(
            title=f"Log: {filename}",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
        )
        win.add_buttons(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        win.set_default_size(800, 600)
        win.set_position(Gtk.WindowPosition.CENTER)
        win.connect("response", lambda d, _r: d.destroy())
        win.connect("delete-event", lambda w, _e: w.destroy())

        content = win.get_content_area()
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.set_wrap_mode(Gtk.WrapMode.NONE)
        tv.get_buffer().set_text(text)
        scroll.add(tv)
        content.pack_start(scroll, True, True, 0)
        win.show_all()

    # ── Sync / Syncthing ──────────────────────────────────────

    def _start_sync(self) -> None:
        GLib.idle_add(self._init_sync)

    def _init_sync(self) -> bool:
        try:
            import threading
            from gltd_notes.services.syncthing_service import SyncthingService

            self._sync_service = SyncthingService(self.config)
            if self._sync_service._mode == "none":
                return False
            self._sync_btn.set_label("  Sync: iniciando...  ")
            self._sync_btn.show()
            if self._sync_service._mode == "embedded":
                if not self._sync_service._bin_path().exists():
                    self._sync_btn.set_label("  Sync: binario nao encontrado  ")
                    GLib.idle_add(self._prompt_download_syncthing)
                    return False

                def _bg_start():
                    try:
                        ok = self._sync_service.start()
                        def _done():
                            if ok:
                                GLib.timeout_add_seconds(5, self._update_sync_status)
                            else:
                                self._sync_btn.set_label("  Sync: falha ao iniciar  ")
                            return False
                        GLib.idle_add(_done)
                    except Exception as e:
                        import logging
                        logging.getLogger("gltd_notes").warning("Sync start error: %s", e)

                        def _err():
                            self._sync_btn.set_label("  Sync: erro  ")
                            return False
                        GLib.idle_add(_err)

                threading.Thread(target=_bg_start, daemon=True).start()
            else:
                GLib.timeout_add_seconds(5, self._update_sync_status)
        except Exception as e:
            import logging
            logging.getLogger("gltd_notes").warning("Erro ao iniciar sync: %s", e)
            self._sync_btn.set_label("  Sync: erro  ")
        return False

    def _prompt_download_syncthing(self) -> bool:
        try:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Syncthing nao encontrado",
            )
            dialog.format_secondary_text(
                "O binario do Syncthing nao foi encontrado.\n\n"
                "Deseja baixar e instalar agora?\n"
                "(Configuracoes > Sync > Baixar / Instalar Syncthing)"
            )
            if dialog.run() == Gtk.ResponseType.OK:
                dialog.destroy()
                self._open_settings()
            else:
                dialog.destroy()
        except Exception:
            pass
        return False

    def _update_sync_status(self) -> bool:
        if not hasattr(self, "_sync_service"):
            return False
        try:
            running = self._sync_service.is_running()
            if not running:
                self._sync_btn.set_markup('<span foreground="#f7768e">  Sync: offline  </span>')
                return True
            self._sync_service.approve_pending_devices()
            self._sync_service.approve_pending_folders()
            self._sync_service.ensure_folder_sharing()
            uh = self._user_hash()
            folder_id = f"gltd-notes-user-{uh}"
            status = self._sync_service.get_folder_status(folder_id)
            state = status.get("state", "unknown")
            if state == "idle":
                self._sync_btn.set_markup('<span foreground="#9ece6a">  Sync: OK  </span>')
            elif state in ("syncing", "scanning"):
                comp = self._sync_service.get_completion(folder_id)
                pct = int(comp.get("completion", 0))
                self._sync_btn.set_markup(f'<span foreground="#e0af68">  Sync: {pct}%  </span>')
            else:
                self._sync_btn.set_markup(f'<span foreground="#e0af68">  Sync: {state}  </span>')
        except Exception:
            self._sync_btn.set_label("  Sync: —  ")
        return True

    def _open_sync_dashboard(self) -> None:
        try:
            from gltd_notes.gui.sync_dashboard import SyncDashboard
            SyncDashboard.show(self, self.config, getattr(self, "_sync_service", None))
        except Exception as e:
            import logging
            _log_sync = logging.getLogger("gltd_notes")
            _log_sync.warning("Erro ao abrir dashboard Syncthing: %s", e)
            self._msg(f"Erro ao abrir Syncthing:\n{e}")

    def _show_sync_details(self) -> None:
        self._open_sync_dashboard()

    # ── Web UI process control ───────────────────────────────
    def _web_status_text(self) -> str:
        from gltd_notes.services.web_process import status as web_status

        st = web_status(self.config)
        state = {
            "running": "em execução",
            "stopped": "parado",
            "starting": "iniciando…",
        }.get(st["state"], st["state"])
        pid = st.get("pid") or "—"
        return (
            f"Status: {state}\n"
            f"URL: {st['url']}\n"
            f"PID: {pid}\n"
            f"Log: {st['log']}\n\n"
            "Login web = mesmo usuário/senha do desktop."
        )

    def _web_status_dialog(self) -> None:
        self.config.reload()
        d = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Interface Web",
        )
        d.format_secondary_text(self._web_status_text())
        d.run()
        d.destroy()

    def _web_start(self) -> None:
        from gltd_notes.services.web_process import start as web_start

        self.config.reload()
        st = web_start(self.config)
        self._set_status(
            f"Web: {'em execução' if st['running'] else 'falhou ao iniciar'} · {st['url']}"
        )
        if st["running"]:
            self._msg(f"Interface web em execução.\n{st['url']}")
        else:
            self._msg("Não foi possível iniciar a interface web.\nVeja o log em ~/.local/share/gltd_notes/web.log")

    def _web_stop(self) -> None:
        from gltd_notes.services.web_process import stop as web_stop

        self.config.reload()
        st = web_stop(self.config)
        self._set_status("Web: parado" if not st["running"] else "Web: ainda ativo")
        self._msg("Interface web finalizada." if not st["running"] else "A web ainda parece estar ativa.")

    def _web_restart(self) -> None:
        from gltd_notes.services.web_process import restart as web_restart

        self.config.reload()
        st = web_restart(self.config)
        self._set_status(
            f"Web reiniciada · {st['url']}" if st["running"] else "Web: falha ao reiniciar"
        )
        if st["running"]:
            self._msg(f"Interface web reiniciada.\n{st['url']}")
        else:
            self._msg("Falha ao reiniciar a interface web.")

    def _web_open(self) -> None:
        from gltd_notes.services.web_process import start as web_start, status as web_status, web_url
        from gltd_notes.utils.browser import open_url

        self.config.reload()
        st = web_status(self.config)
        if not st["running"]:
            st = web_start(self.config)
        url = st.get("url") or web_url(self.config)
        if st["running"]:
            ok = open_url(url)
            self._set_status(f"Web aberta: {url}" if ok else f"Abra manualmente: {url}")
            if not ok:
                self._msg(f"Não foi possível abrir o navegador.\nAcesse: {url}")
        else:
            self._msg("Não foi possível iniciar a interface web.")

    def _msg(self, text: str) -> None:
        d = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        d.run()
        d.destroy()

    # ── window close / tray ──────────────────────────────────
    def _on_delete_event(self, *_args):
        """Window X button: hide to tray (default) instead of quitting."""
        if self._really_quit:
            self._autosave_now(silent=True)
            return False  # allow destroy
        close_to_tray = self.config.data.get("gui", {}).get("close_to_tray", True)
        if close_to_tray:
            self._autosave_now(silent=True)
            self.hide()
            self._set_status(t("hide_window"))
            return True  # stop default destroy
        self._autosave_now(silent=True)
        return False

    def _hide_to_tray(self) -> None:
        self._autosave_now(silent=True)
        self.hide()

    def _show_from_tray(self) -> None:
        self.show_all()
        self.present()
        if self._ui_locked:
            GLib.idle_add(self._unlock_entry.grab_focus)

    def _quit(self) -> None:
        self._autosave_now(silent=True)
        self._really_quit = True
        self.destroy()
        Gtk.main_quit()

    def _on_destroy(self, *_args) -> None:
        self._cancel_autosave()
        self._cancel_agent_timer()
        self._cancel_agent_flush()
        if self.api_server and self.api_server._httpd:
            try:
                self.api_server._httpd.shutdown()
            except Exception:
                pass
        if hasattr(self, "_sync_service") and self._sync_service:
            try:
                self._sync_service.stop()
            except Exception:
                pass
        if self._really_quit:
            Gtk.main_quit()


def run_gui() -> int:
    config = Config()
    config.migrate_password_flags()
    get_i18n(config.data.get("gui", {}).get("language") or "auto")
    if not run_setup_if_needed(config):
        return 1

    setup_logging(CONFIG_DIR / "logs")

    lock_path = os.path.join("/tmp", "gltd_notes_gui.lock")
    _lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(_lock_fd)
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=0,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format="GLTD Notes já está em execução.\nApenas uma instância pode ser executada por vez.",
        )
        dialog.run()
        dialog.destroy()
        return 1

    config = Config()
    config.migrate_password_flags()
    get_i18n(config.data.get("gui", {}).get("language") or "auto")
    try:
        win = MainWindow(config)
    except Exception as e:
        import traceback
        traceback.print_exc()
        dialog = Gtk.MessageDialog(
            parent=None,
            flags=0,
            type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            message_format=f"Erro ao iniciar GLTD Notes:\n{e}",
        )
        dialog.run()
        dialog.destroy()
        os.close(_lock_fd)
        return 1
    win.show_all()
    Gtk.main()
    os.close(_lock_fd)
    return 0
