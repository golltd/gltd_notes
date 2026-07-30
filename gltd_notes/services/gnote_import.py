"""Import Tomboy/GNote .note files into GLTD Notes.

Read-only on the GNote tree — never modifies or deletes source files.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from gltd_notes.blockchain import GENESIS_PREV, Block, utc_now_iso
from gltd_notes.services.app_context import AppContext
from gltd_notes.utils.hashing import sha256_text

TOMBOY_NS = "http://beatniksoftware.com/tomboy"
LINK_NS = "http://beatniksoftware.com/tomboy/link"
SIZE_NS = "http://beatniksoftware.com/tomboy/size"

# Register so ElementTree writes/reads consistently if needed
ET.register_namespace("", TOMBOY_NS)
ET.register_namespace("link", LINK_NS)
ET.register_namespace("size", SIZE_NS)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag.startswith("{") else tag


def _normalize_gnote_ts(ts: Optional[str]) -> Optional[str]:
    """Convert GNote/Tomboy timestamps to UTC ISO Z."""
    if not ts:
        return None
    s = ts.strip()
    # GNote sometimes uses comma as fractional separator: 2024-10-03T19:18:38,060990Z
    s = s.replace(",", ".")
    # Truncate overly long fractional seconds (Windows .NET style .6484670)
    m = re.match(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$",
        s,
    )
    if m:
        base, frac, rest = m.group(1), m.group(2) or "", m.group(3) or ""
        if frac:
            # keep up to 6 digits
            digits = frac[1:]
            frac = "." + digits[:6].ljust(6, "0")[:6]
        s = base + frac + rest
    if s.endswith("Z"):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            return s
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # assume local Brazil-ish if no tz — store as-is marked Z only if UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return s


def _element_to_text(el: ET.Element) -> str:
    """Flatten Tomboy note-content XML to plain text (preserve line breaks)."""
    parts: List[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in list(node):
            name = _local(child.tag)
            if name in ("list",):
                walk(child)
            elif name == "list-item":
                # bullet
                parts.append("• ")
                walk(child)
                if not (parts and parts[-1].endswith("\n")):
                    parts.append("\n")
            else:
                # bold, italic, monospace, link:*, size:*, etc. — keep text only
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(el)
    text = "".join(parts)
    # GNote often duplicates title as first line of content — keep as-is
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class ParsedGNote:
    gnote_id: str
    source_path: str
    title: str
    body: str
    tags: List[str] = field(default_factory=list)
    notebooks: List[str] = field(default_factory=list)
    create_date: Optional[str] = None
    last_change_date: Optional[str] = None
    is_template: bool = False
    is_conflict: bool = False


def parse_gnote_file(path: Path) -> ParsedGNote:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        text = raw.decode("utf-8", errors="replace")

    root = ET.fromstring(text)
    children = {_local(c.tag): c for c in root}

    title = (children["title"].text if "title" in children and children["title"].text else "") or ""
    title = title.strip() or "(untitled)"

    body = ""
    if "text" in children:
        # note-content is usually nested inside text
        note_content = None
        for c in children["text"].iter():
            if _local(c.tag) == "note-content":
                note_content = c
                break
        if note_content is not None:
            body = _element_to_text(note_content)
        else:
            body = "".join(children["text"].itertext())

    tags: List[str] = []
    notebooks: List[str] = []
    is_template = False
    if "tags" in children:
        for tag_el in children["tags"]:
            if _local(tag_el.tag) != "tag":
                continue
            t = (tag_el.text or "").strip()
            if not t:
                continue
            if t == "system:template":
                is_template = True
                tags.append(t)
            elif t.startswith("system:notebook:"):
                nb = t[len("system:notebook:") :]
                notebooks.append(nb)
                tags.append(t)
            else:
                tags.append(t)

    create = _normalize_gnote_ts(children["create-date"].text if "create-date" in children else None)
    changed = _normalize_gnote_ts(
        children["last-change-date"].text if "last-change-date" in children else None
    )

    gnote_id = path.stem
    # sync-conflict files: uuid.sync-conflict-...
    is_conflict = "sync-conflict" in path.name

    return ParsedGNote(
        gnote_id=gnote_id.split(".sync-conflict")[0] if is_conflict else gnote_id,
        source_path=str(path),
        title=title + (" [sync-conflict]" if is_conflict else ""),
        body=body or "",
        tags=tags,
        notebooks=notebooks,
        create_date=create,
        last_change_date=changed,
        is_template=is_template,
        is_conflict=is_conflict,
    )


def gltd_note_id_for_gnote(gnote_id: str, conflict_suffix: str = "") -> str:
    """Stable SHA-256 id so re-import is idempotent."""
    return sha256_text(f"gnote-import:{gnote_id}{conflict_suffix}")


def iter_gnote_files(gnote_dir: Path, include_conflicts: bool = False) -> Iterable[Path]:
    gnote_dir = Path(gnote_dir).resolve()
    for p in sorted(gnote_dir.glob("*.note")):
        if not p.is_file():
            continue
        if "sync-conflict" in p.name and not include_conflicts:
            continue
        yield p


@dataclass
class ImportResult:
    total_files: int = 0
    imported: int = 0
    skipped_existing: int = 0
    skipped_template: bool | int = 0
    errors: List[str] = field(default_factory=list)
    notebooks: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total_files": self.total_files,
            "imported": self.imported,
            "skipped_existing": self.skipped_existing,
            "skipped_template": self.skipped_template,
            "error_count": len(self.errors),
            "errors": self.errors[:50],
            "notebooks": self.notebooks,
        }


class _FastChainAppender:
    """Append many blocks without re-reading the full chain each time."""

    def __init__(self, chain_path: Path, machine_id: str, hostname: str, user_hash: str):
        self.path = Path(chain_path)
        self.machine_id = machine_id
        self.hostname = hostname
        self.user_hash = user_hash
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        tip = GENESIS_PREV
        next_index = 0
        existing_ids: set[str] = set()
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json

                    d = json.loads(line)
                except Exception:
                    continue
                existing_ids.add(str(d.get("entity_id") or ""))
                tip = str(d.get("block_hash") or tip)
                try:
                    next_index = max(next_index, int(d.get("index", 0)) + 1)
                except (TypeError, ValueError):
                    pass
        self.tip = tip
        self.next_index = next_index
        self.existing_ids = existing_ids
        self._fh = open(self.path, "a", encoding="utf-8")

    def has_entity(self, entity_id: str) -> bool:
        return entity_id in self.existing_ids

    def append(
        self,
        action: str,
        entity_id: str,
        payload: Dict[str, Any],
        timestamp: Optional[str] = None,
    ) -> Block:
        block = Block(
            index=self.next_index,
            timestamp=timestamp or utc_now_iso(),
            hostname=self.hostname,
            machine_id=self.machine_id,
            user_hash=self.user_hash,
            prev_hash=self.tip or GENESIS_PREV,
            action=action,
            entity_id=entity_id,
            payload=payload,
        ).seal()
        import json
        import os

        line = json.dumps(block.to_dict(), ensure_ascii=False, separators=(",", ":"))
        self._fh.write(line + "\n")
        self.tip = block.block_hash
        self.next_index += 1
        self.existing_ids.add(entity_id)
        return block

    def close(self) -> None:
        try:
            self._fh.flush()
            import os

            os.fsync(self._fh.fileno())
        finally:
            self._fh.close()


class GNoteImporter:
    def __init__(self, ctx: AppContext, user_hash: str):
        self.ctx = ctx
        self.user_hash = user_hash

    def import_directory(
        self,
        gnote_dir: Path,
        include_conflicts: bool = False,
        skip_templates: bool = True,
        progress_every: int = 100,
    ) -> ImportResult:
        gnote_dir = Path(gnote_dir)
        if not gnote_dir.is_dir():
            raise FileNotFoundError(f"GNote directory not found: {gnote_dir}")

        result = ImportResult()
        layout = self.ctx.user_layout(self.user_hash)
        store = self.ctx.user_store(self.user_hash)

        notes_app = _FastChainAppender(
            layout.chain_path("notes"),
            machine_id=self.ctx.config.machine_id,
            hostname=self.ctx.config.hostname,
            user_hash=self.user_hash,
        )
        cats_app = _FastChainAppender(
            layout.chain_path("categories"),
            machine_id=self.ctx.config.machine_id,
            hostname=self.ctx.config.hostname,
            user_hash=self.user_hash,
        )
        known_categories: set[str] = set(cats_app.existing_ids)

        try:
            files = list(iter_gnote_files(gnote_dir, include_conflicts=include_conflicts))
            result.total_files = len(files)
            for i, path in enumerate(files, 1):
                try:
                    parsed = parse_gnote_file(path)
                    if skip_templates and parsed.is_template:
                        result.skipped_template = int(result.skipped_template) + 1
                        continue

                    conflict_suffix = ""
                    if parsed.is_conflict:
                        # unique id per conflict file name
                        conflict_suffix = f":conflict:{path.name}"

                    note_id = gltd_note_id_for_gnote(parsed.gnote_id, conflict_suffix)
                    if notes_app.has_entity(note_id):
                        result.skipped_existing += 1
                        continue

                    store.write_note_body(note_id, parsed.body)
                    body_hash = sha256_text(parsed.body)

                    categories = list(parsed.notebooks) or []
                    if not categories:
                        categories = ["GNote"]
                    for nb in categories:
                        result.notebooks[nb] = result.notebooks.get(nb, 0) + 1
                        cat_id = sha256_text(f"cat:{self.user_hash}:{nb.lower()}")
                        if cat_id not in known_categories:
                            cats_app.append(
                                action="create",
                                entity_id=cat_id,
                                payload={"name": nb, "imported_from": "gnote"},
                            )
                            known_categories.add(cat_id)

                    tags = [t for t in parsed.tags if not t.startswith("system:notebook:")]
                    tags = list(dict.fromkeys(tags + ["imported:gnote"]))

                    payload = {
                        "title": parsed.title,
                        "body_hash": body_hash,
                        "body_path": f"{note_id}.gltdnote",
                        "body_snapshot": parsed.body,
                        "categories": categories,
                        "tags": tags,
                        "file_hashes": [],
                        "is_shared": False,
                        "shared_with": [],
                        "deleted": False,
                        "kind": "note",
                        "source": "gnote",
                        "gnote_id": parsed.gnote_id,
                        "gnote_path": parsed.source_path,
                        "gnote_create_date": parsed.create_date,
                        "gnote_last_change_date": parsed.last_change_date,
                        "created_at": parsed.create_date or utc_now_iso(),
                    }
                    notes_app.append(
                        action="create",
                        entity_id=note_id,
                        payload=payload,
                        timestamp=parsed.last_change_date or parsed.create_date or utc_now_iso(),
                    )
                    result.imported += 1
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"{path.name}: {e}")

                if progress_every and i % progress_every == 0:
                    print(f"[gnote-import] {i}/{result.total_files} processed… "
                          f"imported={result.imported} skip={result.skipped_existing} err={len(result.errors)}")
        finally:
            notes_app.close()
            cats_app.close()

        return result
