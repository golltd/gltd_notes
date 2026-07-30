"""CLI entry: python -m gltd_notes [gui|api|web|setup|status]."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_path() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def cmd_setup(_: argparse.Namespace) -> int:
    _ensure_path()
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    from gltd_notes.config import Config
    from gltd_notes.gui.setup_wizard import SetupWizard

    config = Config()
    wizard = SetupWizard(config)
    while True:
        resp = wizard.run()
        if resp != Gtk.ResponseType.OK:
            wizard.destroy()
            return 1
        if wizard.apply():
            wizard.destroy()
            print("Setup complete.")
            print(f"Config: {config.path}")
            print(f"Data:   {config.data_root}")
            print(f"API key stored in config (permissions 600).")
            return 0


def cmd_gui(_: argparse.Namespace) -> int:
    _ensure_path()
    from gltd_notes.gui.main_window import run_gui

    return run_gui()


def cmd_api(args: argparse.Namespace) -> int:
    _ensure_path()
    from gltd_notes.config import Config
    from gltd_notes.api.server import APIServer
    from gltd_notes.services.app_context import AppContext

    config = Config()
    if not config.setup_complete:
        print("Run setup first: gltd-notes setup", file=sys.stderr)
        return 1
    ctx = AppContext(config)
    server = APIServer(ctx, host=args.host, port=args.port)
    server.serve_forever()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    _ensure_path()
    import socket
    import threading
    import time

    from gltd_notes.config import Config
    from gltd_notes.utils.browser import open_url
    from gltd_notes.web.server import WebUIServer
    from gltd_notes.services.app_context import AppContext

    config = Config()
    if not config.setup_complete:
        print("Run setup first: gltd-notes setup", file=sys.stderr)
        return 1
    ctx = AppContext(config)
    server = WebUIServer(ctx, host=args.host, port=args.port)
    browse_host = server.host
    if browse_host in ("0.0.0.0", "::", ""):
        browse_host = "127.0.0.1"
    url = f"http://{browse_host}:{server.port}/"
    open_browser = not getattr(args, "no_browser", False)

    def _wait_port(host: str, port: int, timeout: float = 5.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    return True
            except OSError:
                time.sleep(0.1)
        return False

    if open_browser:
        def _open() -> None:
            if _wait_port(browse_host, int(server.port)):
                ok = open_url(url)
                if ok:
                    print(f"Browser opened: {url}")
                else:
                    print(f"Could not open browser. Open manually: {url}", file=sys.stderr)
            else:
                print(f"Server slow to start. Open manually: {url}", file=sys.stderr)

        threading.Thread(target=_open, daemon=True).start()
    else:
        print(f"Web UI: {url}  (--no-browser)")

    print(f"Login with desktop username/password. Data root: {config.data_root}")
    server.serve_forever()
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    _ensure_path()
    from gltd_notes.config import Config
    from gltd_notes.services.app_context import AppContext

    config = Config()
    print(json.dumps(config.to_public_dict(), indent=2, ensure_ascii=False))
    if config.setup_complete and config.active_user_hash:
        ctx = AppContext(config)
        uh = config.active_user_hash
        report = {name: ctx.user_chain(uh, name).validate() for name in ctx.all_chain_names()}
        print("--- chain validation ---")
        print(json.dumps(report, indent=2))
    return 0


def cmd_auto_markers(args: argparse.Namespace) -> int:
    _ensure_path()
    from gltd_notes.config import Config
    from gltd_notes.services.app_context import AppContext
    from gltd_notes.services.auto_markers import AutoMarkerService

    config = Config()
    if not config.setup_complete:
        print("Run init first.", file=sys.stderr)
        return 1
    ctx = AppContext(config)
    uh = args.user_hash or config.active_user_hash
    svc = AutoMarkerService(ctx)
    report = svc.analyze_and_apply(
        uh,
        only_missing=not args.force,
        dry_run=args.dry_run,
        limit=args.limit or 0,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_import_gnote(args: argparse.Namespace) -> int:
    """Import Tomboy/GNote notes (read-only on source)."""
    _ensure_path()
    from gltd_notes.config import Config
    from gltd_notes.services.app_context import AppContext
    from gltd_notes.services.gnote_import import GNoteImporter

    config = Config()
    if not config.setup_complete or not config.list_users():
        print("Run setup/init first.", file=sys.stderr)
        return 1
    gnote_dir = Path(args.source or "~/.local/share/gnote").expanduser()
    # Resolve symlink for clarity but never write there
    resolved = gnote_dir.resolve()
    print(f"Source (read-only): {gnote_dir} -> {resolved}")
    print(f"Target data root:   {config.data_root}")
    uh = args.user_hash or config.active_user_hash
    if not uh:
        print("No active user.", file=sys.stderr)
        return 1
    ctx = AppContext(config)
    ctx.ensure_data_tree()
    importer = GNoteImporter(ctx, uh)
    result = importer.import_directory(
        gnote_dir,
        include_conflicts=bool(args.include_conflicts),
        skip_templates=not bool(args.include_templates),
    )
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    if result.errors:
        print(f"Completed with {len(result.errors)} errors (first shown above).", file=sys.stderr)
        return 2 if result.imported == 0 else 0
    return 0


def cmd_init_headless(args: argparse.Namespace) -> int:
    """Non-interactive setup for automation / first install."""
    _ensure_path()
    from gltd_notes.config import Config
    from gltd_notes.services.app_context import AppContext

    config = Config()
    if args.data_root:
        config.data_root = args.data_root
    if args.username:
        if not config.get_user_by_name(args.username):
            # Password is optional; lock only if --enable-lock-password
            enable_lock = bool(getattr(args, "enable_lock_password", False))
            if enable_lock and not args.password:
                print("--password required with --enable-lock-password", file=sys.stderr)
                return 1
            config.add_user(
                args.username,
                password=args.password if enable_lock else None,
                display_name=args.display_name or args.username,
                enable_lock_password=enable_lock,
            )
    if args.api_port:
        config.data["api"]["port"] = int(args.api_port)
    if args.api_host:
        config.data["api"]["host"] = args.api_host
    config.setup_complete = bool(config.list_users())
    config.save()
    ctx = AppContext(config)
    ctx.ensure_data_tree()
    for u in config.list_users():
        ctx.user_layout(u["user_hash"]).ensure()
    print(json.dumps({"ok": True, "config": str(config.path), "data_root": str(config.data_root), "users": len(config.list_users()), "api_key": config.api_key}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gltd-notes", description="GLTD Notes — private GNote alternative")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="Start GTK interface (default)")
    sub.add_parser("setup", help="Run setup wizard")
    p_api = sub.add_parser("api", help="Run REST API server only")
    p_api.add_argument("--host", default=None)
    p_api.add_argument("--port", type=int, default=None)
    p_web = sub.add_parser("web", help="Run web UI only (opens browser by default)")
    p_web.add_argument("--host", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the default browser automatically",
    )
    sub.add_parser("status", help="Show config and chain status")
    p_init = sub.add_parser("init", help="Headless init (no GTK)")
    p_init.add_argument("--data-root", default=None, help="Data directory (default: ~/gltd_notes_data)")
    p_init.add_argument("--username", default=None)
    p_init.add_argument("--password", default=None, help="Only used with --enable-lock-password")
    p_init.add_argument("--enable-lock-password", action="store_true",
                        help="Activate session lock password at init (default: off)")
    p_init.add_argument("--display-name", default=None)
    p_init.add_argument("--api-host", default="127.0.0.1")
    p_init.add_argument("--api-port", type=int, default=8765)

    p_imp = sub.add_parser("import-gnote", help="Import notes from GNote/Tomboy directory (read-only source)")
    p_imp.add_argument(
        "--source",
        default=None,
        help="GNote data directory (default: ~/.local/share/gnote)",
    )
    p_imp.add_argument("--user-hash", default=None, help="Target user_hash (default: active user)")
    p_imp.add_argument(
        "--include-conflicts",
        action="store_true",
        help="Also import *.sync-conflict-*.note files",
    )
    p_imp.add_argument(
        "--include-templates",
        action="store_true",
        help="Import system:template notes (skipped by default)",
    )

    p_am = sub.add_parser("auto-markers", help="Generate #markers from note content/categories")
    p_am.add_argument("--user-hash", default=None)
    p_am.add_argument("--force", action="store_true", help="Re-merge markers even if some exist")
    p_am.add_argument("--dry-run", action="store_true")
    p_am.add_argument("--limit", type=int, default=0)

    args = parser.parse_args(argv)
    cmd = args.command or "gui"
    if cmd == "gui":
        return cmd_gui(args)
    if cmd == "setup":
        return cmd_setup(args)
    if cmd == "api":
        return cmd_api(args)
    if cmd == "web":
        return cmd_web(args)
    if cmd == "status":
        return cmd_status(args)
    if cmd == "init":
        return cmd_init_headless(args)
    if cmd == "import-gnote":
        return cmd_import_gnote(args)
    if cmd == "auto-markers":
        return cmd_auto_markers(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
