"""Full-featured localhost web UI — same data as desktop GUI, password login only."""

from __future__ import annotations

import ipaddress
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from gltd_notes import __version__
from gltd_notes.services.app_context import AppContext

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def _is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return addr in ("127.0.0.1", "::1", "localhost")


class WebUIServer:
    def __init__(self, ctx: AppContext, host: Optional[str] = None, port: Optional[int] = None):
        self.ctx = ctx
        # Default: bind localhost only (ignore accidental 0.0.0.0 in old configs
        # unless explicitly allowed via web.allow_remote)
        cfg_web = ctx.config.data.get("web") or {}
        raw_host = host if host is not None else cfg_web.get("host") or "127.0.0.1"
        allow_remote = bool(cfg_web.get("allow_remote", False))
        if not allow_remote and raw_host in ("0.0.0.0", "::", ""):
            raw_host = "127.0.0.1"
        self.host = raw_host
        self.port = int(port or cfg_web.get("port") or 8766)
        self.allow_remote = allow_remote
        from gltd_notes.api.server import APIServer

        self.api = APIServer(ctx)

    def _index_html(self) -> bytes:
        if INDEX_FILE.exists():
            return INDEX_FILE.read_bytes()
        return b"<h1>GLTD Notes Web</h1><p>index.html missing</p>"

    def make_handler(self):
        web = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                print(f"[web] {self.address_string()} {fmt % args}")

            def _client_allowed(self) -> bool:
                if web.allow_remote:
                    return True
                host = self.client_address[0] if self.client_address else ""
                # strip IPv4-mapped IPv6 ::ffff:127.0.0.1
                if host.startswith("::ffff:"):
                    host = host[7:]
                return _is_loopback(host)

            def _reject_remote(self) -> bool:
                if self._client_allowed():
                    return False
                body = b"Forbidden: GLTD Notes Web is localhost-only by default.\n"
                self.send_response(403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True

            def do_GET(self):  # noqa: N802
                if self._reject_remote():
                    return
                parsed = urlparse(self.path)
                path = parsed.path
                if path in ("/", "/index.html"):
                    body = web._index_html()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    # bust caches so login JS updates are always fresh
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path.startswith("/static/"):
                    rel = path[len("/static/") :]
                    fpath = (STATIC_DIR / rel).resolve()
                    if not str(fpath).startswith(str(STATIC_DIR.resolve())) or not fpath.is_file():
                        self.send_error(404)
                        return
                    data = fpath.read_bytes()
                    ctype = "application/octet-stream"
                    if fpath.suffix == ".css":
                        ctype = "text/css; charset=utf-8"
                    elif fpath.suffix == ".js":
                        ctype = "application/javascript; charset=utf-8"
                    elif fpath.suffix == ".html":
                        ctype = "text/html; charset=utf-8"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path.startswith("/proxy/"):
                    self._proxy(parsed)
                    return
                self.send_error(404)

            def do_POST(self):  # noqa: N802
                if self._reject_remote():
                    return
                parsed = urlparse(self.path)
                if parsed.path.startswith("/proxy/"):
                    self._proxy(parsed)
                    return
                self.send_error(404)

            def do_PUT(self):  # noqa: N802
                self.do_POST()

            def do_DELETE(self):  # noqa: N802
                self.do_POST()

            def do_OPTIONS(self):  # noqa: N802
                if self._reject_remote():
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header(
                    "Access-Control-Allow-Headers",
                    "Content-Type, X-API-Key, Authorization, X-Session-Token",
                )
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
                self.end_headers()

            def _proxy(self, parsed):
                api_path = parsed.path[len("/proxy") :]
                qs = parse_qs(parsed.query)
                method = self.command
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body: Dict[str, Any] = {}
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        self._json(400, {"ok": False, "error": "invalid JSON"})
                        return

                path = api_path.rstrip("/") or "/"
                # Public
                if path == "/api/v1/health" and method == "GET":
                    self._json(200, {"ok": True, "service": "gltd_notes", "version": __version__})
                    return
                if path == "/api/v1/login" and method == "POST":
                    try:
                        self._json(200, web.api.route_login(body))
                    except PermissionError as e:
                        self._json(401, {"ok": False, "error": str(e)})
                    except Exception as e:  # noqa: BLE001
                        self._json(400, {"ok": False, "error": str(e)})
                    return
                if path in ("/api/v1/public/users", "/api/v1/public/identities") and method == "GET":
                    self._json(200, web.api.public_identities())
                    return

                auth = web.ctx.auth.authenticate_headers(self.headers)
                if not auth:
                    self._json(
                        401,
                        {"ok": False, "error": "unauthorized — faça login com usuário e senha do desktop"},
                    )
                    return

                def reader():
                    return body

                try:
                    result = web.api.route(
                        method,
                        path,
                        qs,
                        reader if method in ("POST", "PUT") else None,
                        auth=auth,
                    )
                    if result is None:
                        self._json(404, {"ok": False, "error": "not found"})
                        return
                    status, payload = result
                    self._json(status, payload)
                except PermissionError as e:
                    self._json(403, {"ok": False, "error": str(e)})
                except KeyError as e:
                    self._json(404, {"ok": False, "error": str(e)})
                except ValueError as e:
                    self._json(400, {"ok": False, "error": str(e)})
                except Exception as e:  # noqa: BLE001
                    self._json(500, {"ok": False, "error": str(e)})

            def _json(self, status, payload):
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

        return Handler

    def serve_forever(self) -> None:
        self.ctx.ensure_data_tree()
        # Refuse non-loopback bind unless allow_remote
        if not self.allow_remote and not _is_loopback(self.host.replace("localhost", "127.0.0.1")):
            if self.host not in ("127.0.0.1", "::1", "localhost"):
                print(f"[web] Forcing bind to 127.0.0.1 (was {self.host}; set web.allow_remote=true to override)")
                self.host = "127.0.0.1"
        httpd = ThreadingHTTPServer((self.host, self.port), self.make_handler())
        print(f"GLTD Notes Web UI on http://{self.host}:{self.port}")
        print("Login: conta + senha do desktop (sem API key). Bind: localhost only.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nWeb UI stopped")
        finally:
            httpd.server_close()
