"""Task-list notes: checkable items, due dates, note links, progress & subtasks."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from gltd_notes.services.app_context import AppContext
from gltd_notes.services.notes import NotesService
from gltd_notes.utils.hashing import new_entity_id, sha256_text


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def empty_tasklist_body() -> str:
    return json.dumps({"version": 1, "tasks": []}, ensure_ascii=False, indent=2)


def _norm_task(t: Dict[str, Any], i: int = 0) -> Dict[str, Any]:
    return {
        "id": t.get("id") or new_entity_id("task", str(i)),
        "text": str(t.get("text") or ""),
        "done": bool(t.get("done")),
        "order": int(t.get("order", i)),
        "linked_note_id": t.get("linked_note_id") or None,
        "due_date": t.get("due_date") or None,  # YYYY-MM-DD
        "completed_at": t.get("completed_at") or None,
        "progress_ids": list(t.get("progress_ids") or []),
        "parent_id": t.get("parent_id") or None,  # subtask of another task id
    }


def parse_tasklist_body(body: Optional[str]) -> Dict[str, Any]:
    if not body or not body.strip():
        return {"version": 1, "tasks": []}
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return {"version": 1, "tasks": []}
        tasks = data.get("tasks") or []
        if not isinstance(tasks, list):
            tasks = []
        normalized = []
        for i, t in enumerate(tasks):
            if not isinstance(t, dict):
                continue
            normalized.append(_norm_task(t, i))
        normalized.sort(key=lambda x: x["order"])
        for i, t in enumerate(normalized):
            t["order"] = i
        return {"version": 1, "tasks": normalized}
    except json.JSONDecodeError:
        tasks = []
        for i, line in enumerate((body or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            tasks.append(
                _norm_task(
                    {
                        "id": new_entity_id("task", line[:40], str(i)),
                        "text": line,
                        "done": False,
                        "order": i,
                    },
                    i,
                )
            )
        return {"version": 1, "tasks": tasks}


def serialize_tasklist(data: Dict[str, Any]) -> str:
    tasks = [_norm_task(t, i) for i, t in enumerate(data.get("tasks") or [])]
    tasks.sort(key=lambda x: x.get("order", 0))
    for i, t in enumerate(tasks):
        t["order"] = i
    return json.dumps({"version": 1, "tasks": tasks}, ensure_ascii=False, indent=2)


class TasksService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.notes = NotesService(ctx)

    def create_tasklist(self, user_hash: str, title: str = "") -> Dict[str, Any]:
        return self.notes.create_note(
            user_hash,
            title=title or "Task list",
            body=empty_tasklist_body(),
            categories=["Tasks"],
            tags=["tasklist"],
            kind="tasklist",
            extra_payload={"markers": ["#tarefas"]},
        )

    def get_tasks(self, user_hash: str, note_id: str) -> List[Dict[str, Any]]:
        note = self.notes.get_note(user_hash, note_id, include_body=True)
        return parse_tasklist_body(note.get("body")).get("tasks") or []

    def save_tasks(
        self,
        user_hash: str,
        note_id: str,
        tasks: List[Dict[str, Any]],
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        for i, t in enumerate(tasks):
            t["order"] = i
            if not t.get("id"):
                t["id"] = new_entity_id("task", t.get("text") or "", str(i))
            # stamp completed_at when marked done
            if t.get("done") and not t.get("completed_at"):
                t["completed_at"] = utc_now()
            if not t.get("done"):
                t["completed_at"] = None
        body = serialize_tasklist({"tasks": tasks})
        open_count = sum(1 for t in tasks if not t.get("done") and not t.get("parent_id"))
        return self.notes.update_note(
            user_hash,
            note_id,
            title=title,
            body=body,
            kind="tasklist",
            extra_payload={"task_open_count": open_count, "task_total": len(tasks)},
        )

    def add_task(
        self,
        user_hash: str,
        note_id: str,
        text: str = "",
        linked_note_id: Optional[str] = None,
        due_date: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        tasks = self.get_tasks(user_hash, note_id)
        tasks.append(
            _norm_task(
                {
                    "id": new_entity_id("task", text or "new"),
                    "text": text or "",
                    "done": False,
                    "order": len(tasks),
                    "linked_note_id": linked_note_id,
                    "due_date": due_date,
                    "parent_id": parent_id,
                    "progress_ids": [],
                },
                len(tasks),
            )
        )
        return self.save_tasks(user_hash, note_id, tasks)

    def create_linked_note(
        self,
        user_hash: str,
        list_id: str,
        task_id: str,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a normal note and link it to the task."""
        tasks = self.get_tasks(user_hash, list_id)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            raise KeyError("task not found")
        note_title = title or (task.get("text") or "Nota da tarefa")[:80]
        note = self.notes.create_note(
            user_hash,
            title=note_title,
            body=f"<h1>{note_title}</h1><p>Nota vinculada à tarefa.</p>",
            kind="note",
            tags=["from_task"],
            extra_payload={
                "markers": ["#tarefa"],
                "linked_from_task": task_id,
                "linked_from_list": list_id,
            },
        )
        task["linked_note_id"] = note["entity_id"]
        self.save_tasks(user_hash, list_id, tasks)
        return note

    def add_progress(
        self,
        user_hash: str,
        list_id: str,
        task_id: str,
        text: str,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a hidden progress note (andamento) linked to the task."""
        tasks = self.get_tasks(user_hash, list_id)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            raise KeyError("task not found")
        task_text = (task.get("text") or "tarefa")[:60]
        prog_title = title or f"Andamento: {task_text}"
        note = self.notes.create_note(
            user_hash,
            title=prog_title,
            body=text or "",
            kind="task_progress",
            tags=["andamento", "hidden"],
            categories=["Andamentos"],
            extra_payload={
                "hidden": True,
                "parent_list_id": list_id,
                "parent_task_id": task_id,
                "markers": ["#andamento"],
            },
        )
        pids = list(task.get("progress_ids") or [])
        pids.append(note["entity_id"])
        task["progress_ids"] = pids
        self.save_tasks(user_hash, list_id, tasks)
        return note

    def list_progress(
        self,
        user_hash: str,
        list_id: str,
        task_id: str,
    ) -> List[Dict[str, Any]]:
        tasks = self.get_tasks(user_hash, list_id)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            return []
        out = []
        for pid in task.get("progress_ids") or []:
            try:
                n = self.notes.get_note(user_hash, pid, include_body=True)
                out.append(n)
            except KeyError:
                continue
        out.sort(key=lambda e: e.get("created_at") or e.get("updated_at") or "")
        return out

    def add_subtask(
        self,
        user_hash: str,
        list_id: str,
        parent_task_id: str,
        text: str = "",
        due_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.add_task(
            user_hash,
            list_id,
            text=text or "Subtarefa",
            due_date=due_date,
            parent_id=parent_task_id,
        )

    def list_open_tasks_summary(self, user_hash: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Flatten open top-level items from all tasklists for dashboard."""
        notes = self.notes.list_notes(user_hash, include_shared=True, include_body=False)
        out: List[Dict[str, Any]] = []
        for n in notes:
            if n.get("kind") != "tasklist":
                continue
            try:
                full = self.notes.get_note(user_hash, n["entity_id"], include_body=True)
            except KeyError:
                continue
            for t in parse_tasklist_body(full.get("body")).get("tasks") or []:
                if t.get("done") or t.get("parent_id"):
                    continue
                out.append(
                    {
                        "task_id": t["id"],
                        "text": t.get("text") or "",
                        "list_id": n["entity_id"],
                        "list_title": n.get("title") or "",
                        "linked_note_id": t.get("linked_note_id"),
                        "due_date": t.get("due_date"),
                        "progress_count": len(t.get("progress_ids") or []),
                    }
                )
                if len(out) >= limit:
                    return out
        return out
