"""Suggest and apply #markers from note title/body/categories (batch-fast)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from gltd_notes.services.app_context import AppContext
from gltd_notes.services.gnote_import import _FastChainAppender
from gltd_notes.services.notes import NotesService, extract_hashtags, normalize_markers

KEYWORD_MARKERS: List[Tuple[str, str]] = [
    ("linux", "#linux"),
    ("ubuntu", "#linux"),
    ("mint", "#linux"),
    ("debian", "#linux"),
    ("kernel", "#linux"),
    ("bash", "#bash"),
    ("shell", "#shell"),
    ("php", "#php"),
    ("laravel", "#php"),
    ("jquery", "#jquery"),
    ("javascript", "#javascript"),
    ("css", "#css"),
    ("html", "#html"),
    ("bootstrap", "#bootstrap"),
    ("sql", "#sql"),
    ("mysql", "#sql"),
    ("mariadb", "#sql"),
    ("postgres", "#sql"),
    ("python", "#python"),
    ("java", "#java"),
    ("android", "#android"),
    ("wordpress", "#wordpress"),
    ("bitcoin", "#bitcoin"),
    ("crypto", "#crypto"),
    ("miner", "#mineracao"),
    ("wifi", "#rede"),
    ("vpn", "#rede"),
    ("ssh", "#ssh"),
    ("docker", "#docker"),
    ("git", "#git"),
    ("apache", "#servidor"),
    ("nginx", "#servidor"),
    ("servidor", "#servidor"),
    ("backup", "#backup"),
    ("senha", "#seguranca"),
    ("password", "#seguranca"),
    ("ssl", "#seguranca"),
    ("email", "#email"),
    ("smtp", "#email"),
    ("amazon", "#amazon"),
    ("aws", "#aws"),
    ("raspberry", "#raspberry"),
    ("raspberypi", "#raspberry"),
    ("machine learning", "#ml"),
    ("spam", "#spam"),
    ("condominio", "#condominio"),
    ("apartamento", "#apartamento"),
    ("investimento", "#investimento"),
    ("golltd", "#golltd"),
    ("ecoservices", "#ecoservices"),
    ("ecoempresa", "#ecoempresa"),
    ("ecompile", "#ecompile"),
    ("vtiger", "#vtiger"),
    ("dental", "#dentalprev"),
    ("sinfat", "#sinfat"),
    ("fatma", "#sinfat"),
    ("consema", "#consema"),
    ("fort", "#fort"),
    ("protocolo", "#protocolos"),
    ("uselinux", "#linux"),
    ("webservice", "#api"),
    ("webhook", "#api"),
]


def markers_from_text(title: str, body: str, categories: List[str]) -> List[str]:
    blob = f"{title}\n{body}\n{' '.join(categories)}".lower()
    found: Set[str] = set()
    for cat in categories or []:
        c = re.sub(r"[^\wÀ-ÿ]+", "_", cat.strip(), flags=re.UNICODE).strip("_")
        if c:
            found.add("#" + c.lower()[:40])
    for kw, marker in KEYWORD_MARKERS:
        if kw in blob:
            found.add(marker)
    found.update(extract_hashtags(title, body))
    return normalize_markers(sorted(found))


class AutoMarkerService:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.notes = NotesService(ctx)

    def analyze_and_apply(
        self,
        user_hash: str,
        *,
        only_missing: bool = True,
        dry_run: bool = False,
        limit: int = 0,
    ) -> Dict[str, Any]:
        notes = self.notes.list_notes(user_hash, include_shared=False, include_body=False)
        updated = 0
        skipped = 0
        samples: List[Dict[str, Any]] = []

        appender = None
        if not dry_run:
            layout = self.ctx.user_layout(user_hash)
            appender = _FastChainAppender(
                layout.chain_path("notes"),
                machine_id=self.ctx.config.machine_id,
                hostname=self.ctx.config.hostname,
                user_hash=user_hash,
            )

        try:
            for n in notes:
                if limit and updated >= limit:
                    break
                nid = n["entity_id"]
                body = self.notes._read_body_fast(user_hash, nid, "user")
                existing = normalize_markers(n.get("markers") or [])
                if only_missing and existing:
                    skipped += 1
                    continue
                suggested = markers_from_text(
                    n.get("title") or "",
                    body,
                    list(n.get("categories") or []),
                )
                merged = normalize_markers(existing + suggested)
                if set(x.lower() for x in merged) == set(x.lower() for x in existing):
                    skipped += 1
                    continue
                if not dry_run and appender is not None:
                    # merge into full tip-like payload so list view keeps fields
                    payload = dict(n)
                    for drop in (
                        "source",
                        "updated_at",
                        "updated_by_user",
                        "updated_by_host",
                        "updated_by_machine",
                        "last_action",
                        "last_block_hash",
                        "entity_id",
                    ):
                        payload.pop(drop, None)
                    payload["markers"] = merged
                    payload["kind"] = n.get("kind") or "note"
                    payload["title"] = n.get("title")
                    payload["body_hash"] = n.get("body_hash")
                    payload["body_path"] = n.get("body_path")
                    payload["categories"] = n.get("categories") or []
                    payload["tags"] = n.get("tags") or []
                    payload["file_hashes"] = n.get("file_hashes") or []
                    payload["is_shared"] = n.get("is_shared", False)
                    payload["shared_with"] = n.get("shared_with") or []
                    payload["deleted"] = False
                    appender.append("update", nid, payload)
                updated += 1
                if len(samples) < 25:
                    samples.append(
                        {
                            "title": (n.get("title") or "")[:60],
                            "markers": merged,
                            "entity_id": nid[:16],
                        }
                    )
        finally:
            if appender is not None:
                appender.close()

        return {
            "updated": updated,
            "skipped": skipped,
            "total": len(notes),
            "samples": samples,
            "dry_run": dry_run,
        }
