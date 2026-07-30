"""Append-only JSONL blockchain-style ledgers for conflict-safe multi-machine sync.

Each chain file stores one JSON object (block) per line:

{
  "index": 0,
  "timestamp": "2026-07-27T12:00:00.000000Z",
  "hostname": "my-laptop",
  "machine_id": "...",
  "user_hash": "...",
  "prev_hash": "0"*64 or previous block hash,
  "action": "create|update|delete|share|revert|...",
  "entity_id": "sha256...",
  "payload": { ... },
  "block_hash": "sha256 of canonical fields"
}

Syncthing may deliver concurrent appends. On load we:
1. Parse all blocks
2. Deduplicate by block_hash
3. Sort by (timestamp, index, block_hash)
4. Rebuild the tip state by replaying actions
Invalid / orphaned blocks remain in history for audit but tip prefers latest valid timestamp.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from gltd_notes.utils.hashing import sha256_json

GENESIS_PREV = "0" * 64


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


@dataclass
class Block:
    index: int
    timestamp: str
    hostname: str
    machine_id: str
    user_hash: str
    prev_hash: str
    action: str
    entity_id: str
    payload: Dict[str, Any]
    block_hash: str = ""

    def compute_hash(self) -> str:
        body = {
            "index": self.index,
            "timestamp": self.timestamp,
            "hostname": self.hostname,
            "machine_id": self.machine_id,
            "user_hash": self.user_hash,
            "prev_hash": self.prev_hash,
            "action": self.action,
            "entity_id": self.entity_id,
            "payload": self.payload,
        }
        return sha256_json(body)

    def seal(self) -> "Block":
        self.block_hash = self.compute_hash()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "hostname": self.hostname,
            "machine_id": self.machine_id,
            "user_hash": self.user_hash,
            "prev_hash": self.prev_hash,
            "action": self.action,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "block_hash": self.block_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        return cls(
            index=int(d.get("index", 0)),
            timestamp=str(d.get("timestamp", "")),
            hostname=str(d.get("hostname", "")),
            machine_id=str(d.get("machine_id", "")),
            user_hash=str(d.get("user_hash", "")),
            prev_hash=str(d.get("prev_hash", GENESIS_PREV)),
            action=str(d.get("action", "")),
            entity_id=str(d.get("entity_id", "")),
            payload=dict(d.get("payload") or {}),
            block_hash=str(d.get("block_hash", "")),
        )

    def verify(self) -> bool:
        return self.block_hash == self.compute_hash()


@dataclass
class ChainState:
    """Materialized view of entities from a chain."""

    entities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    history: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    blocks: List[Block] = field(default_factory=list)
    tip_hash: str = GENESIS_PREV
    next_index: int = 0


class Blockchain:
    def __init__(
        self,
        path: Path,
        machine_id: str,
        hostname: Optional[str] = None,
        default_user_hash: str = "",
    ):
        self.path = Path(path)
        self.machine_id = machine_id
        self.hostname = hostname or socket.gethostname()
        self.default_user_hash = default_user_hash
        self._lock = threading.RLock()
        self._state_cache: Optional[ChainState] = None
        self._state_mtime: float = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def _read_raw_blocks(self) -> List[Block]:
        blocks: List[Block] = []
        if not self.path.exists():
            return blocks
        with open(self.path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    blocks.append(Block.from_dict(json.loads(line)))
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Keep going — corrupted line must not break the chain file
                    continue
        return blocks

    def _mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def load_state(self) -> ChainState:
        with self._lock:
            mtime = self._mtime()
            if self._state_cache is not None and mtime == self._state_mtime:
                return self._state_cache
            raw = self._read_raw_blocks()
            # Dedup by block_hash (Syncthing duplicate merges)
            seen = set()
            unique: List[Block] = []
            for b in raw:
                key = b.block_hash or b.compute_hash()
                if key in seen:
                    continue
                seen.add(key)
                if not b.block_hash:
                    b.block_hash = key
                unique.append(b)

            # Sort for deterministic replay: timestamp then index then hash
            unique.sort(key=lambda b: (parse_ts(b.timestamp), b.index, b.block_hash))

            state = ChainState()
            for b in unique:
                state.blocks.append(b)
                hist = state.history.setdefault(b.entity_id, [])
                hist.append(b.to_dict())
                self._apply(state, b)
            if unique:
                # tip: latest by time
                tip = max(unique, key=lambda b: (parse_ts(b.timestamp), b.index, b.block_hash))
                state.tip_hash = tip.block_hash
                state.next_index = max(b.index for b in unique) + 1
            self._state_cache = state
            self._state_mtime = mtime
            return state

    def _apply(self, state: ChainState, block: Block) -> None:
        eid = block.entity_id
        action = block.action
        payload = dict(block.payload or {})
        meta = {
            "updated_at": block.timestamp,
            "updated_by_user": block.user_hash,
            "updated_by_host": block.hostname,
            "updated_by_machine": block.machine_id,
            "last_action": action,
            "last_block_hash": block.block_hash,
        }
        if action in ("create", "update", "share", "unshare", "revert", "attach", "detach"):
            current = dict(state.entities.get(eid) or {})
            current.update(payload)
            current.update(meta)
            current["entity_id"] = eid
            if action == "create" and "created_at" not in current:
                current["created_at"] = block.timestamp
                current["created_by_user"] = block.user_hash
                current["created_by_host"] = block.hostname
            if action == "share":
                shares = list(current.get("shared_with") or [])
                for u in payload.get("shared_with") or []:
                    if u not in shares:
                        shares.append(u)
                current["shared_with"] = shares
                current["is_shared"] = True
            if action == "unshare":
                remove = set(payload.get("shared_with") or [])
                current["shared_with"] = [u for u in (current.get("shared_with") or []) if u not in remove]
                current["is_shared"] = bool(current["shared_with"])
            if action == "attach":
                files = list(current.get("file_hashes") or [])
                fh = payload.get("file_hash")
                if fh and fh not in files:
                    files.append(fh)
                current["file_hashes"] = files
            if action == "detach":
                fh = payload.get("file_hash")
                current["file_hashes"] = [x for x in (current.get("file_hashes") or []) if x != fh]
            state.entities[eid] = current
        elif action == "delete":
            if eid in state.entities:
                ent = dict(state.entities[eid])
                ent["deleted"] = True
                ent.update(meta)
                state.entities[eid] = ent
        else:
            # unknown action: still record payload merge
            current = dict(state.entities.get(eid) or {})
            current.update(payload)
            current.update(meta)
            current["entity_id"] = eid
            state.entities[eid] = current

    def append(
        self,
        action: str,
        entity_id: str,
        payload: Dict[str, Any],
        user_hash: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Block:
        with self._lock:
            state = self.load_state()
            block = Block(
                index=state.next_index,
                timestamp=timestamp or utc_now_iso(),
                hostname=self.hostname,
                machine_id=self.machine_id,
                user_hash=user_hash or self.default_user_hash,
                prev_hash=state.tip_hash or GENESIS_PREV,
                action=action,
                entity_id=entity_id,
                payload=payload or {},
            ).seal()
            line = json.dumps(block.to_dict(), ensure_ascii=False, separators=(",", ":"))
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._state_cache = None
            self._state_mtime = 0.0
            return block

    def history_for(self, entity_id: str) -> List[Dict[str, Any]]:
        state = self.load_state()
        return list(state.history.get(entity_id) or [])

    def get_entity(self, entity_id: str, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
        state = self.load_state()
        ent = state.entities.get(entity_id)
        if not ent:
            return None
        if ent.get("deleted") and not include_deleted:
            return None
        return dict(ent)

    def list_entities(
        self,
        include_deleted: bool = False,
        predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> List[Dict[str, Any]]:
        state = self.load_state()
        out = []
        for ent in state.entities.values():
            if ent.get("deleted") and not include_deleted:
                continue
            if predicate and not predicate(ent):
                continue
            out.append(dict(ent))
        out.sort(key=lambda e: e.get("updated_at") or e.get("created_at") or "", reverse=True)
        return out

    def validate(self) -> Dict[str, Any]:
        state = self.load_state()
        invalid = [b.block_hash for b in state.blocks if not b.verify()]
        return {
            "path": str(self.path),
            "block_count": len(state.blocks),
            "entity_count": len(state.entities),
            "invalid_hashes": invalid,
            "tip_hash": state.tip_hash,
            "ok": len(invalid) == 0,
        }
