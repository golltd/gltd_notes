"""Minimal stdlib REST API bound to localhost with API-key auth."""

from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from gltd_notes import __version__
from gltd_notes.services.app_context import AppContext
from gltd_notes.services.events import EventsService
from gltd_notes.services.notes import NotesService


JsonDict = Dict[str, Any]


class APIServer:
    def __init__(self, ctx: AppContext, host: Optional[str] = None, port: Optional[int] = None):
        self.ctx = ctx
        self.host = host or ctx.config.data["api"]["host"]
        self.port = int(port or ctx.config.data["api"]["port"])
        self.notes = NotesService(ctx)
        self.events = EventsService(ctx)
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._agent_service: Any = None

    def make_handler(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "GLTDNotesAPI/0.1"

            def log_message(self, fmt: str, *args: Any) -> None:
                # quieter default; still useful on stderr
                print(f"[api] {self.address_string()} {fmt % args}")

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-API-Key, Authorization, X-Session-Token",
                )
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

            def _read_json(self) -> JsonDict:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _auth_ctx(self) -> Optional[Dict[str, Any]]:
                return api.ctx.auth.authenticate_headers(self.headers)

            def _send(self, status: int, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, message: str) -> None:
                self._send(status, {"ok": False, "error": message})

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

            def do_PUT(self) -> None:  # noqa: N802
                self._dispatch("PUT")

            def do_DELETE(self) -> None:  # noqa: N802
                self._dispatch("DELETE")

            def _dispatch(self, method: str) -> None:
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                qs = parse_qs(parsed.query)

                # public endpoints
                if path == "/api/v1/health" and method == "GET":
                    self._send(200, {"ok": True, "service": "gltd_notes", "version": __version__})
                    return
                if path == "/api/v1/login" and method == "POST":
                    try:
                        body = self._read_json()
                        result = api.route_login(body)
                        self._send(200, result)
                    except PermissionError as e:
                        self._error(401, str(e))
                    except Exception as e:  # noqa: BLE001
                        self._error(400, str(e))
                    return
                if path in ("/api/v1/public/users", "/api/v1/public/identities") and method == "GET":
                    self._send(200, api.public_identities())
                    return

                auth = self._auth_ctx()
                if not auth:
                    self._error(401, "unauthorized: login or provide X-API-Key / X-Session-Token")
                    return

                try:
                    result = api.route(
                        method,
                        path,
                        qs,
                        self._read_json if method in ("POST", "PUT") else None,
                        auth=auth,
                    )
                    if result is None:
                        self._error(404, f"not found: {method} {path}")
                        return
                    status, payload = result
                    self._send(status, payload)
                except PermissionError as e:
                    self._error(403, str(e))
                except KeyError as e:
                    self._error(404, str(e))
                except ValueError as e:
                    self._error(400, str(e))
                except json.JSONDecodeError:
                    self._error(400, "invalid JSON body")
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    self._error(500, f"internal error: {e}")

        return Handler

    def _identity_rows(self) -> list[Dict[str, Any]]:
        """Internal ordered account list (includes user_hash, not for public JSON)."""
        from pathlib import Path

        cfg = self.ctx.config
        data_root = Path(cfg.data_root)
        rows: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for u in cfg.list_users():
            uh = u["user_hash"]
            seen.add(uh)
            rows.append(
                {
                    "user_hash": uh,
                    "username": u.get("username"),
                    "has_password": bool(u.get("password_set")),
                }
            )
        user_dir = data_root / "user"
        if user_dir.is_dir():
            for p in sorted(user_dir.iterdir()):
                if not p.is_dir() or len(p.name) < 16 or p.name in seen:
                    continue
                rows.append(
                    {
                        "user_hash": p.name,
                        "username": None,
                        "has_password": False,
                    }
                )
        return rows

    def public_identities(self) -> JsonDict:
        """Login list: username is OK; never path, hash, host or API key."""
        rows = []
        for i, r in enumerate(self._identity_rows()):
            uname = r.get("username") or f"Conta {i + 1}"
            rows.append(
                {
                    "id": f"acct_{i}",
                    "label": uname,  # show username only
                    "username": uname,
                    "has_password": r.get("has_password", False),
                }
            )
        return {"ok": True, "identities": rows}

    def route_login(self, body: JsonDict) -> JsonDict:
        password = body.get("password") if body.get("password") is not None else ""
        password = str(password)
        sel = (
            (body.get("id") or body.get("account_id") or body.get("user_hash") or "")
            .strip()
            or None
        )
        username = (body.get("username") or "").strip() or None
        user_hash = None
        rows = self._identity_rows()
        if sel and sel.startswith("acct_"):
            try:
                idx = int(sel.split("_", 1)[1])
            except ValueError as e:
                raise ValueError("conta inválida") from e
            if idx < 0 or idx >= len(rows):
                raise ValueError("conta inválida")
            user_hash = rows[idx]["user_hash"]
            username = rows[idx].get("username") or username
        elif username:
            # login by username + password (simplest UX)
            u = self.ctx.config.get_user_by_name(username)
            if u:
                user_hash = u["user_hash"]
        elif sel:
            user_hash = sel
            u = self.ctx.config.get_user(user_hash)
            if u:
                username = u.get("username") or username
        if not user_hash and not username:
            raise ValueError("informe o usuário e a senha")
        try:
            info = self.ctx.auth.create_web_token(
                username=username,
                password=password,
                user_hash=user_hash,
            )
        except PermissionError:
            raise PermissionError("usuário ou senha incorretos")
        return {
            "ok": True,
            "token": info["token"],
            "user_hash": info["user_hash"],
            "username": info["username"],
            "expires_at": info["expires_at"],
        }

    def _user_hash(
        self,
        body: Optional[JsonDict],
        qs: Dict[str, list],
        auth: Optional[Dict[str, Any]] = None,
    ) -> str:
        if body and body.get("user_hash"):
            return str(body["user_hash"])
        if qs.get("user_hash"):
            return qs["user_hash"][0]
        if auth and auth.get("user_hash"):
            return str(auth["user_hash"])
        uh = self.ctx.config.active_user_hash
        if not uh:
            raise ValueError("user_hash required (or set active user via setup/login)")
        return uh

    def route(
        self,
        method: str,
        path: str,
        qs: Dict[str, list],
        body_reader: Optional[Callable[[], JsonDict]],
        auth: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[int, Any]]:
        body: JsonDict = body_reader() if body_reader else {}

        if path == "/api/v1/logout" and method == "POST":
            tok = (auth or {}).get("token")
            self.ctx.auth.revoke_web_token(tok)
            return 200, {"ok": True}

        if path == "/api/v1/me" and method == "GET":
            # Keep response minimal for web clients (no paths/hostnames)
            return 200, {
                "ok": True,
                "user_hash": (auth or {}).get("user_hash"),
                "username": (auth or {}).get("username"),
                "via": (auth or {}).get("via"),
            }

        if path == "/api/v1/config" and method == "GET":
            pub = self.ctx.config.to_public_dict()
            # Never leak secrets/paths to browser session clients
            if (auth or {}).get("via") == "api_key":
                pub["api_key"] = self.ctx.config.api_key
            else:
                pub.pop("api_key", None)
                if isinstance(pub.get("api"), dict):
                    pub["api"] = {
                        k: v
                        for k, v in pub["api"].items()
                        if k not in ("api_key",)
                    }
                # strip absolute paths from web clients
                pub.pop("data_root", None)
                pub.pop("install_root", None)
                pub.pop("machine_id", None)
            return 200, {"ok": True, "config": pub}

        if path == "/api/v1/users" and method == "GET":
            users = [
                {
                    "user_hash": u["user_hash"],
                    "username": u["username"],
                    "display_name": u.get("display_name"),
                }
                for u in self.ctx.config.list_users()
            ]
            return 200, {"ok": True, "users": users}

        if path == "/api/v1/notes" and method == "GET":
            uh = self._user_hash(None, qs, auth)
            notes = self.notes.list_notes(
                uh,
                query=(qs.get("q") or [None])[0],
                category=(qs.get("category") or [None])[0],
                include_body=(qs.get("include_body") or ["0"])[0] in ("1", "true", "yes"),
            )
            return 200, {"ok": True, "notes": notes, "user_hash": uh}

        if path == "/api/v1/notes" and method == "POST":
            uh = self._user_hash(body, qs, auth)
            note = self.notes.create_note(
                uh,
                title=body.get("title") or "Untitled",
                body=body.get("body") or "",
                categories=body.get("categories"),
                tags=body.get("tags"),
                kind=body.get("kind") or "note",
                extra_payload={"markers": body.get("markers")} if body.get("markers") is not None else None,
            )
            return 201, {"ok": True, "note": note}

        if path.startswith("/api/v1/notes/") and method == "GET":
            rest = path[len("/api/v1/notes/") :]
            parts = rest.split("/")
            note_id = parts[0]
            uh = self._user_hash(None, qs, auth)
            if len(parts) == 1:
                return 200, {"ok": True, "note": self.notes.get_note(uh, note_id, include_body=True)}
            if len(parts) == 2 and parts[1] == "history":
                return 200, {
                    "ok": True,
                    "history": self.notes.history_grouped(uh, note_id),
                }
            return None

        if path.startswith("/api/v1/notes/") and method == "PUT":
            note_id = path[len("/api/v1/notes/") :].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            extra = {}
            if body.get("markers") is not None:
                extra["markers"] = body.get("markers")
            if body.get("agent") is not None:
                extra["agent"] = body["agent"]
            if body.get("agent_status") is not None:
                extra["agent_status"] = body["agent_status"]
            note = self.notes.update_note(
                uh,
                note_id,
                title=body.get("title"),
                body=body.get("body"),
                categories=body.get("categories"),
                tags=body.get("tags"),
                kind=body.get("kind"),
                extra_payload=extra or None,
                force_history=bool(body.get("force_history")),
            )
            return 200, {"ok": True, "note": note}

        if path.startswith("/api/v1/notes/") and method == "DELETE":
            note_id = path[len("/api/v1/notes/") :].split("/")[0]
            uh = self._user_hash(None, qs, auth)
            return 200, {"ok": True, **self.notes.delete_note(uh, note_id)}

        if path.endswith("/revert") and method == "POST" and path.startswith("/api/v1/notes/"):
            note_id = path[len("/api/v1/notes/") :].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            note = self.notes.revert(uh, note_id, body.get("block_hash") or "")
            return 200, {"ok": True, "note": note}

        if path.endswith("/share") and method == "POST" and path.startswith("/api/v1/notes/"):
            note_id = path[len("/api/v1/notes/") :].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            targets = body.get("shared_with") or body.get("user_hashes") or []
            note = self.notes.share_note(uh, note_id, list(targets))
            return 200, {"ok": True, "note": note}

        if path.endswith("/attach") and method == "POST" and path.startswith("/api/v1/notes/"):
            note_id = path[len("/api/v1/notes/") :].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            import base64

            if body.get("path"):
                result = self.notes.attach_file(uh, note_id, body["path"], body.get("original_name"))
            elif body.get("content_base64"):
                data = base64.b64decode(body["content_base64"])
                result = self.notes.attach_file(uh, note_id, data, body.get("original_name"))
            else:
                raise ValueError("provide path or content_base64")
            return 200, {"ok": True, "attachment": result}

        if path == "/api/v1/events" and method == "GET":
            uh = self._user_hash(None, qs, auth)
            events = self.events.list_events(
                uh,
                include_completed=(qs.get("include_completed") or ["0"])[0] in ("1", "true"),
            )
            return 200, {"ok": True, "events": events}

        if path == "/api/v1/events" and method == "POST":
            uh = self._user_hash(body, qs, auth)
            event = self.events.create_event(
                uh,
                title=body.get("title") or "Event",
                body=body.get("body") or "",
                due_at=body.get("due_at"),
                remind_at=body.get("remind_at"),
                categories=body.get("categories"),
            )
            return 201, {"ok": True, "event": event}

        if path.startswith("/api/v1/events/") and method == "GET":
            event_id = path[len("/api/v1/events/") :].split("/")[0]
            uh = self._user_hash(None, qs, auth)
            return 200, {"ok": True, "event": self.events.get_event(uh, event_id)}

        if path.startswith("/api/v1/events/") and method == "PUT":
            event_id = path[len("/api/v1/events/") :].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            event = self.events.update_event(uh, event_id, **body)
            return 200, {"ok": True, "event": event}

        if path.startswith("/api/v1/events/") and method == "DELETE":
            event_id = path[len("/api/v1/events/") :].split("/")[0]
            uh = self._user_hash(None, qs, auth)
            return 200, {"ok": True, **self.events.delete_event(uh, event_id)}

        if path == "/api/v1/dashboard" and method == "GET":
            uh = self._user_hash(None, qs, auth)
            from gltd_notes.services.tasks import TasksService

            tasks = TasksService(self.ctx).list_open_tasks_summary(uh, limit=20)
            events = self.events.list_events(uh, include_completed=False)[:15]
            return 200, {"ok": True, "open_tasks": tasks, "events": events}

        if path == "/api/v1/tasklists" and method == "POST":
            uh = self._user_hash(body, qs, auth)
            from gltd_notes.services.tasks import TasksService

            note = TasksService(self.ctx).create_tasklist(uh, title=body.get("title") or "Task list")
            return 201, {"ok": True, "note": note}

        if path == "/api/v1/agent-tasks" and method == "POST":
            uh = self._user_hash(body, qs, auth)
            from gltd_notes.services.agent_tasks import AgentTasksService

            note = AgentTasksService(self.ctx).create(
                uh,
                title=body.get("title") or "Agent task",
                description=body.get("description") or "",
                agent=body.get("agent") or "grok",
            )
            return 201, {"ok": True, "note": note}

        # ── Agent tasks extended ──
        if path.startswith("/api/v1/agent-tasks/") and method == "GET":
            note_id = path[len("/api/v1/agent-tasks/"):]
            if "/" not in note_id:
                uh = self._user_hash(None, qs, auth)
                from gltd_notes.services.agent_tasks import AgentTasksService

                svc = AgentTasksService(self.ctx)
                data = svc.get_data(uh, note_id)
                note = data.pop("_note", {})
                data["title"] = note.get("title") or ""
                data["kind"] = note.get("kind") or "agent_task"
                return 200, {"ok": True, "task": data}

        if path.endswith("/children") and path.startswith("/api/v1/agent-tasks/") and method == "GET":
            note_id = path[len("/api/v1/agent-tasks/"):].split("/")[0]
            uh = self._user_hash(None, qs, auth)
            from gltd_notes.services.agent_tasks import AgentTasksService

            svc = AgentTasksService(self.ctx)
            data = svc.get_data(uh, note_id)
            child_ids = (data.get("related_ids") or [])
            children = []
            for cid in child_ids:
                try:
                    cdata = svc.get_data(uh, cid)
                    cn = cdata.pop("_note", {})
                    children.append({
                        "entity_id": cid,
                        "title": cn.get("title") or "",
                        "agent": cdata.get("agent") or "grok",
                        "status": cdata.get("status") or "pending",
                    })
                except KeyError:
                    pass
            return 200, {"ok": True, "children": children}

        if path.endswith("/add-related") and path.startswith("/api/v1/agent-tasks/") and method == "POST":
            note_id = path[len("/api/v1/agent-tasks/"):].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            from gltd_notes.services.agent_tasks import AgentTasksService

            child = AgentTasksService(self.ctx).add_related(
                uh, note_id,
                title=body.get("title") or "Subtarefa",
                description=body.get("description") or "",
                agent=body.get("agent"),
            )
            return 201, {"ok": True, "note": child}

        if path.endswith("/run") and path.startswith("/api/v1/agent-tasks/") and method == "POST":
            note_id = path[len("/api/v1/agent-tasks/"):].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            from gltd_notes.services.agent_tasks import AgentTasksService

            svc = AgentTasksService(self.ctx)
            api._agent_service = svc
            result = svc.run_agent(uh, note_id, timeout=600)
            api._agent_service = None
            return 200, {"ok": result["ok"], "data": result.get("data")}

        if path.endswith("/cancel") and path.startswith("/api/v1/agent-tasks/") and method == "POST":
            note_id = path[len("/api/v1/agent-tasks/"):].split("/")[0]
            uh = self._user_hash(body, qs, auth)
            svc = getattr(api, "_agent_service", None)
            if svc:
                svc.cancel()
            return 200, {"ok": True}

        if path == "/api/v1/categories" and method == "GET":
            uh = self._user_hash(None, qs, auth)
            return 200, {"ok": True, "categories": self.notes.list_categories(uh)}

        if path == "/api/v1/chains/validate" and method == "GET":
            uh = self._user_hash(None, qs, auth)
            report = {}
            for name in self.ctx.all_chain_names():
                report[name] = self.ctx.user_chain(uh, name).validate()
            report["shared_notes"] = self.ctx.shared_chain("notes").validate()
            return 200, {"ok": True, "report": report}

        return None

    def serve_forever(self) -> None:
        self.ctx.ensure_data_tree()
        handler = self.make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        print(f"GLTD Notes API listening on http://{self.host}:{self.port}")
        print("Auth: send header X-API-Key: <key from ~/.config/gltd_notes/config.json>")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nAPI stopped")
        finally:
            self._httpd.server_close()

    def start_background(self) -> ThreadingHTTPServer:
        import threading

        self.ctx.ensure_data_tree()
        handler = self.make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        t = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t.start()
        return self._httpd
