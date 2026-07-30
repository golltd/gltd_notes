# Architecture

## Goals

1. Reliable personal notes without a cloud vendor.
2. Multi-machine sync via **Syncthing** (folder sync only).
3. Avoid silent data loss under concurrent edits (GNote `.sync-conflict-*` pain).
4. Local automation via REST.
5. Optional attachments with content-addressed deduplication.

## Components

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  GTK GUI    │   │  Web UI     │   │  Other apps │
│  + tray     │   │  (optional) │   │  (curl/…)   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       │                 │                 │
       │          localhost only           │
       └────────────────┬──────────────────┘
                        │
                 ┌──────▼──────┐
                 │  REST API   │  X-API-Key
                 │  (stdlib)   │
                 └──────┬──────┘
                        │
                 ┌──────▼──────┐
                 │  Services   │  notes / events / auth
                 └──────┬──────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
     FileStore     Blockchain     Config/Session
   (.gltdnote,     (*.chain.jsonl)  (~/.config)
    arquivos/)
```

## Blockchain ledgers

Each `*.chain.jsonl` file is an **append-only log**. A block:

| Field | Purpose |
|-------|---------|
| `index` | Local monotonic counter at write time (not globally unique) |
| `timestamp` | UTC ISO-8601 with microseconds |
| `hostname` | Machine name that produced the block |
| `machine_id` | Stable id from local config |
| `user_hash` | Logical user |
| `prev_hash` | Previous tip hash known at write time |
| `action` | `create`, `update`, `delete`, `share`, `attach`, `revert`, … |
| `entity_id` | Note/event/file link id (SHA-256) |
| `payload` | Action-specific JSON (includes `body_snapshot` for notes) |
| `block_hash` | SHA-256 of canonical JSON of the above fields |

### Replay / merge rules

When loading a chain (after Syncthing sync):

1. Parse all non-empty lines; skip corrupt lines.
2. Deduplicate by `block_hash`.
3. Sort by `(timestamp, index, block_hash)`.
4. Replay into an in-memory entity map.
5. Tip entity = last applied non-deleted state per `entity_id`.
6. Full block list remains as **history** for UI revert and audit.

If two machines edit the same note offline, **both updates remain in history**. The tip is the later timestamp; the user can revert to any earlier block. This is intentionally simpler than CRDT full-text merge, but far safer than last-writer-wins file overwrite.

## Content storage

| Kind | Path | Naming |
|------|------|--------|
| Note body | `notas/<id>.gltdnote` | UTF-8 text |
| Event body | `eventos/<id>.gltdnote` | UTF-8 text |
| Attachment | `arquivos/<abc>/<sha256>` | raw bytes, no extension |
| Attachment meta | `*.meta.json` sidecar | original filename |

Atomic writes use `*.tmp` + `os.replace` + `fsync`.

## Multi-user paths

```
data_root/user/<user_hash>/...
data_root/shared/...
```

Sharing copies note body (and known attachments) into `shared/` and records `shared_with` on both the owner chain and the shared notes chain.

## What is out of scope (v0.1)

- Encryption at rest
- OAuth (API key is fixed local secret; OAuth can be added later)
- Direct Syncthing control API
- Mobile clients (documented for future)

## GNote coexistence

GNote data under `~/.local/share/gnote` is **never opened** by this codebase. Import tooling may be added later as an explicit user action.
