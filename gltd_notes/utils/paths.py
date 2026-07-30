"""Path layout for user and shared data trees."""

from __future__ import annotations

from pathlib import Path

DEFAULT_DATA_ROOT = Path.home() / "gltd_notes_data"
DEFAULT_INSTALL_ROOT = Path("/var/PROGRAMAS/gltd_notes")
CONFIG_DIR = Path.home() / ".config" / "gltd_notes"
SESSION_DIR = Path.home() / ".local" / "share" / "gltd_notes" / "session"

NOTE_EXT = ".gltdnote"
CHAIN_SUFFIX = ".chain.jsonl"

CHAIN_NAMES = (
    "notes",
    "categories",
    "files",
    "arquivos_nota",
    "eventos",
)


class DataLayout:
    """Resolves paths under a root (user or shared)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.notas = self.root / "notas"
        self.arquivos = self.root / "arquivos"
        self.databases = self.root / "databases"
        self.eventos = self.root / "eventos"

    def ensure(self) -> None:
        for d in (self.notas, self.arquivos, self.databases, self.eventos, self.working):
            d.mkdir(parents=True, exist_ok=True)
        for name in CHAIN_NAMES:
            path = self.chain_path(name)
            if not path.exists():
                path.touch()

    @property
    def working(self) -> Path:
        """Per-note tip/draft metadata (not full history)."""
        return self.databases / "working"

    def chain_path(self, name: str) -> Path:
        if name not in CHAIN_NAMES:
            raise ValueError(f"unknown chain: {name}")
        return self.databases / f"{name}{CHAIN_SUFFIX}"

    def note_path(self, note_id: str) -> Path:
        return self.notas / f"{note_id}{NOTE_EXT}"

    def working_path(self, note_id: str) -> Path:
        return self.working / f"{note_id}.json"

    def file_path(self, content_hash: str) -> Path:
        return self.arquivos / content_hash[:3] / content_hash

    def event_note_path(self, event_id: str) -> Path:
        return self.eventos / f"{event_id}{NOTE_EXT}"


def user_root(data_root: Path, user_hash: str) -> Path:
    return Path(data_root) / "user" / user_hash


def shared_root(data_root: Path) -> Path:
    return Path(data_root) / "shared"
