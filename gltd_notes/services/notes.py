"""Note CRUD, history, revert, share and attachments.

Versioning policy
-----------------
* Body is **always** written to disk on save (no data loss while typing).
* Blockchain history blocks are **checkpoints** only:
  - first create
  - every ``history_checkpoint_seconds`` (default 5 min) since last checkpoint
  - large content change (default ≥ 120 chars of growth/shrink, or ≥ 30% rewrite)
  - forced actions: share, delete, attach, revert, ``force_history=True``
* Between checkpoints, tip metadata lives in ``databases/working/<id>.json``
  and is merged over chain state for list/get.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_log = logging.getLogger("gltd_notes.notes")

from gltd_notes.blockchain import parse_ts, utc_now_iso
from gltd_notes.services.app_context import AppContext
from gltd_notes.utils.hashing import new_entity_id, sha256_text

HASHTAG_RE = re.compile(r"(?<![\w#])#([A-Za-zÀ-ÿ0-9_]{2,64})")


def normalize_markers(markers: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for m in markers or []:
        s = str(m).strip()
        if not s:
            continue
        if not s.startswith("#"):
            s = "#" + s
        s = re.sub(r"[^\w#À-ÿ]", "_", s, flags=re.UNICODE)
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def extract_hashtags(*texts: str) -> List[str]:
    found: List[str] = []
    for text in texts:
        if not text:
            continue
        for m in HASHTAG_RE.findall(text):
            found.append("#" + m)
    return normalize_markers(found)


def _fold(s: str) -> str:
    """Lowercase + strip accents for fuzzy search."""
    s = (s or "").lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _query_matches(hay: str, query: str) -> bool:
    """Match full phrase or all tokens (order-independent)."""
    hay_f = _fold(hay)
    q = (query or "").strip()
    if not q:
        return True
    q_f = _fold(q)
    if q_f in hay_f:
        return True
    tokens = [t for t in re.split(r"\s+", q_f) if t]
    if len(tokens) > 1 and all(tok in hay_f for tok in tokens):
        return True
    return False


class NotesService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def _history_settings(self) -> tuple[int, int]:
        gui = self.ctx.config.data.get("gui") or {}
        seconds = int(gui.get("history_checkpoint_seconds") or 300)
        large = int(gui.get("history_large_change_chars") or 120)
        return max(30, seconds), max(20, large)

    def _working_path(self, user_hash: str, note_id: str) -> Path:
        layout = self.ctx.user_layout(user_hash)
        layout.working.mkdir(parents=True, exist_ok=True)
        return layout.working_path(note_id)

    def _write_working(self, user_hash: str, note_id: str, payload: Dict[str, Any]) -> None:
        path = self._working_path(user_hash, note_id)
        data = dict(payload)
        data["entity_id"] = note_id
        data["updated_at"] = utc_now_iso()
        data["working"] = True
        # never store full body snapshot in working tip (body is on disk)
        data.pop("body_snapshot", None)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)

    def _read_working(self, user_hash: str, note_id: str) -> Optional[Dict[str, Any]]:
        path = self._working_path(user_hash, note_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _clear_working(self, user_hash: str, note_id: str) -> None:
        path = self._working_path(user_hash, note_id)
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _apply_working_overlay(self, user_hash: str, ent: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(ent)
        w = self._read_working(user_hash, ent.get("entity_id") or "")
        if not w:
            return out
        # overlay tip fields if working is same or newer
        w_ts = w.get("updated_at") or ""
        e_ts = out.get("updated_at") or ""
        if w_ts and e_ts and parse_ts(w_ts) < parse_ts(e_ts):
            return out
        for k, v in w.items():
            if k in ("working",):
                continue
            out[k] = v
        out["has_working_tip"] = True
        return out

    def _last_checkpoint(self, user_hash: str, note_id: str) -> Optional[Dict[str, Any]]:
        hist = self.ctx.user_chain(user_hash, "notes").history_for(note_id)
        for b in reversed(hist):
            action = b.get("action")
            if action in ("create", "update", "revert", "share"):
                pl = b.get("payload") or {}
                # legacy blocks without flag count as checkpoints
                if action != "update" or pl.get("checkpoint", True):
                    return b
        return None

    def _is_large_change(self, old_body: str, new_body: Optional[str], large_chars: int) -> bool:
        if new_body is None:
            return False
        old = old_body or ""
        new = new_body or ""
        if abs(len(new) - len(old)) >= large_chars:
            return True
        # rewrite ratio for shorter notes
        base = max(len(old), len(new), 1)
        # cheap approx: common prefix length
        n = 0
        for a, b in zip(old, new):
            if a != b:
                break
            n += 1
        changed = base - n
        if changed >= large_chars:
            return True
        if base >= 40 and (changed / base) >= 0.30:
            return True
        return False

    def _should_checkpoint(
        self,
        user_hash: str,
        note_id: str,
        existing: Dict[str, Any],
        new_body: Optional[str],
        force_history: bool,
    ) -> bool:
        if force_history:
            return True
        seconds, large_chars = self._history_settings()
        last = self._last_checkpoint(user_hash, note_id)
        if not last:
            return True
        try:
            age = (datetime.now(timezone.utc) - parse_ts(last.get("timestamp") or "")).total_seconds()
        except Exception:
            age = seconds + 1
        if age >= seconds:
            return True
        old_snap = ""
        pl = last.get("payload") or {}
        old_snap = pl.get("body_snapshot")
        if old_snap is None:
            # fall back to file
            old_snap = self._read_body_fast(user_hash, note_id, "user")
        if self._is_large_change(old_snap or "", new_body, large_chars):
            return True
        return False

    def create_note(
        self,
        user_hash: str,
        title: str,
        body: str = "",
        categories: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        kind: str = "note",
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        note_id = new_entity_id("note", user_hash, title or "")
        store = self.ctx.user_store(user_hash)
        store.write_note_body(note_id, body or "")
        body_hash = sha256_text(body or "")
        payload = {
            "title": title or "Untitled",
            "body_hash": body_hash,
            "body_path": f"{note_id}.gltdnote",
            "body_snapshot": body or "",
            "categories": categories or [],
            "tags": tags or [],
            "file_hashes": [],
            "is_shared": False,
            "shared_with": [],
            "deleted": False,
            "kind": kind or "note",
            "markers": normalize_markers((extra_payload or {}).get("markers") if extra_payload else None),
            "checkpoint": True,
        }
        if extra_payload:
            payload.update(extra_payload)
            if "markers" in payload:
                payload["markers"] = normalize_markers(payload.get("markers"))
            payload["checkpoint"] = True
        block = self.ctx.user_chain(user_hash, "notes").append(
            action="create",
            entity_id=note_id,
            payload=payload,
            user_hash=user_hash,
        )
        # category index entries
        for cat in categories or []:
            self._ensure_category(user_hash, cat)
        note = self.get_note(user_hash, note_id, include_body=True)
        note["block_hash"] = block.block_hash
        note["checkpoint"] = True
        return note

    def update_note(
        self,
        user_hash: str,
        note_id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        categories: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        kind: Optional[str] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
        force_history: bool = False,
    ) -> Dict[str, Any]:
        existing = self._require_note_meta(user_hash, note_id)
        store = self.ctx.user_store(user_hash)
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            # always persist content immediately
            store.write_note_body(note_id, body)
            payload["body_hash"] = sha256_text(body)
            payload["body_path"] = f"{note_id}.gltdnote"
            payload["body_snapshot"] = body
        if categories is not None:
            payload["categories"] = categories
            for cat in categories:
                self._ensure_category(user_hash, cat)
        if tags is not None:
            payload["tags"] = tags
        # preserve sharing fields
        payload.setdefault("is_shared", existing.get("is_shared", False))
        payload.setdefault("shared_with", existing.get("shared_with") or [])
        payload.setdefault("file_hashes", existing.get("file_hashes") or [])
        payload.setdefault("kind", kind or existing.get("kind") or "note")
        payload.setdefault("deleted", False)
        if title is None:
            payload.setdefault("title", existing.get("title"))
        if body is None:
            payload.setdefault("body_hash", existing.get("body_hash"))
            payload.setdefault("body_path", existing.get("body_path"))
            # keep last snapshot only if we checkpoint (filled below)
        if categories is None:
            payload.setdefault("categories", existing.get("categories") or [])
        if tags is None:
            payload.setdefault("tags", existing.get("tags") or [])
        if extra_payload:
            payload.update(extra_payload)
        # markers: explicit in extra_payload, else keep existing (+ body hashtags if body updated)
        if extra_payload and "markers" in extra_payload:
            payload["markers"] = normalize_markers(extra_payload.get("markers"))
        else:
            payload.setdefault("markers", list(existing.get("markers") or []))
            if body is not None:
                merged = normalize_markers(
                    list(payload.get("markers") or []) + extract_hashtags(body, title or existing.get("title") or "")
                )
                payload["markers"] = merged
        # keep task counts if present on existing and not overridden
        for k in ("task_open_count", "task_total", "agent", "agent_status", "parent_id", "favorite"):
            if k not in payload and k in existing:
                payload[k] = existing[k]

        checkpoint = self._should_checkpoint(
            user_hash, note_id, existing, body, force_history=force_history
        )

        if not checkpoint:
            # tip only — no new history version
            tip = dict(payload)
            tip.pop("body_snapshot", None)  # body lives on disk
            if body is None:
                tip["body_hash"] = existing.get("body_hash")
                tip["body_path"] = existing.get("body_path")
            self._write_working(user_hash, note_id, tip)
            note = self.get_note(user_hash, note_id, include_body=True)
            note["checkpoint"] = False
            note["block_hash"] = existing.get("last_block_hash")
            return note

        # checkpoint: full history entry
        if body is None:
            # include snapshot from disk so revert works
            current_body = store.read_note_body(note_id) or ""
            payload["body_snapshot"] = current_body
            payload["body_hash"] = sha256_text(current_body)
            payload["body_path"] = f"{note_id}.gltdnote"
        payload["checkpoint"] = True
        block = self.ctx.user_chain(user_hash, "notes").append(
            action="update",
            entity_id=note_id,
            payload=payload,
            user_hash=user_hash,
        )
        self._clear_working(user_hash, note_id)
        if existing.get("is_shared"):
            self._mirror_shared_update(user_hash, note_id, payload, body if body is not None else None)
        note = self.get_note(user_hash, note_id, include_body=True)
        note["block_hash"] = block.block_hash
        note["checkpoint"] = True
        return note

    def delete_note(self, user_hash: str, note_id: str) -> Dict[str, Any]:
        self._require_note_meta(user_hash, note_id)
        self._clear_working(user_hash, note_id)
        block = self.ctx.user_chain(user_hash, "notes").append(
            action="delete",
            entity_id=note_id,
            payload={"deleted": True, "checkpoint": True},
            user_hash=user_hash,
        )
        return {"entity_id": note_id, "deleted": True, "block_hash": block.block_hash}

    def get_note(self, user_hash: str, note_id: str, include_body: bool = True) -> Dict[str, Any]:
        # try private first, then shared
        meta = self.ctx.user_chain(user_hash, "notes").get_entity(note_id)
        source = "user"
        if not meta:
            meta = self.ctx.shared_chain("notes").get_entity(note_id)
            source = "shared"
        if not meta:
            # may exist only as working tip (shouldn't normally)
            w = self._read_working(user_hash, note_id)
            if not w:
                raise KeyError(f"note not found: {note_id}")
            meta = w
        out = dict(meta)
        if source == "user":
            out = self._apply_working_overlay(user_hash, out)
        out["source"] = source
        if include_body:
            if source == "user":
                body = self.ctx.user_store(user_hash).read_note_body(note_id)
            else:
                body = self.ctx.shared_store().read_note_body(note_id)
            out["body"] = body if body is not None else ""
        return out

    def _read_body_fast(self, user_hash: str, note_id: str, source: str = "user") -> str:
        """Read note body from disk without reloading the blockchain."""
        if source == "shared":
            body = self.ctx.shared_store().read_note_body(note_id)
        else:
            body = self.ctx.user_store(user_hash).read_note_body(note_id)
        return body if body is not None else ""

    @staticmethod
    def body_for_search(body: str) -> str:
        """Strip simple HTML tags so rich notes remain searchable as text."""
        if not body:
            return ""
        if "<" not in body:
            return body
        import re
        import html as html_lib

        t = re.sub(r"(?i)<br\s*/?>", "\n", body)
        t = re.sub(r"(?i)</(p|div|h[1-6]|li)>", "\n", t)
        t = re.sub(r"<[^>]+>", " ", t)
        return html_lib.unescape(t)

    def list_notes(
        self,
        user_hash: str,
        query: Optional[str] = None,
        category: Optional[str] = None,
        include_shared: bool = True,
        include_body: bool = False,
        marker: Optional[str] = None,
        include_peers: bool = True,
    ) -> List[Dict[str, Any]]:
        # list_entities() loads the chain once per call — do not call get_note() per item
        notes = self.ctx.user_chain(user_hash, "notes").list_entities()
        for n in notes:
            n["source"] = "user"
            # overlay draft tip (title/markers/updated_at without new history)
            overlaid = self._apply_working_overlay(user_hash, n)
            n.clear()
            n.update(overlaid)
            n["source"] = "user"
        if include_peers:
            # Read notes from other machines' synced folders (same network)
            seen = {n["entity_id"] for n in notes}
            for peer_hash in self.ctx.list_local_user_hashes():
                if peer_hash == user_hash:
                    continue
                try:
                    peer_notes = self.ctx.user_chain(peer_hash, "notes").list_entities()
                except Exception:
                    continue
                for p in peer_notes:
                    if p.get("entity_id") in seen:
                        continue
                    p["source"] = "peer"
                    p["peer_hash"] = peer_hash
                    notes.append(p)
        if include_shared:
            shared = self.ctx.shared_chain("notes").list_entities(
                predicate=lambda e: (
                    user_hash in (e.get("shared_with") or [])
                    or e.get("owner_user_hash") == user_hash
                )
            )
            seen = {n["entity_id"] for n in notes}
            for s in shared:
                if s["entity_id"] not in seen:
                    s["source"] = "shared"
                    notes.append(s)
        # Hide progress notes (andamentos) and other hidden kinds from normal lists
        notes = [
            n
            for n in notes
            if not n.get("hidden")
            and (n.get("kind") or "note") not in ("task_progress",)
        ]
        if category:
            notes = [n for n in notes if category in (n.get("categories") or [])]
        if marker:
            m = marker if marker.startswith("#") else f"#{marker}"
            m = m.lower()
            notes = [
                n
                for n in notes
                if m in [x.lower() for x in (n.get("markers") or [])]
                or m in " ".join(n.get("tags") or []).lower()
            ]
        if query:
            q = query.strip()
            filtered = []
            for n in notes:
                try:
                    body = self._read_body_fast(user_hash, n["entity_id"], n.get("source") or "user")
                except Exception as exc:
                    _log.warning("skip note %s during search: %s", n.get("entity_id", "?"), exc)
                    continue
                hay = " ".join(
                    [
                        n.get("title") or "",
                        " ".join(n.get("tags") or []),
                        " ".join(n.get("categories") or []),
                        " ".join(n.get("markers") or []),
                        self.body_for_search(body),
                    ]
                )
                if _query_matches(hay, q):
                    if include_body:
                        nn = dict(n)
                        nn["body"] = body
                        filtered.append(nn)
                    else:
                        filtered.append(n)
            notes = filtered
        elif include_body:
            enriched = []
            for n in notes:
                nn = dict(n)
                nn["body"] = self._read_body_fast(user_hash, n["entity_id"], n.get("source") or "user")
                enriched.append(nn)
            notes = enriched
        notes.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
        return notes

    def history(self, user_hash: str, note_id: str) -> List[Dict[str, Any]]:
        hist = self.ctx.user_chain(user_hash, "notes").history_for(note_id)
        if not hist:
            hist = self.ctx.shared_chain("notes").history_for(note_id)
        return hist

    def history_grouped(
        self,
        user_hash: str,
        note_id: str,
        window_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """History for UI: only meaningful checkpoints, collapsed into 5‑min buckets.

        Old noisy update spam is grouped so the side panel stays readable.
        """
        seconds, _ = self._history_settings()
        if window_seconds is None:
            window_seconds = seconds
        hist = self.history(user_hash, note_id)
        # Prefer explicit checkpoints; keep create/delete/share/attach/revert always
        meaningful: List[Dict[str, Any]] = []
        for b in hist:
            action = b.get("action") or ""
            pl = b.get("payload") or {}
            if action in ("create", "delete", "share", "unshare", "attach", "detach", "revert"):
                meaningful.append(b)
            elif action == "update":
                # skip legacy non-checkpoint noise only if flag is explicitly False
                if pl.get("checkpoint", True):
                    meaningful.append(b)
            else:
                meaningful.append(b)

        if not meaningful:
            return []

        # Collapse only legacy noisy update spam (no explicit checkpoint field).
        # Modern checkpoints (checkpoint=True) are each kept as a version.
        groups: List[Dict[str, Any]] = []
        bucket: List[Dict[str, Any]] = []

        def is_legacy_update(b: Dict[str, Any]) -> bool:
            if b.get("action") != "update":
                return False
            pl = b.get("payload") or {}
            return "checkpoint" not in pl

        def flush() -> None:
            nonlocal bucket
            if not bucket:
                return
            newest = bucket[-1]
            entry = dict(newest)
            entry["group_size"] = len(bucket)
            entry["group_from"] = bucket[0].get("timestamp")
            entry["group_to"] = newest.get("timestamp")
            groups.append(entry)
            bucket = []

        for b in meaningful:
            if is_legacy_update(b):
                if bucket and is_legacy_update(bucket[-1]):
                    try:
                        dt = (
                            parse_ts(b.get("timestamp") or "")
                            - parse_ts(bucket[-1].get("timestamp") or "")
                        ).total_seconds()
                    except Exception:
                        dt = window_seconds + 1
                    if 0 <= dt <= window_seconds:
                        bucket.append(b)
                        continue
                flush()
                bucket = [b]
            else:
                flush()
                entry = dict(b)
                entry["group_size"] = 1
                groups.append(entry)
        flush()
        return groups

    def revert(self, user_hash: str, note_id: str, block_hash: str) -> Dict[str, Any]:
        hist = self.history(user_hash, note_id)
        target = None
        for b in hist:
            if b.get("block_hash") == block_hash:
                target = b
                break
        if not target:
            raise KeyError(f"history block not found: {block_hash}")
        payload = dict(target.get("payload") or {})
        body = payload.get("body_snapshot")
        if body is None:
            try:
                current = self.get_note(user_hash, note_id, include_body=True)
                body = current.get("body", "")
            except KeyError:
                body = ""
        if "body_snapshot" in payload:
            body = payload["body_snapshot"]
        return self.update_note(
            user_hash=user_hash,
            note_id=note_id,
            title=payload.get("title"),
            body=body,
            categories=payload.get("categories"),
            tags=payload.get("tags"),
            extra_payload={
                "markers": payload.get("markers") or [],
                "kind": payload.get("kind") or "note",
            },
            force_history=True,
        )

    def attach_file(
        self,
        user_hash: str,
        note_id: str,
        source: Union[str, Path, bytes],
        original_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_note_meta(user_hash, note_id)
        store = self.ctx.user_store(user_hash)
        if isinstance(source, (bytes, bytearray)):
            content_hash = store.store_bytes(bytes(source), original_name=original_name)
        else:
            content_hash = store.store_file(source, original_name=original_name)

        files_chain = self.ctx.user_chain(user_hash, "files")
        if not files_chain.get_entity(content_hash):
            files_chain.append(
                action="create",
                entity_id=content_hash,
                payload={
                    "sha256": content_hash,
                    "original_name": original_name,
                    "subdir": content_hash[:3],
                },
                user_hash=user_hash,
            )
        link_id = sha256_text(f"{note_id}:{content_hash}")
        self.ctx.user_chain(user_hash, "arquivos_nota").append(
            action="create",
            entity_id=link_id,
            payload={"note_id": note_id, "file_hash": content_hash, "original_name": original_name},
            user_hash=user_hash,
        )
        self.ctx.user_chain(user_hash, "notes").append(
            action="attach",
            entity_id=note_id,
            payload={"file_hash": content_hash, "original_name": original_name},
            user_hash=user_hash,
        )
        return {"note_id": note_id, "file_hash": content_hash, "original_name": original_name}

    def share_note(self, owner_hash: str, note_id: str, target_user_hashes: List[str]) -> Dict[str, Any]:
        meta = self._require_note_meta(owner_hash, note_id)
        body = self.ctx.user_store(owner_hash).read_note_body(note_id) or ""
        # write into shared store
        shared_store = self.ctx.shared_store()
        shared_store.write_note_body(note_id, body)
        # copy attachments
        for fh in meta.get("file_hashes") or []:
            shared_store.copy_file_to_layout(fh, self.ctx.user_layout(owner_hash))

        payload = {
            "title": meta.get("title"),
            "body_hash": meta.get("body_hash"),
            "body_path": meta.get("body_path"),
            "categories": meta.get("categories") or [],
            "tags": meta.get("tags") or [],
            "file_hashes": meta.get("file_hashes") or [],
            "owner_user_hash": owner_hash,
            "shared_with": target_user_hashes,
            "is_shared": True,
            "kind": "note",
            "deleted": False,
        }
        self.ctx.shared_chain("notes").append(
            action="share",
            entity_id=note_id,
            payload=payload,
            user_hash=owner_hash,
        )
        self.ctx.user_chain(owner_hash, "notes").append(
            action="share",
            entity_id=note_id,
            payload={"shared_with": target_user_hashes, "is_shared": True},
            user_hash=owner_hash,
        )
        return self.get_note(owner_hash, note_id, include_body=True)

    def _mirror_shared_update(
        self,
        user_hash: str,
        note_id: str,
        payload: Dict[str, Any],
        body: Optional[str],
    ) -> None:
        if body is not None:
            self.ctx.shared_store().write_note_body(note_id, body)
        shared_payload = dict(payload)
        shared_payload["owner_user_hash"] = user_hash
        self.ctx.shared_chain("notes").append(
            action="update",
            entity_id=note_id,
            payload=shared_payload,
            user_hash=user_hash,
        )

    def _require_note_meta(self, user_hash: str, note_id: str) -> Dict[str, Any]:
        meta = self.ctx.user_chain(user_hash, "notes").get_entity(note_id)
        if not meta:
            raise KeyError(f"note not found: {note_id}")
        return self._apply_working_overlay(user_hash, meta)

    def _ensure_category(self, user_hash: str, name: str) -> None:
        cat_id = sha256_text(f"cat:{user_hash}:{name.lower()}")
        chain = self.ctx.user_chain(user_hash, "categories")
        if not chain.get_entity(cat_id):
            chain.append(
                action="create",
                entity_id=cat_id,
                payload={"name": name},
                user_hash=user_hash,
            )

    def list_categories(self, user_hash: str) -> List[Dict[str, Any]]:
        return self.ctx.user_chain(user_hash, "categories").list_entities()
