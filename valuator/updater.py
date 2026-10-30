"""In-app updates from GitHub Releases (expects a LonestarValuator.exe asset on each release)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__
from .net import make_session

ASSET_NAME = "LonestarValuator.exe"


def _ver(v: str) -> tuple:
    out = []
    for p in v.lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def check(repo: str) -> dict | None:
    """Return {"version", "url", "notes"} if a newer release exists, else None."""
    if not repo:
        return None
    r = make_session().get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    tag = data.get("tag_name", "")
    if _ver(tag) <= _ver(__version__):
        return None
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower() == ASSET_NAME.lower()), None)
    if not asset:
        return None
    return {"version": tag, "url": asset["browser_download_url"], "notes": data.get("body") or ""}


def install(url: str) -> bool:
    """Download the new exe and swap it in after this process exits. Frozen builds only."""
    if not getattr(sys, "frozen", False):
        return False
    current = Path(sys.executable)
    tmp = Path(tempfile.gettempdir()) / "LonestarValuator_update.exe"
    with make_session().get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    bat = Path(tempfile.gettempdir()) / "lsv_update.bat"
    bat.write_text(
        "@echo off\r\n"
        f"ping 127.0.0.1 -n 3 > nul\r\n"
        f":retry\r\n"
        f'move /y "{tmp}" "{current}" > nul 2>&1\r\n'
        f"if errorlevel 1 (ping 127.0.0.1 -n 2 > nul & goto retry)\r\n"
        f'start "" "{current}"\r\n'
        f'del "%~f0"\r\n', encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     close_fds=True, cwd=os.path.dirname(str(bat)))
    return True
