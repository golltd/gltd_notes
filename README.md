# GLTD Notes — Personal Notepad with Multi-Machine Sync

## What is GLTD Notes?

A **private, open-source** note-taking application for Linux, built as an alternative to GNote. It offers a desktop GUI (GTK 3), a local web server, and a REST API — all running on your machine, with no cloud or external server dependency.

### Why does it exist?

- **Real privacy**: all data stays on your computer, in your folder.
- **Multi-machine synchronization**: use **Syncthing** to keep your notes synced across multiple computers without a central server. The storage format avoids conflicts when two people edit at the same time.
- **Complete history**: every change is recorded. You can revert to any previous version of a note.
- **Built-in AI agents**: describe tasks in natural language and have DeepSeek (via opencode), Grok, or Gemini execute them automatically.

> **This application was developed with AI assistance using Grok (xAI) and DeepSeek V4 (via opencode).**

---

## How to Install

### 1. System Dependencies

Run the following command in the terminal (Linux Mint / Ubuntu / Debian):

```bash
sudo apt install python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-notify-0.7 \
  gir1.2-ayatanaappindicator3-0.1 libnotify-bin
```

### 2. File Locations

The program is installed at:

```
/var/PROGRAMAS/gltd_notes/          ← application code
~/gltd_notes_data/                ← your data (notes, attachments, history)
~/.config/gltd_notes/config.json    ← local config and passwords
~/.local/share/gltd_notes/session/  ← lock screen session control
```

### 3. Initial Setup (first use)

Before opening the program, create your user and set a password:

```bash
/var/PROGRAMAS/gltd_notes/bin/gltd-notes init \
  --data-root ~/gltd_notes_data \
  --username YOUR_USERNAME --password 'YOUR_PASSWORD'
```

### 4. Create System Menu Shortcuts (optional)

```bash
/var/PROGRAMAS/gltd_notes/scripts/install_desktop.sh
```

This adds menu entries and links in `~/.local/bin/` for the `gltd-notes`, `gltd-notes-api`, and `gltd-notes-web` commands.

---

## How to Use

### Desktop GUI (normal mode)

```bash
gltd-notes gui
```

- Create, edit, and delete notes with rich text formatting.
- Attach files (images, PDFs, anything) — each file is stored by content, avoiding duplicates.
- View the **history** of changes and restore previous versions.
- Create **events/reminders** that trigger desktop notifications.
- Use the **system tray icon** for quick access: new note, new event, show window, quit.
- **Lock the session** with a password — while locked, no one can access the notes.

### Web Interface

```bash
gltd-notes web
```

Open your browser at `http://127.0.0.1:8765` to access your notes via the web.

### REST API

```bash
gltd-notes api
```

The REST API is available at `http://127.0.0.1:8765` (localhost only). All requests require the header:

```
X-API-Key: <key from ~/.config/gltd_notes/config.json>
```

Examples:

```bash
# Get the API key
KEY=$(python3 -c "import json;print(json.load(open('$HOME/.config/gltd_notes/config.json'))['api']['api_key'])")

# Health check
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/health

# Create a note
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"title":"My note","body":"Note content via API"}' \
  http://127.0.0.1:8765/api/v1/notes

# List all notes
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8765/api/v1/notes
```

---

## AI Agent Tasks

GLTD Notes lets you delegate tasks to AI agents. Write what you need done and the agent executes it in the terminal.

### Available Agents

| Interface Name | CLI Tool | Description |
|----------------|----------|-------------|
| `opencode-deepseek4` | `opencode run` | Executes tasks using DeepSeek V4 |
| `grok` | `grok` | Executes tasks using Grok |
| `gemini` | `gemini` | Executes tasks using Gemini |

### How to Use

1. In the menu, go to **Tasks → New agent task**.
2. Choose the agent (recommended: `opencode-deepseek4`).
3. Describe the task in natural language. Be specific.
4. Click **▶ Execute** and wait for the result in the output field.

### Example Task

```
Configure server 192.0.2.1:
1. Access via SSH as root
2. Install and configure MariaDB
3. Create database "prod_app"
4. Create user "app_user" with a secure password
5. Set up daily backup with cron
```

For more details about agents, see [README_AGENT.md](README_AGENT.md).

---

## Multi-Machine Sync with Syncthing

1. Install [Syncthing](https://syncthing.net/) on all machines.
2. On each machine, share the GLTD Notes data folder (`~/gltd_notes_data`).
3. Done. Notes sync automatically.

**Why no conflicts?** The program uses a special format called "note blockchain": each change is a new block appended to the end of the file, with machine and user identification. When two people edit the same note at the same time, both versions are preserved and can be viewed in the history.

---

## Note Sharing

In GLTD Notes you can share notes with other users:

- Private notes: visible only to you.
- Shared notes: copied to the `shared/` area and visible to all listed users.
- History shows which user and which machine produced each change.

---

## Documentation

| File | Content |
|------|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Storage, blockchain, and multi-machine sync |
| [docs/API.md](docs/API.md) | Complete REST API reference |
| [docs/SECURITY.md](docs/SECURITY.md) | Authentication and security model |
| [docs/PACKAGING.md](docs/PACKAGING.md) | Future plans (.deb, AppImage, etc.) |
| [README_AGENT.md](README_AGENT.md) | Detailed guide for AI agent tasks |

---

## Versioning

Version numbers follow the format `MAJOR.MINOR.PATCH` (semantic versioning):

- **MAJOR**: incompatible API changes or complete rewrites (currently `0` — pre-stable)
- **MINOR**: new features, new subcommands, new UI pages (`1`)
- **PATCH**: bug fixes, small improvements, README updates — **auto-incremented on every commit**

The patch number is managed automatically by `.githooks/pre-commit`, which runs `scripts/bump_version.sh` before each commit. The canonical version source is `gltd_notes/_version.py` — all other references (`pyproject.toml`, API health endpoints, `__init__.py`) derive from it.

---

## Repository Branches (AI Agent Rules)

This repository uses two branches:

| Branch | Purpose |
|--------|---------|
| `main` | **Stable, tested code only.** Commits here only when the user explicitly requests with phrases like "commit to main", "merge to main", "go to production". |
| `indev` | **In-development code and planning.** Code here may be incomplete, not yet operational, or under testing. **Automatic commits (bump, pre-commit hooks) go to `indev` by default.** |

**Law for AI agents (Grok, DeepSeek, and any assistant):**

1. The default commit target is `indev`. Never commit to `main` unless the user explicitly asks.
2. The pre-commit hook will reject commits to `main` unless `GLTD_COMMIT_MAIN=1` is set.
3. **Never commit personal information** — no real IPs, passwords, hostnames, personal file paths, or real usernames in any branch. Use `192.0.2.0/24` (RFC 5737) for example IPs, `~/gltd_notes_data/` for paths, `YOUR_USER` for usernames. This applies to code, comments, docs, and commit messages.

---

## Donations

If GLTD Notes is useful to you, consider supporting its development:

- **PIX (Brazil)**: `1f57a276-dc0e-44a0-a4e0-4a2349833958`
- **Monero (XMR)**: `84pnTEwRrFLPUqSNQdCLFw6X6gjQeQtdNNVxkYAfvgd229DHgNYzzQ9VgpquUG8RfAJJ5Py556KrAiG47PqKYxPM1mzpAtb`

---

## About Development

This application was developed with **artificial intelligence** assistance using:

- **Grok** (xAI) — prototyping and initial iterations
- **DeepSeek V4** via opencode — final architecture, refinement, and completeness

The code is 100% open (MIT license). See the [LICENSE](LICENSE) file.
