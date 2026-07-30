# Security model (v0.1)

## Trust assumptions

- Single-user or small trusted multi-user on machines you control.
- Data directory may be synced with Syncthing among your own devices.
- API binds to **localhost** by default; do not expose without additional controls.

## Authentication

| Mechanism | Purpose |
|-----------|---------|
| API key (`api.api_key`) | REST + web proxy |
| Username / salted SHA-256 password | Local users, session unlock |
| Session file `0600` | Optional lock state |

Passwords are **not** stored plaintext. v0.1 uses `SHA-256(salt:password)` — adequate for local threat model, not for public internet (upgrade to argon2/bcrypt before any remote exposure).

## What is not encrypted

- Note bodies, attachments, chain files: **plaintext on disk**.
- Syncthing folder inherits that; enable Syncthing/FS encryption separately if needed.

## Integrity

- Each block carries `block_hash`; `/api/v1/chains/validate` reports mismatches.
- Corrupt lines are skipped on load (availability over fail-closed).
- Soft deletes leave bodies on disk for recovery.

## GNote isolation

Code paths never open `~/.local/share/gnote`.

## Hardening roadmap

1. Argon2id password hashing  
2. Optional at-rest encryption (per-user key)  
3. OAuth2 device flow for remote clients  
4. TLS reverse proxy docs  
5. Rate limiting on API  
