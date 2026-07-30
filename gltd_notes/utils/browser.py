"""Open a URL in the user's browser reliably on Linux desktop."""

from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from typing import List, Optional, Sequence


def open_url(url: str) -> bool:
    """Try multiple launchers; return True if one was started."""
    env = os.environ.copy()
    # Prefer user's graphical session
    candidates: List[Sequence[str]] = []
    if shutil.which("xdg-open"):
        candidates.append(["xdg-open", url])
    if shutil.which("gio"):
        candidates.append(["gio", "open", url])
    if shutil.which("x-www-browser"):
        candidates.append(["x-www-browser", url])
    if shutil.which("sensible-browser"):
        candidates.append(["sensible-browser", url])
    for name in ("firefox", "firefox-esr", "google-chrome", "chromium", "chromium-browser", "brave-browser"):
        if shutil.which(name):
            if "firefox" in name:
                candidates.append([name, "--new-tab", url])
            else:
                candidates.append([name, url])

    for cmd in candidates:
        try:
            subprocess.Popen(
                list(cmd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            return True
        except Exception:
            continue

    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False
