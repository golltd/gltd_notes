"""Syncthing embedded/external service manager for GLTD Notes."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen

from gltd_notes.config import Config
from gltd_notes.utils.paths import DEFAULT_INSTALL_ROOT

_log = logging.getLogger("gltd_notes")

DEFAULT_GUI_PORT = 18384


class SyncthingService:
    """Manages Syncthing lifecycle, devices, folders and status."""

    def __init__(self, config: Config):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._mode: str = "none"  # none, embedded, external
        self._api_url: str = ""
        self._api_key: str = ""
        self._load_config()

    def _load_config(self) -> None:
        sc = self.config.data.setdefault("syncthing", {})
        self._mode = sc.get("mode", "none")
        if self._mode == "embedded":
            self._api_url = f"http://127.0.0.1:{sc.get('port', DEFAULT_GUI_PORT)}"
            self._api_key = sc.get("api_key", "")
        elif self._mode == "external":
            self._api_url = sc.get("api_url", "http://127.0.0.1:8384")
            self._api_key = sc.get("api_key", "")
        else:
            self._api_url = ""
            self._api_key = ""

    def _bin_path(self) -> Path:
        custom = self.config.data.get("syncthing", {}).get("bin_path", "")
        if custom:
            return Path(custom).expanduser()
        return DEFAULT_INSTALL_ROOT / "ext_program" / "syncthing"

    def _home_dir(self) -> Path:
        default = str(self.config.data_root / "syncthing")
        return Path(self.config.data.get("syncthing", {}).get("home_dir", default))

    # ── lifecycle ──────────────────────────────────────────────

    def start(self) -> bool:
        if self._mode != "embedded":
            return False
        bin_path = self._bin_path()
        if not bin_path.exists():
            _log.warning("Syncthing binary not found at %s", bin_path)
            return False
        home = self._home_dir()
        home.mkdir(parents=True, exist_ok=True)
        port = self.config.data.get("syncthing", {}).get("port", DEFAULT_GUI_PORT)

        config_xml = home / "config.xml"
        if not config_xml.exists():
            if not self._init_config(bin_path, home, port, config_xml):
                return False

        try:
            self._process = subprocess.Popen(
                [str(bin_path), "--home", str(home), "--no-browser",
                 f"--gui-address=127.0.0.1:{port}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._ensure_api_key()
            self._configure_data_folder()
            self._ensure_device_name()
            return True
        except OSError as e:
            _log.warning("Failed to start syncthing: %s", e)
            return False

    def _init_config(self, bin_path: Path, home: Path, port: int, config_xml: Path) -> bool:
        _log.info("Initializing Syncthing config at %s", home)
        try:
            proc = subprocess.Popen(
                [str(bin_path), "--home", str(home), "--no-browser",
                 f"--gui-address=127.0.0.1:{port}", "--no-restart"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            for _ in range(30):
                if config_xml.exists():
                    break
                time.sleep(0.5)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

            if not config_xml.exists():
                return False

            import xml.etree.ElementTree as ET
            ET.register_namespace("", "http://syncthing.net/ns/config/1")
            tree = ET.parse(str(config_xml))
            root = tree.getroot()
            ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""

            def _find(parent, tag):
                return parent.find(f"{{{ns}}}{tag}") if ns else parent.find(tag)

            # GUI
            gui = _find(root, "gui")
            if gui is not None:
                for el_tag, val in [
                    ("address", f"127.0.0.1:{port}"),
                    ("tls", "false"),
                    ("apikey", ""),
                ]:
                    el = _find(gui, el_tag)
                    if el is not None:
                        el.text = val

            # Options
            opts = _find(root, "options")
            if opts is not None:
                for el_tag, val in [
                    ("globalAnnounceEnabled", "false"),
                    ("localAnnounceEnabled", "true"),
                    ("relaysEnabled", "false"),
                    ("natEnabled", "false"),
                    ("autoUpgradeIntervalH", "0"),
                ]:
                    el = _find(opts, el_tag)
                    if el is not None:
                        el.text = val

                # Device name
                device_name = f"gltd_notes_{socket.gethostname()}"
                dn = _find(opts, "deviceName")
                if dn is None:
                    dn = ET.SubElement(opts, f"{{{ns}}}deviceName" if ns else "deviceName")
                dn.text = device_name

            tree.write(str(config_xml), encoding="utf-8", xml_declaration=True)
            _log.info("Syncthing config initialized: %s", device_name)
            return True
        except Exception as e:
            _log.warning("Failed to init Syncthing config: %s", e)
            return False

    def stop(self) -> None:
        if self._mode == "embedded" and self._process:
            try:
                self._api_post("system/shutdown")
            except Exception:
                pass
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def restart(self) -> bool:
        self.stop()
        time.sleep(1)
        return self.start()

    def ping(self) -> bool:
        try:
            return self._api_get("system/ping", "{}").get("ping") == "pong"
        except Exception:
            return False

    def is_running(self) -> bool:
        if self._mode == "embedded":
            if self._process is not None and self._process.poll() is None:
                return True
            return self.ping()
        if self._mode == "external":
            return self.ping()

    def _ensure_device_name(self) -> None:
        """Update device name in config.xml if not matching expected pattern."""
        import xml.etree.ElementTree as ET

        config_xml = self._home_dir() / "config.xml"
        if not config_xml.exists():
            return
        try:
            expected = f"gltd_notes_{socket.gethostname()}"
            ET.register_namespace("", "http://syncthing.net/ns/config/1")
            tree = ET.parse(str(config_xml))
            root = tree.getroot()
            ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""

            def _find(parent, tag):
                return parent.find(f"{{{ns}}}{tag}") if ns else parent.find(tag)

            opts = _find(root, "options")
            if opts is not None:
                dn = _find(opts, "deviceName")
                if dn is not None and dn.text == expected:
                    return
                if dn is None:
                    dn = ET.SubElement(opts, f"{{{ns}}}deviceName" if ns else "deviceName")
                dn.text = expected
                tree.write(str(config_xml), encoding="utf-8", xml_declaration=True)
                _log.info("Syncthing device name updated to: %s", expected)
        except Exception:
            pass

    def _ensure_api_key(self) -> None:
        time.sleep(2)
        config_xml = self._home_dir() / "config.xml"
        for _ in range(15):
            if config_xml.exists():
                break
            time.sleep(1)
        if not config_xml.exists():
            return
        import xml.etree.ElementTree as ET

        tree = ET.parse(str(config_xml))
        root = tree.getroot()
        ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
        if ns:
            gui = root.find(f"{{{ns}}}gui")
        else:
            gui = root.find("gui")
        if gui is not None:
            if ns:
                apikey_el = gui.find(f"{{{ns}}}apikey")
            else:
                apikey_el = gui.find("apikey")
            if apikey_el is not None and apikey_el.text:
                self._api_key = apikey_el.text
                sc = self.config.data.setdefault("syncthing", {})
                sc["api_key"] = self._api_key

    # ── folder config ───────────────────────────────────────────

    def _configure_data_folder(self) -> None:
        data_root = str(self.config.data_root)
        folders = self._api_get("config/folders") or []
        folder_ids = [f.get("id", "") for f in folders]
        uh = self.config.active_user_hash or "default"

        # User's personal chain database
        user_path = str(Path(data_root) / "user" / uh)
        folder_id_user = f"gltd-notes-user-{uh[:12]}"
        if folder_id_user not in folder_ids:
            self._api_post("config/folders", {
                "id": folder_id_user,
                "label": "GLTD Notes — Minhas notas",
                "path": user_path,
                "type": "sendreceive",
                "rescanIntervalS": 3600,
            })

        # Shared folder
        shared_path = str(Path(data_root) / "shared")
        if "gltd-notes-shared" not in folder_ids:
            self._api_post("config/folders", {
                "id": "gltd-notes-shared",
                "label": "GLTD Notes — Compartilhados",
                "path": shared_path,
                "type": "sendreceive",
                "rescanIntervalS": 3600,
            })

    def add_shared_folder(self, username: str) -> Optional[str]:
        data_root = str(self.config.data_root)
        shared_path = Path(data_root) / "shared" / f"@{username}"
        shared_path.mkdir(parents=True, exist_ok=True)
        folder_id = f"gltd-shared-{username}"
        folders = self._api_get("config/folders") or []
        if not any(f.get("id") == folder_id for f in folders):
            return self._api_post("config/folders", {
                "id": folder_id,
                "label": f"GLTD Shared @{username}",
                "path": str(shared_path),
                "type": "sendreceive",
                "rescanIntervalS": 600,
            })
        return folder_id

    # ── devices ─────────────────────────────────────────────────

    def get_devices(self) -> List[Dict[str, Any]]:
        cfg = self._api_get("config/devices") or []
        status = self._api_get("system/connections") or {}
        conns = {c.get("deviceID", ""): c for c in status.get("connections", {})}
        result = []
        for d in cfg:
            did = d.get("deviceID", "")
            conn = conns.get(did, {})
            result.append({
                "deviceID": did,
                "name": d.get("name", did[:12]),
                "connected": conn.get("connected", False),
                "address": d.get("addresses", [""])[0] if d.get("addresses") else "",
            })
        return result

    def add_device(self, device_id: str, name: str = "", personal_network: bool = False) -> bool:
        existing = self._api_get("config/devices") or []
        if any(d.get("deviceID") == device_id for d in existing):
            return True
        self._api_post("config/devices", {
            "deviceID": device_id,
            "name": name or device_id[:12],
            "addresses": ["dynamic"],
            "compression": "metadata",
            "introducer": personal_network,
        })
        folders = self._api_get("config/folders") or []
        for f in folders:
            fdevices = [d.get("deviceID") for d in f.get("devices", [])]
            if device_id not in fdevices:
                fdevices.append({"deviceID": device_id})
                self._api_patch(f"config/folders/{f['id']}", {"devices": fdevices})
        return True

    def remove_device(self, device_id: str) -> bool:
        existing = self._api_get("config/devices") or []
        if not any(d.get("deviceID") == device_id for d in existing):
            return True
        self._api_delete(f"config/devices/{device_id}")
        return True

    # ── status ──────────────────────────────────────────────────

    def get_folder_status(self, folder_id: str = "gltd-notes-data") -> Dict[str, Any]:
        try:
            return self._api_get(f"db/status?folder={folder_id}") or {}
        except Exception:
            return {}

    def get_system_status(self) -> Dict[str, Any]:
        try:
            return self._api_get("system/status") or {}
        except Exception:
            return {}

    def get_completion(self, folder_id: str = "gltd-notes-data") -> Dict[str, Any]:
        try:
            return self._api_get(f"db/completion?folder={folder_id}") or {}
        except Exception:
            return {}

    # ── HTTP helpers ────────────────────────────────────────────

    def _api_get(self, path: str, default: Optional[Any] = None) -> Any:
        return self._api_request("GET", path, default=default)

    def _api_post(self, path: str, data: Any = None) -> Any:
        return self._api_request("POST", path, data)

    def _api_patch(self, path: str, data: Any = None) -> Any:
        return self._api_request("PATCH", path, data)

    def _api_delete(self, path: str) -> Any:
        return self._api_request("DELETE", path)

    def _api_request(self, method: str, path: str, data: Any = None,
                     default: Optional[Any] = None) -> Any:
        if not self._api_url:
            return default
        url = f"{self._api_url}/rest/{path}"
        headers = {"X-API-Key": self._api_key}
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except Exception as e:
            _log.debug("Syncthing API %s %s: %s", method, path, e)
            return default
