"""Application configuration (setup paths, API key, users)."""

from __future__ import annotations

import json
import os
import secrets
import socket
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from gltd_notes.utils.hashing import new_entity_id, sha256_text
from gltd_notes.utils.paths import (
    CONFIG_DIR,
    DEFAULT_DATA_ROOT,
    DEFAULT_INSTALL_ROOT,
    SESSION_DIR,
)

CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8765
DEFAULT_WEB_PORT = 8766


def _default_config() -> Dict[str, Any]:
    return {
        "version": 1,
        "setup_complete": False,
        "data_root": str(DEFAULT_DATA_ROOT),
        "install_root": str(DEFAULT_INSTALL_ROOT),
        "hostname": socket.gethostname(),
        "api": {
            "enabled": True,
            "host": DEFAULT_API_HOST,
            "port": DEFAULT_API_PORT,
            "api_key": secrets.token_urlsafe(32),
            "require_auth": True,
        },
        "web": {
            "enabled": True,
            "host": DEFAULT_API_HOST,  # 127.0.0.1 — localhost only
            "port": DEFAULT_WEB_PORT,
            "allow_remote": False,
        },
        "gui": {
            "theme": "default",
            "lock_on_idle_minutes": 0,
            "start_minimized_to_tray": False,
            "close_to_tray": True,
            "language": "auto",
            "autosave_ms": 4000,
            # history: only create a chain version every N seconds or on large edits
            "history_checkpoint_seconds": 300,
            "history_large_change_chars": 120,
        },
        "notifications": {
            "enabled": True,
            "check_interval_seconds": 60,
        },
        "users": [],
        "active_user_hash": None,
        "machine_id": new_entity_id("machine"),
    }


class Config:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else CONFIG_FILE
        self._data: Dict[str, Any] = _default_config()
        if self.path.exists():
            self.load()

    @property
    def data(self) -> Dict[str, Any]:
        return self._data

    def load(self) -> None:
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        base = _default_config()
        self._deep_merge(base, loaded)
        self._data = base

    def reload(self) -> None:
        """Re-read config from disk (shared desktop/web password stays in sync)."""
        if self.path.exists():
            self.load()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                Config._deep_merge(base[k], v)
            else:
                base[k] = v

    @property
    def data_root(self) -> Path:
        return Path(self._data["data_root"])

    @data_root.setter
    def data_root(self, value: Path | str) -> None:
        self._data["data_root"] = str(value)

    @property
    def setup_complete(self) -> bool:
        return bool(self._data.get("setup_complete"))

    @setup_complete.setter
    def setup_complete(self, value: bool) -> None:
        self._data["setup_complete"] = bool(value)

    @property
    def api_key(self) -> str:
        return self._data["api"]["api_key"]

    def regenerate_api_key(self) -> str:
        key = secrets.token_urlsafe(32)
        self._data["api"]["api_key"] = key
        return key

    @property
    def hostname(self) -> str:
        return self._data.get("hostname") or socket.gethostname()

    @property
    def machine_id(self) -> str:
        return self._data["machine_id"]

    @property
    def active_user_hash(self) -> Optional[str]:
        return self._data.get("active_user_hash")

    @active_user_hash.setter
    def active_user_hash(self, value: Optional[str]) -> None:
        self._data["active_user_hash"] = value

    def list_users(self) -> List[Dict[str, Any]]:
        return list(self._data.get("users") or [])

    def get_user(self, user_hash: str) -> Optional[Dict[str, Any]]:
        for u in self.list_users():
            if u.get("user_hash") == user_hash:
                return u
        return None

    def get_user_by_name(self, username: str) -> Optional[Dict[str, Any]]:
        for u in self.list_users():
            if u.get("username") == username:
                return u
        return None

    def get_user_fresh(self, user_hash: Optional[str] = None, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Reload from disk then resolve user (desktop password changes apply immediately)."""
        self.reload()
        if user_hash:
            return self.get_user(user_hash)
        if username:
            return self.get_user_by_name(username)
        return None

    def add_user(
        self,
        username: str,
        password: Optional[str] = None,
        display_name: Optional[str] = None,
        *,
        enable_lock_password: bool = False,
    ) -> Dict[str, Any]:
        """Create a user.

        Lock password is only active when enable_lock_password=True and a
        non-empty password is provided. Headless init can create users without
        enabling session lock.
        """
        if self.get_user_by_name(username):
            raise ValueError(f"user already exists: {username}")
        salt = secrets.token_hex(16)
        password_set = bool(enable_lock_password and password)
        password_hash = sha256_text(f"{salt}:{password}") if password_set else ""
        user_hash = new_entity_id("user", username)
        user = {
            "user_hash": user_hash,
            "username": username,
            "display_name": display_name or username,
            "salt": salt,
            "password_hash": password_hash,
            "password_set": password_set,
            "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "roles": ["owner"],
        }
        self._data.setdefault("users", []).append(user)
        if not self._data.get("active_user_hash"):
            self._data["active_user_hash"] = user_hash
        return user

    def user_has_password(self, user_hash: Optional[str] = None) -> bool:
        """True only if the user explicitly set a session lock password."""
        uh = user_hash or self.active_user_hash
        if not uh:
            return False
        user = self.get_user(uh)
        if not user:
            return False
        # Migrate legacy users: password_set missing but hash present from init
        # — treat as NOT set until user confirms in Settings (avoids mystery lock).
        if "password_set" not in user:
            user["password_set"] = False
            self.save()
            return False
        return bool(user.get("password_set")) and bool(user.get("password_hash"))

    def set_user_password(self, user_hash: str, new_password: str, current_password: Optional[str] = None) -> None:
        """Set or change lock password. First set does not require current_password."""
        self.reload()
        user = self.get_user(user_hash)
        if not user:
            raise KeyError("user not found")
        if not new_password or len(new_password) < 4:
            raise ValueError("password must be at least 4 characters")
        if user.get("password_set") and user.get("password_hash"):
            if current_password is None:
                raise PermissionError("current password required")
            expected = sha256_text(f"{user['salt']}:{current_password}")
            if not secrets.compare_digest(expected, user["password_hash"]):
                raise PermissionError("current password is incorrect")
        salt = secrets.token_hex(16)
        user["salt"] = salt
        user["password_hash"] = sha256_text(f"{salt}:{new_password}")
        user["password_set"] = True
        self.save()

    def clear_user_password(self, user_hash: str, current_password: str) -> None:
        """Remove lock password (disables session lock)."""
        self.reload()
        user = self.get_user(user_hash)
        if not user:
            raise KeyError("user not found")
        if not user.get("password_set"):
            user["password_set"] = False
            user["password_hash"] = ""
            self.save()
            return
        expected = sha256_text(f"{user['salt']}:{current_password}")
        if not secrets.compare_digest(expected, user["password_hash"]):
            raise PermissionError("current password is incorrect")
        user["password_hash"] = ""
        user["password_set"] = False
        self.save()

    def verify_password(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        self.reload()  # always use latest password from disk (GUI ↔ web)
        user = self.get_user_by_name(username)
        if not user or not user.get("password_set") or not user.get("password_hash"):
            return None
        expected = sha256_text(f"{user['salt']}:{password}")
        if secrets.compare_digest(expected, user["password_hash"]):
            return user
        return None

    def verify_user_password(self, user_hash: str, password: str) -> bool:
        self.reload()  # always use latest password from disk (GUI ↔ web)
        user = self.get_user(user_hash)
        if not user or not user.get("password_set") or not user.get("password_hash"):
            return False
        expected = sha256_text(f"{user['salt']}:{password}")
        return secrets.compare_digest(expected, user["password_hash"])

    def migrate_password_flags(self) -> None:
        """Ensure legacy users have password_set (defaults to False)."""
        changed = False
        for u in self._data.get("users") or []:
            if "password_set" not in u:
                # Do not treat init-time hashes as intentional lock passwords
                u["password_set"] = False
                changed = True
        if changed:
            self.save()

    def to_public_dict(self) -> Dict[str, Any]:
        d = deepcopy(self._data)
        d["api"] = dict(d.get("api") or {})
        # never expose password hashes in public dumps used by UI
        users = []
        for u in d.get("users") or []:
            users.append(
                {
                    "user_hash": u.get("user_hash"),
                    "username": u.get("username"),
                    "display_name": u.get("display_name"),
                    "created_at": u.get("created_at"),
                    "roles": u.get("roles"),
                }
            )
        d["users"] = users
        # keep api_key for owner config UI only when called explicitly
        return d


def ensure_session_dir() -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR
