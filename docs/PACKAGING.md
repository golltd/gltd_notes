# Packaging guide (future installers)

This document prepares **.deb**, **AppImage**, **Windows**, and **Android** packaging. The v0.1 tree is already layout-friendly.

## Shared requirements for installers

Installers / first-run must collect or accept:

| Setting | Default | Notes |
|---------|---------|-------|
| Data root | OS-specific | Syncthing folder |
| API host | `127.0.0.1` | Do not expose publicly without TLS + stronger auth |
| API port | `8765` | |
| Web UI port | `8766` | Optional |
| Initial username/password | prompt | Creates `user_hash` |
| Autostart API/GUI | optional | systemd user unit / Task Scheduler |

Environment overrides (recommended convention):

```
GLTD_NOTES_DATA_ROOT=
GLTD_NOTES_API_HOST=
GLTD_NOTES_API_PORT=
GLTD_NOTES_WEB_PORT=
GLTD_NOTES_CONFIG=
```

(CLI already accepts `--data-root`, `--api-host`, `--api-port` on `init` / `api` / `web`.)

## Debian / Linux Mint `.deb`

Suggested layout after install:

```
/usr/lib/gltd-notes/          # or keep /var/PROGRAMAS/gltd_notes
/usr/bin/gltd-notes -> wrapper
/usr/share/applications/gltd-notes.desktop
/usr/share/doc/gltd-notes/
```

Depends:

```
python3, python3-gi, gir1.2-gtk-3.0, gir1.2-notify-0.7,
gir1.2-ayatanaappindicator3-0.1, libnotify4
```

Build sketch:

```bash
# future
mkdir -p deb/DEBIAN deb/usr/lib/gltd-notes deb/usr/bin
cp -a /var/PROGRAMAS/gltd_notes/. deb/usr/lib/gltd-notes/
# write deb/DEBIAN/control, postinst (install_desktop), prerm
dpkg-deb --build deb gltd-notes_0.1.0_all.deb
```

Optional systemd user unit `gltd-notes-api.service` ExecStart=`gltd-notes api`.

## AppImage

1. Stage appdir with Python runtime **or** rely on system Python (simpler, less portable).
2. Use `appimagetool` on an AppDir containing `AppRun` that sets `PYTHONPATH` and launches `python3 -m gltd_notes gui`.
3. Ship a script that checks for `python3-gi` and shows a clear error if missing.

Alternative: **PyInstaller** onedir + AppImage wrap.

## Windows installer

Challenges: GTK3 on Windows (MSYS2 / gvsbuild) or ship **web UI only** as the Windows primary UI.

Recommended path for v1 Windows:

1. Bundle Python embedded + pure stdlib services (`api` + `web`).
2. Use Inno Setup / WiX to choose install dir, data dir, ports.
3. Register firewall rule for localhost only (no public bind).
4. Optional: tray via `pystray` later.

Data root default: `%LOCALAPPDATA%\GLTD\gltd_notes`.

## Android (future)

Out of scope for v0.1 runtime. Options:

| Approach | Pros | Cons |
|----------|------|------|
| Kivy / BeeWare Briefcase | Python reuse | Heavy packaging |
| Flutter / Kotlin client talking to REST | Native UX | Need always-on PC API or local port of storage |
| Termux + same Python tree | Fast prototype | Not Play Store APK |

APK checklist for a later release:

1. Port `blockchain.py` + `storage.py` + `notes.py` to mobile paths (`context.filesDir`).
2. Local REST optional; Syncthing via Syncthing-Fork shared folder.
3. Notifications via Android `NotificationManager` (map from `EventsService.due_for_notification`).
4. Automated tests: instrumented Espresso + file fixtures for chain replay.
5. CI: build debug APK, install on emulator, run smoke create/list note.

**Never** ship a default public-bind API key in mobile builds.

## Configuration UI for installers

All packages should surface the same settings page:

- Data directory browser
- API bind address/port (default loopback)
- Web UI enable + port
- Create first user
- Show/regenerate API key
- “Open Syncthing docs” link

## Versioning

Use semver. Package version must match `gltd_notes.__version__` and `pyproject.toml`.

## Smoke test matrix (all packages)

1. `init` creates user + directories  
2. Create note → file appears under `notas/*.gltdnote`  
3. Chain validates (`/api/v1/chains/validate`)  
4. Attach file → `arquivos/xxx/hash`  
5. Share to second user → `shared/`  
6. Revert from history  
7. Event due → notification path invoked  
