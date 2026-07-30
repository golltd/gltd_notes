"""Local session authentication and API key checks."""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from gltd_notes.config import Config, ensure_session_dir
from gltd_notes.utils.hashing import sha256_text


@dataclass
class Session:
    session_id: str
    user_hash: str
    username: str
    created_at: float
    last_active: float
    locked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_hash": self.user_hash,
            "username": self.username,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "locked": self.locked,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Session":
        return cls(
            session_id=d["session_id"],
            user_hash=d["user_hash"],
            username=d["username"],
            created_at=float(d["created_at"]),
            last_active=float(d["last_active"]),
            locked=bool(d.get("locked", False)),
        )


class AuthService:
    def __init__(self, config: Config):
        self.config = config
        self.session_dir = ensure_session_dir()
        self.session_file = self.session_dir / "current_session.json"

    def login(self, username: str, password: str) -> Session:
        user = self.config.verify_password(username, password)
        if not user:
            raise PermissionError("invalid username or password")
        session = Session(
            session_id=secrets.token_urlsafe(24),
            user_hash=user["user_hash"],
            username=user["username"],
            created_at=time.time(),
            last_active=time.time(),
            locked=False,
        )
        self._write_session(session)
        self.config.active_user_hash = user["user_hash"]
        self.config.save()
        return session

    def logout(self) -> None:
        if self.session_file.exists():
            self.session_file.unlink()

    def get_session(self) -> Optional[Session]:
        if not self.session_file.exists():
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                return Session.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def touch(self) -> Optional[Session]:
        s = self.get_session()
        if not s or s.locked:
            return s
        s.last_active = time.time()
        self._write_session(s)
        return s

    def ensure_open_session(self, user_hash: Optional[str] = None) -> Session:
        """Return current unlocked session, or create one for active user (no password)."""
        s = self.get_session()
        if s and not s.locked:
            return s
        uh = user_hash or self.config.active_user_hash
        user = self.config.get_user(uh) if uh else None
        if not user and self.config.list_users():
            user = self.config.list_users()[0]
        if not user:
            raise PermissionError("no user configured")
        session = Session(
            session_id=secrets.token_urlsafe(24),
            user_hash=user["user_hash"],
            username=user["username"],
            created_at=time.time(),
            last_active=time.time(),
            locked=False,
        )
        self._write_session(session)
        self.config.active_user_hash = user["user_hash"]
        self.config.save()
        return session

    def lock(self) -> Session:
        """Lock session. Requires an explicit lock password to have been set."""
        if not self.config.user_has_password():
            raise PermissionError("no lock password set — define one in Settings first")
        s = self.get_session() or self.ensure_open_session()
        s.locked = True
        self._write_session(s)
        return s

    def unlock(self, password: str) -> Session:
        s = self.get_session()
        if not s:
            raise PermissionError("no session")
        if not self.config.user_has_password(s.user_hash):
            # No password — unlock freely and clear lock flag
            s.locked = False
            s.last_active = time.time()
            self._write_session(s)
            return s
        if not self.config.verify_user_password(s.user_hash, password):
            raise PermissionError("invalid password")
        s.locked = False
        s.last_active = time.time()
        self._write_session(s)
        return s

    def require_unlocked(self) -> Session:
        s = self.get_session()
        if not s:
            raise PermissionError("not logged in")
        if s.locked:
            raise PermissionError("session locked")
        return s

    def check_api_key(self, provided: Optional[str]) -> bool:
        if not self.config.data["api"].get("require_auth", True):
            return True
        expected = self.config.api_key
        if not provided or not expected:
            return False
        return secrets.compare_digest(provided.strip(), expected)

    # ── Web session tokens (multi-tab / browser) ─────────────
    def _web_tokens_path(self) -> Path:
        return self.session_dir / "web_tokens.json"

    def _load_web_tokens(self) -> Dict[str, Any]:
        path = self._web_tokens_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_web_tokens(self, data: Dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = self._web_tokens_path()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def create_web_token(
        self,
        username: Optional[str] = None,
        password: str = "",
        ttl_hours: int = 72,
        user_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate desktop lock password and issue a browser session token.

        Accepts username and/or user_hash (from opaque login account id).
        """
        # Always re-read config so password changed in GUI is valid immediately on web
        self.config.reload()
        user = None
        if user_hash:
            user = self.config.get_user(user_hash)
        if not user and username:
            user = self.config.get_user_by_name(username)
        if not user:
            raise PermissionError("usuário ou senha incorretos")

        if user.get("password_set") and user.get("password_hash"):
            expected = sha256_text(f"{user['salt']}:{password or ''}")
            if not secrets.compare_digest(expected, user["password_hash"]):
                raise PermissionError("usuário ou senha incorretos")
        else:
            # no lock password configured — only allow empty password
            if password:
                raise PermissionError("usuário ou senha incorretos")

        token = secrets.token_urlsafe(32)
        now = time.time()
        tokens = self._load_web_tokens()
        tokens = {
            k: v
            for k, v in tokens.items()
            if float(v.get("expires_at", 0)) > now
        }
        tokens[token] = {
            "user_hash": user["user_hash"],
            "username": user["username"],
            "created_at": now,
            "expires_at": now + ttl_hours * 3600,
            "last_active": now,
        }
        self._save_web_tokens(tokens)
        # Update only active_user_hash without rewriting stale password fields:
        # reload again then set active and save
        self.config.reload()
        self.config.active_user_hash = user["user_hash"]
        self.config.save()
        return {
            "token": token,
            "user_hash": user["user_hash"],
            "username": user["username"],
            "expires_at": tokens[token]["expires_at"],
        }

    def check_web_token(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        tokens = self._load_web_tokens()
        info = tokens.get(token.strip())
        if not info:
            return None
        if float(info.get("expires_at", 0)) < time.time():
            tokens.pop(token.strip(), None)
            self._save_web_tokens(tokens)
            return None
        info["last_active"] = time.time()
        tokens[token.strip()] = info
        self._save_web_tokens(tokens)
        return {
            "user_hash": info["user_hash"],
            "username": info["username"],
            "token": token.strip(),
        }

    def revoke_web_token(self, token: Optional[str]) -> None:
        if not token:
            return
        tokens = self._load_web_tokens()
        tokens.pop(token.strip(), None)
        self._save_web_tokens(tokens)

    def authenticate_headers(self, headers) -> Optional[Dict[str, Any]]:
        """Accept X-API-Key, Authorization Bearer (api key or web token), or X-Session-Token."""
        # API key
        key = None
        if hasattr(headers, "get"):
            key = headers.get("X-API-Key") or headers.get("x-api-key")
            sess = headers.get("X-Session-Token") or headers.get("x-session-token")
            auth = headers.get("Authorization") or headers.get("authorization") or ""
        else:
            key = None
            sess = None
            auth = ""
        if key and self.check_api_key(key):
            uh = self.config.active_user_hash
            user = self.config.get_user(uh) if uh else None
            if not user and self.config.list_users():
                user = self.config.list_users()[0]
            return {
                "via": "api_key",
                "user_hash": (user or {}).get("user_hash") or uh,
                "username": (user or {}).get("username") or "",
            }
        token = sess
        if not token and auth.lower().startswith("bearer "):
            token = auth[7:].strip()
            # try as api key first
            if self.check_api_key(token):
                uh = self.config.active_user_hash
                user = self.config.get_user(uh) if uh else None
                if not user and self.config.list_users():
                    user = self.config.list_users()[0]
                return {
                    "via": "api_key",
                    "user_hash": (user or {}).get("user_hash") or uh,
                    "username": (user or {}).get("username") or "",
                }
        web = self.check_web_token(token)
        if web:
            return {
                "via": "session",
                "user_hash": web["user_hash"],
                "username": web["username"],
                "token": web["token"],
            }
        if not self.config.data["api"].get("require_auth", True):
            uh = self.config.active_user_hash
            return {"via": "open", "user_hash": uh, "username": ""}
        return None

    def _write_session(self, session: Session) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.session_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        os.replace(tmp, self.session_file)
        try:
            os.chmod(self.session_file, 0o600)
        except OSError:
            pass
