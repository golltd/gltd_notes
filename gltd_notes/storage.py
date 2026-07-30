"""Content-addressed note and attachment storage on disk."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Union

from gltd_notes.utils.hashing import content_subdir, sha256_bytes, sha256_file
from gltd_notes.utils.paths import DataLayout, NOTE_EXT


class FileStore:
    def __init__(self, layout: DataLayout):
        self.layout = layout
        self.layout.ensure()

    def write_note_body(self, note_id: str, body: str) -> Path:
        path = self.layout.note_path(note_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body if body is not None else "")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return path

    def read_note_body(self, note_id: str) -> Optional[str]:
        path = self.layout.note_path(note_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def write_event_body(self, event_id: str, body: str) -> Path:
        path = self.layout.event_note_path(event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body if body is not None else "")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return path

    def read_event_body(self, event_id: str) -> Optional[str]:
        path = self.layout.event_note_path(event_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def store_bytes(self, data: bytes, original_name: Optional[str] = None) -> str:
        content_hash = sha256_bytes(data)
        dest = self.layout.file_path(content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            tmp = dest.with_suffix(".tmp")
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        # optional sidecar metadata (not required by hash name)
        meta_path = dest.with_suffix(".meta.json")
        if original_name and not meta_path.exists():
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"original_name": original_name, "sha256": content_hash}, f)
        return content_hash

    def store_file(self, source: Union[str, Path], original_name: Optional[str] = None) -> str:
        source = Path(source)
        content_hash = sha256_file(source)
        dest = self.layout.file_path(content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            tmp = dest.with_suffix(".tmp")
            shutil.copy2(source, tmp)
            os.replace(tmp, dest)
        name = original_name or source.name
        meta_path = dest.with_suffix(".meta.json")
        if name and not meta_path.exists():
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"original_name": name, "sha256": content_hash}, f)
        return content_hash

    def resolve_file(self, content_hash: str) -> Optional[Path]:
        path = self.layout.file_path(content_hash)
        return path if path.exists() else None

    def copy_file_to_layout(self, content_hash: str, src_layout: DataLayout) -> Optional[Path]:
        """Copy a content-addressed file from another layout (e.g. user -> shared)."""
        src = src_layout.file_path(content_hash)
        if not src.exists():
            return None
        dest = self.layout.file_path(content_hash)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(src, dest)
        meta_src = src.with_suffix(".meta.json")
        meta_dest = dest.with_suffix(".meta.json")
        if meta_src.exists() and not meta_dest.exists():
            shutil.copy2(meta_src, meta_dest)
        return dest
