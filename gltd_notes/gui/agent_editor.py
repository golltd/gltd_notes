"""Editor for agent_task notes."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from gltd_notes.i18n import t
from gltd_notes.services.agent_tasks import AGENTS, STATUSES, parse_agent_body, serialize_agent


_ST_COLORS = {
    "done": "#9ece6a",
    "failed": "#f7768e",
    "running": "#e0af68",
    "pending": "#565f89",
}
_ST_ICONS = {
    "done": "✓",
    "failed": "✗",
    "running": "●",
    "pending": "○",
}


class AgentTaskEditor(Gtk.Box):
    def __init__(
        self,
        on_change: Optional[Callable[[], None]] = None,
        on_play: Optional[Callable[[], None]] = None,
        on_add_related: Optional[Callable[[str, str, str], Optional[Dict]]] = None,
        on_clear_output: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_navigate_to_child: Optional[Callable[[str], None]] = None,
        on_navigate_back: Optional[Callable[[], None]] = None,
        on_play_subtask: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.on_change = on_change
        self.on_play = on_play
        self.on_add_related = on_add_related
        self.on_clear_output = on_clear_output
        self.on_cancel = on_cancel
        self.on_navigate_to_child = on_navigate_to_child
        self.on_navigate_back = on_navigate_back
        self.on_play_subtask = on_play_subtask
        self._loading = False
        self._running = False
        self._subtask_rows: List[Gtk.Box] = []
        self._sub_entries: Dict[str, Gtk.Entry] = {}

        # ── Navigation bar ──
        self._nav_bar = Gtk.Box(spacing=8)
        self._nav_bar.set_no_show_all(True)
        self._nav_bar.hide()
        self.back_btn = Gtk.Button(label="← Voltar")
        self.back_btn.connect("clicked", lambda *_: self._go_back())
        self._nav_bar.pack_start(self.back_btn, False, False, 0)
        self._nav_title = Gtk.Label(xalign=0)
        self._nav_bar.pack_start(self._nav_title, True, True, 0)
        self.pack_start(self._nav_bar, False, False, 0)

        row = Gtk.Box(spacing=8)
        self.pack_start(row, False, False, 0)
        row.pack_start(Gtk.Label(label="Agente:"), False, False, 0)
        self.agent_combo = Gtk.ComboBoxText()
        for a in AGENTS:
            self.agent_combo.append_text(a)
        self.agent_combo.set_active(0)
        self.agent_combo.connect("changed", lambda *_: self._emit())
        row.pack_start(self.agent_combo, False, False, 0)

        row.pack_start(Gtk.Label(label="Status:"), False, False, 0)
        self.status_combo = Gtk.ComboBoxText()
        for s in STATUSES:
            self.status_combo.append_text(s)
        self.status_combo.set_active(0)
        self.status_combo.connect("changed", lambda *_: self._emit())
        row.pack_start(self.status_combo, False, False, 0)

        self.play_btn = Gtk.Button(label="▶ Play / Executar")
        self.play_btn.connect("clicked", lambda *_: self.on_play and self.on_play())
        row.pack_start(self.play_btn, False, False, 0)

        self.cancel_btn = Gtk.Button(label="■ Cancelar")
        self.cancel_btn.set_tooltip_text("Abortar a execução do agente")
        self.cancel_btn.connect("clicked", lambda *_: self.on_cancel and self.on_cancel())
        self.cancel_btn.set_no_show_all(True)
        self.cancel_btn.hide()
        row.pack_start(self.cancel_btn, False, False, 0)

        self.clear_output_btn = Gtk.Button(label="✕ Limpar Output")
        self.clear_output_btn.set_tooltip_text("Apagar o conteúdo do campo de output")
        self.clear_output_btn.connect("clicked", lambda *_: self.on_clear_output and self.on_clear_output())
        row.pack_start(self.clear_output_btn, False, False, 0)

        self.pack_start(Gtk.Label(label="Descrição da tarefa:", xalign=0), False, False, 0)
        scroll_d = Gtk.ScrolledWindow()
        scroll_d.set_min_content_height(100)
        self.desc_view = Gtk.TextView()
        self.desc_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.desc_view.get_buffer().connect("changed", lambda *_: self._emit())
        scroll_d.add(self.desc_view)
        self.pack_start(scroll_d, True, True, 0)

        # ── Subtasks section ──
        subs_hdr = Gtk.Box(spacing=8)
        subs_hdr.pack_start(Gtk.Label(label="<b>Subtarefas</b>", use_markup=True, xalign=0), False, False, 0)
        self.add_sub_btn = Gtk.Button(label="＋ Adicionar subtarefa")
        self.add_sub_btn.connect("clicked", lambda *_: self._add_subtask_row())
        subs_hdr.pack_end(self.add_sub_btn, False, False, 0)
        self.pack_start(subs_hdr, False, False, 0)

        self.subs_scroll = Gtk.ScrolledWindow()
        self.subs_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.subs_scroll.set_min_content_height(80)
        self.subs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.subs_scroll.add(self.subs_box)
        self.pack_start(self.subs_scroll, True, True, 0)

        self.pack_start(Gtk.Label(label="Output do agente:", xalign=0), False, False, 0)
        scroll_o = Gtk.ScrolledWindow()
        scroll_o.set_min_content_height(120)
        self.out_view = Gtk.TextView()
        self.out_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.out_view.get_buffer().connect("changed", lambda *_: self._emit())
        scroll_o.add(self.out_view)
        self.pack_start(scroll_o, True, True, 0)

        self.meta = Gtk.Label(label="", xalign=0)
        self.pack_start(self.meta, False, False, 0)
        self.show_all()

    def _emit(self) -> None:
        if self._loading:
            return
        if self.on_change:
            self.on_change()

    # ── Subtask row management ──
    def _add_subtask_row(self, sub_id: str = "", desc: str = "", status: str = "pending") -> Gtk.Box:
        if not sub_id:
            import uuid
            sub_id = str(uuid.uuid4())[:8]

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box._sub_id = sub_id
        box.set_margin_start(8)
        box.set_margin_end(8)

        top_row = Gtk.Box(spacing=6)
        box.pack_start(top_row, False, False, 0)

        st_icon = _ST_ICONS.get(status, "○")
        st_color = _ST_COLORS.get(status, "#565f89")
        icon_lbl = Gtk.Label()
        icon_lbl.set_markup(f'<span foreground="{st_color}">{st_icon}</span>')
        icon_lbl._sub_id = sub_id
        top_row.pack_start(icon_lbl, False, False, 0)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Descreva a subtarefa…")
        entry.set_text(desc or "")
        entry.connect("changed", lambda *_: self._emit())
        entry._sub_id = sub_id
        self._sub_entries[sub_id] = entry
        top_row.pack_start(entry, True, True, 0)

        play_btn = Gtk.Button(label="▶")
        play_btn.set_tooltip_text("Executar esta subtarefa")
        play_btn._sub_id = sub_id
        play_btn.connect("clicked", self._on_sub_play_clicked)
        top_row.pack_start(play_btn, False, False, 0)

        rm_btn = Gtk.Button(label="✕")
        rm_btn.set_tooltip_text("Remover subtarefa")
        rm_btn._sub_id = sub_id
        rm_btn.connect("clicked", self._on_sub_remove_clicked)
        rm_btn.set_relief(Gtk.ReliefStyle.NONE)
        top_row.pack_start(rm_btn, False, False, 0)

        sep = Gtk.Separator()
        sep._sub_id = sub_id
        box.pack_start(sep, False, False, 0)

        box.show_all()
        self.subs_box.pack_start(box, False, False, 0)
        self._subtask_rows.append(box)
        return box

    def _on_sub_play_clicked(self, button: Gtk.Button) -> None:
        sub_id = getattr(button, "_sub_id", "")
        if sub_id and self.on_play_subtask:
            self.on_play_subtask(sub_id)

    def _on_sub_remove_clicked(self, button: Gtk.Button) -> None:
        sub_id = getattr(button, "_sub_id", "")
        for box in list(self._subtask_rows):
            if getattr(box, "_sub_id", "") == sub_id:
                self.subs_box.remove(box)
                self._subtask_rows.remove(box)
                self._sub_entries.pop(sub_id, None)
                box.destroy()
                break
        self._emit()

    def _clear_subtask_rows(self) -> None:
        for box in list(self._subtask_rows):
            self.subs_box.remove(box)
            box.destroy()
        self._subtask_rows.clear()
        self._sub_entries.clear()

    def _go_back(self) -> None:
        if self.on_navigate_back:
            self.on_navigate_back()

    def show_nav_bar(self, title: str) -> None:
        self._nav_title.set_markup(f'<b>{GLib.markup_escape_text(title)}</b>')
        self._nav_bar.show_all()

    def hide_nav_bar(self) -> None:
        self._nav_bar.hide()

    def load_from_body(self, body: str) -> None:
        self._loading = True
        data = parse_agent_body(body)
        agent = data.get("agent") or "grok"
        try:
            self.agent_combo.set_active(AGENTS.index(agent))
        except ValueError:
            self.agent_combo.set_active(0)
        status = data.get("status") or "pending"
        try:
            self.status_combo.set_active(STATUSES.index(status))
        except ValueError:
            self.status_combo.set_active(0)
        self.desc_view.get_buffer().set_text(data.get("description") or "")
        self.out_view.get_buffer().set_text(data.get("output") or "")
        rel = data.get("related_ids") or []
        parent = data.get("parent_id") or ""
        self.meta.set_text(
            f"executed_at: {data.get('executed_at') or '—'}  ·  "
            f"parent: {(parent[:12] + '…') if parent else '—'}  ·  related: {len(rel)}"
        )
        self._loading = False

    def load_subtasks(self, subtasks: list) -> None:
        self._clear_subtask_rows()
        for s in (subtasks or []):
            self._add_subtask_row(
                sub_id=s.get("id", ""),
                desc=s.get("description", ""),
                status=s.get("status", "pending"),
            )

    def build_subtasks(self, existing_subtasks: Optional[list] = None) -> list:
        agent = self.agent_combo.get_active_text() or "grok"
        existing = {}
        source = existing_subtasks if existing_subtasks is not None else (self._base or {}).get("subtasks") or []
        for s in (source or []):
            existing[s.get("id", "")] = s
        result = []
        for box in self._subtask_rows:
            sub_id = getattr(box, "_sub_id", "")
            entry = self._sub_entries.get(sub_id)
            desc = entry.get_text() if entry else ""
            prev = existing.get(sub_id, {})
            result.append({
                "id": sub_id,
                "description": desc,
                "agent": prev.get("agent") or agent or "grok",
                "status": prev.get("status", "pending"),
                "output": prev.get("output", ""),
                "executed_at": prev.get("executed_at"),
            })
        return result

    def get_data(self, existing_subtasks: Optional[list] = None) -> Dict:
        db = self.desc_view.get_buffer()
        ob = self.out_view.get_buffer()
        desc = db.get_text(db.get_start_iter(), db.get_end_iter(), True)
        out = ob.get_text(ob.get_start_iter(), ob.get_end_iter(), True)
        agent = self.agent_combo.get_active_text() or "grok"
        status = self.status_combo.get_active_text() or "pending"
        return {
            "version": 1,
            "description": desc,
            "agent": agent,
            "status": status,
            "output": out,
            "executed_at": None,
            "parent_id": None,
            "related_ids": [],
            "subtasks": self.build_subtasks(existing_subtasks),
        }

    def to_body(self, base: Optional[Dict] = None) -> str:
        src = base if base is not None else getattr(self, "_base", None)
        data = parse_agent_body(serialize_agent(src) if src else "{}")
        cur = self.get_data(data.get("subtasks") if data else None)
        data["description"] = cur["description"]
        data["agent"] = cur["agent"]
        data["status"] = cur["status"]
        data["output"] = cur["output"]
        data["subtasks"] = cur["subtasks"]
        if src:
            for k in ("parent_id", "related_ids", "executed_at"):
                if src.get(k) is not None:
                    data[k] = src[k]
        return serialize_agent(data)

    def load_full(self, body: str) -> None:
        self._base = parse_agent_body(body)
        self.load_from_body(body)
        self.load_subtasks(self._base.get("subtasks") or [])

    def clear_output(self) -> None:
        self.out_view.get_buffer().set_text("")
        self._emit()

    def set_running(self, running: bool) -> None:
        self._running = running
        if running:
            self.play_btn.hide()
            self.cancel_btn.show()
        else:
            self.cancel_btn.hide()
            self.play_btn.show()

    def append_output(self, chunk: str) -> None:
        buf = self.out_view.get_buffer()
        buf.insert(buf.get_end_iter(), chunk)
        self._emit()
