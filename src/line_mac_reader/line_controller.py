"""Launch LINE, bring it to the foreground, and pin its main window.

Pinning the window to a fixed position/size (allowed per SOW §9) is what makes
every coordinate in config meaningful; without it the badge/region offsets
would drift between runs.
"""

from __future__ import annotations

import subprocess
import time

from .config import Config
from .models import Rect

APP_NAME = "LINE"


class LineNotFoundError(RuntimeError):
    pass


def _run_osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=15
    )
    if proc.returncode != 0:
        raise RuntimeError(f"osascript failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


class LineController:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def launch_and_focus(self) -> Rect:
        """Start LINE (if needed), focus it, pin the window; returns its rect."""
        if not self._is_running():
            proc = subprocess.run(
                ["open", "-a", APP_NAME], capture_output=True, text=True
            )
            if proc.returncode != 0:
                raise LineNotFoundError(
                    "Could not launch LINE. Is the desktop app installed? "
                    f"({proc.stderr.strip()})"
                )
            time.sleep(self.cfg.timing.app_launch_wait)

        self._activate()
        time.sleep(self.cfg.timing.click_wait)

        if self.cfg.window.move_window:
            self._pin_window(self.cfg.window.rect)
            time.sleep(self.cfg.timing.click_wait)

        rect = self.get_window_rect()
        if rect.width < 400 or rect.height < 300:
            raise LineNotFoundError(
                f"LINE window looks too small ({rect.width}x{rect.height}) — "
                "is it still on the login screen? Log in manually first."
            )
        return rect

    def _is_running(self) -> bool:
        try:
            from AppKit import NSWorkspace

            for app in NSWorkspace.sharedWorkspace().runningApplications():
                if app.localizedName() == APP_NAME:
                    return True
            return False
        except ImportError:
            out = subprocess.run(
                ["pgrep", "-x", APP_NAME], capture_output=True, text=True
            )
            return out.returncode == 0

    def _activate(self) -> None:
        _run_osascript(f'tell application "{APP_NAME}" to activate')

    def _pin_window(self, r: Rect) -> None:
        script = (
            f'tell application "System Events" to tell process "{APP_NAME}"\n'
            f'  set position of window 1 to {{{r.x}, {r.y}}}\n'
            f'  set size of window 1 to {{{r.width}, {r.height}}}\n'
            f'end tell'
        )
        try:
            _run_osascript(script)
        except RuntimeError as exc:
            raise LineNotFoundError(
                "Could not position the LINE window. Either LINE has no window "
                "(not logged in?) or Accessibility permission is missing. "
                f"Details: {exc}"
            ) from exc

    def get_window_rect(self) -> Rect:
        script = (
            f'tell application "System Events" to tell process "{APP_NAME}"\n'
            f'  set p to position of window 1\n'
            f'  set s to size of window 1\n'
            f'  return (item 1 of p as text) & "," & (item 2 of p as text) & "," '
            f'& (item 1 of s as text) & "," & (item 2 of s as text)\n'
            f'end tell'
        )
        try:
            out = _run_osascript(script)
            x, y, w, h = (int(v) for v in out.split(","))
            return Rect(x, y, w, h)
        except (RuntimeError, ValueError) as exc:
            raise LineNotFoundError(
                "Could not read the LINE window geometry — is LINE running and "
                f"logged in? Details: {exc}"
            ) from exc
