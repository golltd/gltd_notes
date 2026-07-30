# REST API reference

**Base URL:** `http://127.0.0.1:8765`  
**Auth:** header `X-API-Key: <key>` or `Authorization: Bearer <key>`  
**Content-Type:** `application/json` for bodies  

Unless noted, all endpoints require auth.

Query/body field `user_hash` selects the logical user. If omitted, `active_user_hash` from config is used.

---

## GET `/api/v1/health`

No auth. Returns service liveness.

```json
{ "ok": true, "service": "gltd_notes", "version": "0.1.0" }
```

## GET `/api/v1/config`

Returns sanitized config and the API key (localhost authenticated clients only).

## GET `/api/v1/users`

Lists local users (`user_hash`, `username`, `display_name`).

## Notes

### GET `/api/v1/notes`

Query: `q`, `category`, `include_body=1`, `user_hash`

### POST `/api/v1/notes`

```json
{
  "title": "Shopping",
  "body": "milk\nbread",
  "categories": ["personal"],
  "tags": ["todo"],
  "user_hash": "optional"
}
```

### GET `/api/v1/notes/{id}`

Full note including `body`, history metadata, attachments list (`file_hashes`).

### PUT `/api/v1/notes/{id}`

Partial update: any of `title`, `body`, `categories`, `tags`.

### DELETE `/api/v1/notes/{id}`

Soft-delete via chain action `delete` (body file retained for recovery/history).

### GET `/api/v1/notes/{id}/history`

Array of chain blocks for the note (oldest first).

### POST `/api/v1/notes/{id}/revert`

```json
{ "block_hash": "<hash from history>" }
```

Restores title/body/categories/tags from that block’s `payload` (`body_snapshot`).

### POST `/api/v1/notes/{id}/share`

```json
{ "shared_with": ["<user_hash>", "..."] }
```

### POST `/api/v1/notes/{id}/attach`

```json
{ "path": "/absolute/or/relative/file.pdf", "original_name": "file.pdf" }
```

or

```json
{ "content_base64": "...", "original_name": "file.bin" }
```

## Events

### GET `/api/v1/events?include_completed=0`

### POST `/api/v1/events`

```json
{
  "title": "Dentist",
  "body": "Bring insurance card",
  "due_at": "2026-08-01T14:00:00Z",
  "remind_at": "2026-08-01T13:30:00Z"
}
```

### GET/PUT/DELETE `/api/v1/events/{id}`

PUT accepts `title`, `body`, `due_at`, `remind_at`, `completed`, `notified`, `categories`.

## Categories

### GET `/api/v1/categories`

## Integrity

### GET `/api/v1/chains/validate`

Validates block hashes for all user chains and shared notes chain.

## Error shape

```json
{ "ok": false, "error": "message" }
```

Status codes: `400` validation, `401` auth, `403` permission, `404` missing, `500` internal.
