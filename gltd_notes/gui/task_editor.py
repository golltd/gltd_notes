"""GTK editor for task-list notes (due dates, links, progress, subtasks)."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from gltd_notes.i18n import t
from gltd_notes.services.tasks import parse_tasklist_body
from gltd_notes.utils.hashing import new_entity_id

# columns:
# 0 done, 1 text, 2 linked_note_id, 3 task_id, 4 link_label,
# 5 due_date, 6 progress_count_label, 7 parent_id, 8 indent_prefix


class TaskEditor(Gtk.Box):
    def __init__(
        self,
        on_change: Optional[Callable[[], None]] = None,
        on_open_note: Optional[Callable[[str], None]] = None,
        get_notes: Optional[Callable[[], List[Dict]]] = None,
        on_create_note: Optional[Callable[[str], None]] = None,
        on_add_progress: Optional[Callable[[str], None]] = None,
        on_view_progress: Optional[Callable[[str], None]] = None,
        on_add_subtask: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.on_change = on_change
        self.on_open_note = on_open_note
        self.get_notes = get_notes or (lambda: [])
        self.on_create_note = on_create_note
        self.on_add_progress = on_add_progress
        self.on_view_progress = on_view_progress
        self.on_add_subtask = on_add_subtask
        self._loading = False
        self._tasks: List[Dict] = []

        # ── toolbar row 1 ──
        toolbar = Gtk.Box(spacing=4)
        self.pack_start(toolbar, False, False, 0)

        def mk(label, tip, cb):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            toolbar.pack_start(b, False, False, 0)
            return b

        self.add_btn = mk(t("add_task"), "Adicionar tarefa", self._add_task)
        self.up_btn = mk("↑", t("move_up"), lambda: self._move(-1))
        self.down_btn = mk("↓", t("move_down"), lambda: self._move(1))
        self.del_btn = mk(t("delete_task"), "Remover tarefa", self._delete_selected)

        # ── toolbar row 2 ──
        toolbar2 = Gtk.Box(spacing=4)
        self.pack_start(toolbar2, False, False, 0)

        def mk2(label, tip, cb):
            b = Gtk.Button(label=label)
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda *_: cb())
            toolbar2.pack_start(b, False, False, 0)
            return b

        self.link_btn = mk2(t("link_note"), "Vincular nota existente", self._link_note)
        self.create_note_btn = mk2("＋ Criar nota", "Criar nova nota e vincular à tarefa", self._create_note)
        self.unlink_btn = mk2(t("unlink_note"), "Desvincular nota", self._unlink)
        self.open_link_btn = mk2(t("open_linked"), "Abrir nota vinculada", self._open_linked)
        self.due_btn = mk2("📅 Data", "Definir data de conclusão", self._set_due_date)
        self.progress_btn = mk2("＋ Andamento", "Novo andamento da tarefa", self._add_progress)
        self.view_prog_btn = mk2("📋 Andamentos", "Ver andamentos", self._view_progress)
        self.subtask_btn = mk2("＋ Subtarefa", "Criar subtarefa relacionada", self._add_subtask)

        # store
        self.store = Gtk.ListStore(bool, str, str, str, str, str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._on_toggled)
        self.tree.append_column(Gtk.TreeViewColumn(t("task_done"), toggle, active=0))

        text_r = Gtk.CellRendererText()
        text_r.set_property("editable", True)
        text_r.connect("edited", self._on_text_edited)
        col1 = Gtk.TreeViewColumn(t("task_text"), text_r, text=1)
        col1.set_expand(True)
        self.tree.append_column(col1)

        due_r = Gtk.CellRendererText()
        due_r.set_property("editable", True)
        due_r.connect("edited", self._on_due_edited)
        self.tree.append_column(Gtk.TreeViewColumn("Conclusão", due_r, text=5))

        self.tree.append_column(Gtk.TreeViewColumn("🔗", Gtk.CellRendererText(), text=4))
        self.tree.append_column(Gtk.TreeViewColumn("Andam.", Gtk.CellRendererText(), text=6))

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.tree)
        self.pack_start(scroll, True, True, 0)

        hint = Gtk.Label(
            label="Dica: selecione uma tarefa → data, criar nota, andamento ou subtarefa.",
            xalign=0,
        )
        hint.set_opacity(0.7)
        self.pack_start(hint, False, False, 0)
        self.show_all()

    # ── data ─────────────────────────────────────────────────
    def load_from_body(self, body: str) -> None:
        self._loading = True
        data = parse_tasklist_body(body)
        self._tasks = list(data.get("tasks") or [])
        self._reload_store()
        self._loading = False

    def get_tasks(self) -> List[Dict]:
        # keep rich fields from self._tasks by id
        by_id = {t.get("id"): t for t in self._tasks if t.get("id")}
        tasks = []
        for i, row in enumerate(self.store):
            raw_text = row[1] or ""
            if raw_text.startswith("    ↳ "):
                raw_text = raw_text[6:]
            tid = row[3] or new_entity_id("task", raw_text or "", str(i))
            prev = by_id.get(tid) or {}
            done = bool(row[0])
            parent = row[7] or prev.get("parent_id") or None
            tasks.append(
                {
                    "id": tid,
                    "text": raw_text,
                    "done": done,
                    "order": i,
                    "linked_note_id": row[2] or None,
                    "due_date": (row[5] or "").strip() or None,
                    "completed_at": prev.get("completed_at") if done else None,
                    "progress_ids": list(prev.get("progress_ids") or []),
                    "parent_id": parent or None,
                }
            )
        self._tasks = tasks
        return list(tasks)

    def _display_text(self, tsk: Dict) -> str:
        text = tsk.get("text") or ""
        if tsk.get("parent_id"):
            return "    ↳ " + text
        return text

    def _reload_store(self) -> None:
        self.store.clear()
        # parents first then children under them (stable by order)
        tasks = sorted(self._tasks, key=lambda x: x.get("order", 0))
        parents = [t for t in tasks if not t.get("parent_id")]
        children = [t for t in tasks if t.get("parent_id")]
        ordered = []
        for p in parents:
            ordered.append(p)
            ordered.extend([c for c in children if c.get("parent_id") == p.get("id")])
        # orphans
        ordered_ids = {t.get("id") for t in ordered}
        for c in children:
            if c.get("id") not in ordered_ids:
                ordered.append(c)

        for tsk in ordered:
            link = tsk.get("linked_note_id") or ""
            label = (link[:10] + "…") if link else ""
            nprog = len(tsk.get("progress_ids") or [])
            prog_label = str(nprog) if nprog else ""
            self.store.append(
                [
                    bool(tsk.get("done")),
                    self._display_text(tsk),
                    link,
                    tsk.get("id") or "",
                    label,
                    tsk.get("due_date") or "",
                    prog_label,
                    tsk.get("parent_id") or "",
                    "sub" if tsk.get("parent_id") else "",
                ]
            )

    def _emit(self) -> None:
        if self._loading:
            return
        if self.on_change:
            self.on_change()

    def _selected_iter(self):
        return self.tree.get_selection().get_selected()

    def _selected_task_id(self) -> Optional[str]:
        model, it = self._selected_iter()
        if not it:
            return None
        return model[it][3] or None

    def _sync_tasks_from_store(self) -> None:
        self._tasks = self.get_tasks()

    # ── events ───────────────────────────────────────────────
    def _on_toggled(self, _renderer, path: str) -> None:
        it = self.store.get_iter(path)
        self.store[it][0] = not self.store[it][0]
        self._emit()

    def _on_text_edited(self, _renderer, path: str, new_text: str) -> None:
        it = self.store.get_iter(path)
        # strip indent marker if user edited
        text = new_text
        if text.startswith("    ↳ "):
            text = text[6:]
        self.store[it][1] = self._display_text(
            {"text": text, "parent_id": self.store[it][7] or None}
        )
        # keep raw text in tasks on get_tasks via strip
        self._emit()

    def _on_due_edited(self, _renderer, path: str, new_text: str) -> None:
        it = self.store.get_iter(path)
        val = (new_text or "").strip()
        # basic normalize YYYY-MM-DD
        self.store[it][5] = val
        self._emit()

    def _add_task(self) -> None:
        tid = new_entity_id("task", "new")
        self.store.append([False, "", "", tid, "", "", "", "", ""])
        path = Gtk.TreePath.new_from_indices([len(self.store) - 1])
        self.tree.set_cursor(path, self.tree.get_column(1), True)
        self._emit()

    def _move(self, delta: int) -> None:
        model, it = self._selected_iter()
        if not it:
            return
        path = model.get_path(it)
        idx = path.get_indices()[0]
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(model):
            return
        row = list(model[it])
        model.remove(it)
        if new_idx >= len(model):
            model.append(row)
            new_path = Gtk.TreePath.new_from_indices([len(model) - 1])
        else:
            dest = model.get_iter(Gtk.TreePath.new_from_indices([new_idx]))
            model.insert_before(dest, row)
            new_path = Gtk.TreePath.new_from_indices([new_idx])
        self.tree.get_selection().select_path(new_path)
        self._emit()

    def _delete_selected(self) -> None:
        model, it = self._selected_iter()
        if not it:
            return
        tid = model[it][3]
        model.remove(it)
        # also remove children of this task from store
        to_remove = []
        for i, row in enumerate(model):
            if row[7] == tid:
                to_remove.append(model.get_iter(Gtk.TreePath.new_from_indices([i])))
        # reverse paths by collecting ids
        child_ids = [row[3] for row in model if row[7] == tid]
        for cid in child_ids:
            for i, row in enumerate(list(model)):
                if row[3] == cid:
                    model.remove(model.get_iter(Gtk.TreePath.new_from_indices([i])))
                    break
        self._emit()

    def _link_note(self) -> None:
        model, it = self._selected_iter()
        if not it:
            self._msg("Selecione uma tarefa primeiro.")
            return
        notes = [
            n
            for n in self.get_notes()
            if (n.get("kind") or "note") in ("note", None, "note")
            or n.get("kind") not in ("tasklist", "task_progress", "agent_task")
        ]
        # simpler filter
        notes = [n for n in self.get_notes() if n.get("kind", "note") == "note"]
        dialog = Gtk.Dialog(title=t("link_note"), flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        store = Gtk.ListStore(str, str)
        for n in notes:
            store.append([n["entity_id"], n.get("title") or t("untitled")])
        tree = Gtk.TreeView(model=store)
        tree.append_column(Gtk.TreeViewColumn(t("title"), Gtk.CellRendererText(), text=1))
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(420, 320)
        scroll.add(tree)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            m, sit = tree.get_selection().get_selected()
            if sit:
                nid = m[sit][0]
                model[it][2] = nid
                model[it][4] = nid[:10] + "…"
                self._emit()
        dialog.destroy()

    def _create_note(self) -> None:
        tid = self._selected_task_id()
        if not tid:
            self._msg("Selecione uma tarefa para criar a nota.")
            return
        self._sync_tasks_from_store()
        if self.on_create_note:
            self.on_create_note(tid)

    def _unlink(self) -> None:
        model, it = self._selected_iter()
        if it:
            model[it][2] = ""
            model[it][4] = ""
            self._emit()

    def _open_linked(self) -> None:
        model, it = self._selected_iter()
        if not it:
            return
        nid = model[it][2]
        if nid and self.on_open_note:
            self.on_open_note(nid)

    def _set_due_date(self) -> None:
        model, it = self._selected_iter()
        if not it:
            self._msg("Selecione uma tarefa.")
            return
        dialog = Gtk.Dialog(title="Data de conclusão", flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(Gtk.Label(label="Data (AAAA-MM-DD):", xalign=0), False, False, 0)
        entry = Gtk.Entry()
        entry.set_text(model[it][5] or "")
        entry.set_placeholder_text("2026-08-15")
        box.pack_start(entry, False, False, 0)
        # calendar helper
        cal = Gtk.Calendar()
        box.pack_start(cal, False, False, 0)

        def on_cal(*_a):
            y, m, d = cal.get_date()
            entry.set_text(f"{y:04d}-{m+1:02d}-{d:02d}")

        cal.connect("day-selected-double-click", on_cal)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            model[it][5] = entry.get_text().strip()
            self._emit()
        dialog.destroy()

    def _add_progress(self) -> None:
        tid = self._selected_task_id()
        if not tid:
            self._msg("Selecione uma tarefa para registrar andamento.")
            return
        self._sync_tasks_from_store()
        if self.on_add_progress:
            self.on_add_progress(tid)

    def _view_progress(self) -> None:
        tid = self._selected_task_id()
        if not tid:
            self._msg("Selecione uma tarefa.")
            return
        self._sync_tasks_from_store()
        if self.on_view_progress:
            self.on_view_progress(tid)

    def _add_subtask(self) -> None:
        tid = self._selected_task_id()
        if not tid:
            self._msg("Selecione a tarefa pai.")
            return
        # if selected is already subtask, attach to its parent
        model, it = self._selected_iter()
        parent = tid
        if it and model[it][7]:
            parent = model[it][7]
        self._sync_tasks_from_store()
        if self.on_add_subtask:
            self.on_add_subtask(parent)
        else:
            # local fallback
            child_id = new_entity_id("task", "sub")
            # find parent row index to insert after
            insert_at = len(self.store)
            for i, row in enumerate(self.store):
                if row[3] == parent:
                    insert_at = i + 1
                    break
            self.store.insert(
                insert_at,
                [False, "    ↳ ", "", child_id, "", "", "", parent, "sub"],
            )
            path = Gtk.TreePath.new_from_indices([insert_at])
            self.tree.set_cursor(path, self.tree.get_column(1), True)
            self._emit()

    def set_progress_count(self, task_id: str, count: int) -> None:
        for row in self.store:
            if row[3] == task_id:
                row[6] = str(count) if count else ""
                break

    def set_linked_note(self, task_id: str, note_id: str) -> None:
        for row in self.store:
            if row[3] == task_id:
                row[2] = note_id
                row[4] = (note_id[:10] + "…") if note_id else ""
                break
        # update cache
        for t in self._tasks:
            if t.get("id") == task_id:
                t["linked_note_id"] = note_id
        self._emit()

    def append_subtask_row(self, parent_id: str, task_id: str, text: str = "") -> None:
        insert_at = len(self.store)
        for i, row in enumerate(self.store):
            if row[3] == parent_id:
                insert_at = i + 1
                # skip existing children
                j = i + 1
                while j < len(self.store) and self.store[j][7] == parent_id:
                    insert_at = j + 1
                    j += 1
                break
        disp = "    ↳ " + (text or "")
        self.store.insert(insert_at, [False, disp, "", task_id, "", "", "", parent_id, "sub"])
        self._emit()

    def append_progress_id(self, task_id: str, progress_note_id: str) -> None:
        for t in self._tasks:
            if t.get("id") == task_id:
                pids = list(t.get("progress_ids") or [])
                if progress_note_id not in pids:
                    pids.append(progress_note_id)
                t["progress_ids"] = pids
                self.set_progress_count(task_id, len(pids))
                break
        # ensure store row has count
        for t in self.get_tasks():
            if t.get("id") == task_id:
                self.set_progress_count(task_id, len(t.get("progress_ids") or []))

    def _msg(self, text: str) -> None:
        d = Gtk.MessageDialog(
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        d.run()
        d.destroy()

    def retranslate(self) -> None:
        self.add_btn.set_label(t("add_task"))
        self.link_btn.set_label(t("link_note"))
        self.unlink_btn.set_label(t("unlink_note"))
        self.del_btn.set_label(t("delete_task"))
        self.open_link_btn.set_label(t("open_linked"))
