"""Events / reminders service with notification helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from gltd_notes.services.app_context import AppContext
from gltd_notes.utils.hashing import new_entity_id, sha256_text


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class EventsService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def create_event(
        self,
        user_hash: str,
        title: str,
        body: str = "",
        due_at: Optional[str] = None,
        remind_at: Optional[str] = None,
        categories: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        event_id = new_entity_id("event", user_hash, title or "")
        store = self.ctx.user_store(user_hash)
        store.write_event_body(event_id, body or "")
        payload = {
            "title": title or "Event",
            "body_hash": sha256_text(body or ""),
            "body_path": f"{event_id}.gltdnote",
            "due_at": due_at,
            "remind_at": remind_at,
            "categories": categories or [],
            "notified": False,
            "completed": False,
            "kind": "event",
            "deleted": False,
        }
        self.ctx.user_chain(user_hash, "eventos").append(
            action="create",
            entity_id=event_id,
            payload=payload,
            user_hash=user_hash,
        )
        return self.get_event(user_hash, event_id, include_body=True)

    def update_event(
        self,
        user_hash: str,
        event_id: str,
        **fields: Any,
    ) -> Dict[str, Any]:
        existing = self._require(user_hash, event_id)
        payload = {
            "title": fields.get("title", existing.get("title")),
            "due_at": fields.get("due_at", existing.get("due_at")),
            "remind_at": fields.get("remind_at", existing.get("remind_at")),
            "categories": fields.get("categories", existing.get("categories") or []),
            "notified": fields.get("notified", existing.get("notified", False)),
            "completed": fields.get("completed", existing.get("completed", False)),
            "kind": "event",
            "deleted": False,
            "body_path": existing.get("body_path"),
            "body_hash": existing.get("body_hash"),
        }
        if "body" in fields and fields["body"] is not None:
            body = fields["body"]
            self.ctx.user_store(user_hash).write_event_body(event_id, body)
            payload["body_hash"] = sha256_text(body)
            payload["body_path"] = f"{event_id}.gltdnote"
        self.ctx.user_chain(user_hash, "eventos").append(
            action="update",
            entity_id=event_id,
            payload=payload,
            user_hash=user_hash,
        )
        return self.get_event(user_hash, event_id, include_body=True)

    def delete_event(self, user_hash: str, event_id: str) -> Dict[str, Any]:
        self._require(user_hash, event_id)
        self.ctx.user_chain(user_hash, "eventos").append(
            action="delete",
            entity_id=event_id,
            payload={"deleted": True},
            user_hash=user_hash,
        )
        return {"entity_id": event_id, "deleted": True}

    def get_event(self, user_hash: str, event_id: str, include_body: bool = True) -> Dict[str, Any]:
        meta = self._require(user_hash, event_id)
        out = dict(meta)
        if include_body:
            out["body"] = self.ctx.user_store(user_hash).read_event_body(event_id) or ""
        return out

    def list_events(
        self,
        user_hash: str,
        include_completed: bool = False,
        due_before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        items = self.ctx.user_chain(user_hash, "eventos").list_entities()
        if not include_completed:
            items = [e for e in items if not e.get("completed")]
        if due_before:
            limit = parse_iso(due_before)
            if limit:
                filtered = []
                for e in items:
                    due = parse_iso(e.get("due_at") or e.get("remind_at"))
                    if due and due <= limit:
                        filtered.append(e)
                items = filtered
        items.sort(key=lambda e: e.get("due_at") or e.get("remind_at") or e.get("updated_at") or "")
        return items

    def due_for_notification(self, user_hash: str) -> List[Dict[str, Any]]:
        now = utc_now()
        out = []
        for e in self.list_events(user_hash, include_completed=False):
            if e.get("notified"):
                continue
            when = parse_iso(e.get("remind_at") or e.get("due_at"))
            if when and when <= now:
                out.append(e)
        return out

    def mark_notified(self, user_hash: str, event_id: str) -> Dict[str, Any]:
        return self.update_event(user_hash, event_id, notified=True)

    def history(self, user_hash: str, event_id: str) -> List[Dict[str, Any]]:
        return self.ctx.user_chain(user_hash, "eventos").history_for(event_id)

    def _require(self, user_hash: str, event_id: str) -> Dict[str, Any]:
        meta = self.ctx.user_chain(user_hash, "eventos").get_entity(event_id)
        if not meta:
            raise KeyError(f"event not found: {event_id}")
        return meta
