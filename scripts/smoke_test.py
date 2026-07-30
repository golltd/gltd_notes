#!/usr/bin/env python3
"""Non-GUI smoke test for core storage + API."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gltd_notes.api.server import APIServer
from gltd_notes.config import Config
from gltd_notes.services.app_context import AppContext
from gltd_notes.services.events import EventsService
from gltd_notes.services.notes import NotesService


def http_json(method: str, url: str, key: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gltd_notes_test_"))
    cfg_path = tmp / "config.json"
    data_root = tmp / "data"

    config = Config(cfg_path)
    config.data_root = data_root
    config.data["api"]["host"] = "127.0.0.1"
    config.data["api"]["port"] = 18765
    u1 = config.add_user("alice", "secret1", "Alice")
    u2 = config.add_user("bob", "secret2", "Bob")
    config.setup_complete = True
    config.save()

    ctx = AppContext(config)
    ctx.ensure_data_tree()
    notes = NotesService(ctx)
    events = EventsService(ctx)

    n = notes.create_note(u1["user_hash"], "Test note", "hello world", categories=["t"])
    assert n["entity_id"]
    assert (data_root / "user" / u1["user_hash"] / "notas" / f"{n['entity_id']}.gltdnote").exists()

    n2 = notes.update_note(u1["user_hash"], n["entity_id"], body="hello world v2")
    hist = notes.history(u1["user_hash"], n["entity_id"])
    assert len(hist) >= 2
    first_hash = hist[0]["block_hash"]
    notes.revert(u1["user_hash"], n["entity_id"], first_hash)
    body = notes.get_note(u1["user_hash"], n["entity_id"])["body"]
    assert body == "hello world", body

    # attachment
    sample = tmp / "sample.bin"
    sample.write_bytes(b"abc123")
    att = notes.attach_file(u1["user_hash"], n["entity_id"], sample, "sample.bin")
    fpath = data_root / "user" / u1["user_hash"] / "arquivos" / att["file_hash"][:3] / att["file_hash"]
    assert fpath.exists()

    shared = notes.share_note(u1["user_hash"], n["entity_id"], [u2["user_hash"]])
    assert shared["is_shared"]
    bob_notes = notes.list_notes(u2["user_hash"], include_shared=True)
    assert any(x["entity_id"] == n["entity_id"] for x in bob_notes)

    ev = events.create_event(
        u1["user_hash"],
        "Soon",
        "body",
        due_at="2000-01-01T00:00:00Z",
        remind_at="2000-01-01T00:00:00Z",
    )
    due = events.due_for_notification(u1["user_hash"])
    assert any(e["entity_id"] == ev["entity_id"] for e in due)

    # API
    api = APIServer(ctx)
    api.start_background()
    time.sleep(0.3)
    key = config.api_key
    base = "http://127.0.0.1:18765"
    health = http_json("GET", f"{base}/api/v1/health", key)
    assert health["ok"]
    listed = http_json("GET", f"{base}/api/v1/notes?user_hash={u1['user_hash']}", key)
    assert listed["ok"] and len(listed["notes"]) >= 1
    created = http_json(
        "POST",
        f"{base}/api/v1/notes",
        key,
        {"title": "API note", "body": "via http", "user_hash": u1["user_hash"]},
    )
    assert created["ok"]

    report = http_json("GET", f"{base}/api/v1/chains/validate?user_hash={u1['user_hash']}", key)
    assert report["ok"]
    for name, r in report["report"].items():
        if name == "shared_notes":
            continue
        assert r["ok"], r

    print("SMOKE OK")
    print(f"temp data: {tmp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
