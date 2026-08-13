"""Central application context wiring config, chains and stores."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from gltd_notes.auth import AuthService
from gltd_notes.blockchain import Blockchain
from gltd_notes.config import Config
from gltd_notes.storage import FileStore
from gltd_notes.utils.paths import (
    CHAIN_NAMES,
    DataLayout,
    shared_root,
    user_root,
)


class AppContext:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.auth = AuthService(self.config)
        self._user_chains: Dict[str, Dict[str, Blockchain]] = {}
        self._user_stores: Dict[str, FileStore] = {}
        self._shared_chains: Optional[Dict[str, Blockchain]] = None
        self._shared_store: Optional[FileStore] = None

    def ensure_data_tree(self) -> None:
        root = self.config.data_root
        root.mkdir(parents=True, exist_ok=True)
        (root / "user").mkdir(exist_ok=True)
        shared = DataLayout(shared_root(root))
        shared.ensure()
        for u in self.config.list_users():
            self.user_layout(u["user_hash"]).ensure()

    def user_layout(self, user_hash: str) -> DataLayout:
        layout = DataLayout(user_root(self.config.data_root, user_hash))
        layout.ensure()
        return layout

    def shared_layout(self) -> DataLayout:
        layout = DataLayout(shared_root(self.config.data_root))
        layout.ensure()
        return layout

    def user_store(self, user_hash: str) -> FileStore:
        if user_hash not in self._user_stores:
            self._user_stores[user_hash] = FileStore(self.user_layout(user_hash))
        return self._user_stores[user_hash]

    def shared_store(self) -> FileStore:
        if self._shared_store is None:
            self._shared_store = FileStore(self.shared_layout())
        return self._shared_store

    def user_chain(self, user_hash: str, name: str) -> Blockchain:
        if user_hash not in self._user_chains:
            self._user_chains[user_hash] = {}
        chains = self._user_chains[user_hash]
        if name not in chains:
            layout = self.user_layout(user_hash)
            chains[name] = Blockchain(
                path=layout.chain_path(name),
                machine_id=self.config.machine_id,
                hostname=self.config.hostname,
                default_user_hash=user_hash,
            )
        return chains[name]

    def shared_chain(self, name: str) -> Blockchain:
        if self._shared_chains is None:
            self._shared_chains = {}
        if name not in self._shared_chains:
            layout = self.shared_layout()
            self._shared_chains[name] = Blockchain(
                path=layout.chain_path(name),
                machine_id=self.config.machine_id,
                hostname=self.config.hostname,
                default_user_hash=self.config.active_user_hash or "",
            )
        return self._shared_chains[name]

    def all_chain_names(self) -> tuple:
        return CHAIN_NAMES

    def list_local_user_hashes(self) -> list:
        """List all user-hash directories present under data_root/user/.

        Includes the current user plus any other machine's folders synced
        via Syncthing (same-network sharing).
        """
        user_dir = self.config.data_root / "user"
        hashes = []
        try:
            for child in user_dir.iterdir():
                if child.is_dir() and len(child.name) >= 12:
                    hashes.append(child.name)
        except OSError:
            pass
        return hashes
