"""SHA-256 helpers used for note IDs, file content addressing, and chain blocks."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from pathlib import Path
from typing import Any, Union


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Union[str, Path], chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    """Stable hash of a JSON-serializable object (sorted keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256_text(payload)


def new_entity_id(*parts: str) -> str:
    """Create a unique SHA-256 id from hostname, uuid and optional parts."""
    seed = "|".join(
        [
            socket.gethostname(),
            str(uuid.uuid4()),
            str(os.getpid()),
            *parts,
        ]
    )
    return sha256_text(seed)


def content_subdir(content_hash: str) -> str:
    """First 3 hex chars of a SHA-256 used as subdirectory name."""
    if len(content_hash) < 3:
        raise ValueError("hash too short for subdirectory")
    return content_hash[:3]
