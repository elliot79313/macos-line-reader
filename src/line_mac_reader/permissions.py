"""macOS privacy-permission self-checks.

Both Screen Recording and Accessibility must be granted to the process
running this tool (the terminal app or the Python interpreter). We check
up-front and fail with actionable messages instead of silently capturing
black screenshots or having clicks ignored.
"""

from __future__ import annotations

import sys

SCREEN_RECORDING_HELP = (
    "Screen Recording permission is missing.\n"
    "  System Settings → Privacy & Security → Screen Recording →\n"
    "  enable your terminal app (Terminal/iTerm2) or the Python binary,\n"
    "  then RESTART the terminal app."
)

ACCESSIBILITY_HELP = (
    "Accessibility permission is missing.\n"
    "  System Settings → Privacy & Security → Accessibility →\n"
    "  enable your terminal app (Terminal/iTerm2) or the Python binary."
)


def check_permissions() -> list[str]:
    """Return a list of human-readable errors; empty list means all good."""
    if sys.platform != "darwin":
        return ["This tool only runs on macOS."]

    errors: list[str] = []
    try:
        import Quartz

        if not Quartz.CGPreflightScreenCaptureAccess():
            # Trigger the system prompt so the user gets the dialog once.
            Quartz.CGRequestScreenCaptureAccess()
            errors.append(SCREEN_RECORDING_HELP)
    except Exception as exc:  # pyobjc missing/broken
        errors.append(f"Could not verify Screen Recording permission: {exc}")

    try:
        from ApplicationServices import AXIsProcessTrusted

        if not AXIsProcessTrusted():
            errors.append(ACCESSIBILITY_HELP)
    except Exception as exc:
        errors.append(f"Could not verify Accessibility permission: {exc}")

    return errors
