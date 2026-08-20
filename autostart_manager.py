"""
Manages the "Start with Windows" toggle via a real .lnk shortcut in the
Startup folder -- launched directly by explorer.exe at logon, the same
mechanism as every other Startup entry.

This used to write a .vbs wrapper invoked through wscript.exe. On this
machine (and plausibly others with similar AV/EDR posture), wscript.exe was
silently blocked from spawning child processes -- the .vbs "succeeded" with
no error, but pythonw.exe never actually started. See shortcuts.py for how
that was diagnosed. A .lnk avoids the script host entirely.
"""

import os
import sys
import shutil

from shortcuts import create_shortcut, remove_shortcut

APP_NAME = "SoundIntelligence"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, f"{APP_NAME}.ico")
ENTRY_SCRIPT = os.path.join(SCRIPT_DIR, "app_native.py")


def get_startup_dir() -> str:
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def _startup_lnk_path() -> str:
    return os.path.join(get_startup_dir(), f"{APP_NAME}.lnk")


def _pythonw_path() -> str:
    """The pythonw.exe alongside the interpreter running this file --
    avoids depending on PATH resolution at logon time."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    found = shutil.which("pythonw.exe") or shutil.which("pythonw")
    return found or "pythonw.exe"


def is_autostart_enabled() -> bool:
    startup_dir = get_startup_dir()
    # Also true if an old, non-functional .vbs entry is still sitting there
    # from before this fix -- treated as "enabled" so the toggle offers to
    # clean it up rather than silently leaving dead state on disk.
    return (
        os.path.exists(os.path.join(startup_dir, f"{APP_NAME}.lnk"))
        or os.path.exists(os.path.join(startup_dir, f"{APP_NAME}.vbs"))
    )


def set_autostart(enable: bool = True) -> bool:
    startup_dir = get_startup_dir()
    lnk_path = os.path.join(startup_dir, f"{APP_NAME}.lnk")
    old_vbs_path = os.path.join(startup_dir, f"{APP_NAME}.vbs")

    # Always clear the old broken .vbs entry, enable or disable, since it
    # never actually worked and shouldn't linger.
    if os.path.exists(old_vbs_path):
        remove_shortcut(old_vbs_path)

    if not enable:
        return remove_shortcut(lnk_path)

    if not os.path.exists(ENTRY_SCRIPT):
        print(f"[Autostart Error] {ENTRY_SCRIPT} not found")
        return False

    return create_shortcut(
        lnk_path,
        target=_pythonw_path(),
        arguments=f'"{ENTRY_SCRIPT}"',
        working_dir=SCRIPT_DIR,
        description=f"{APP_NAME} -- adaptive EQ engine",
        icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ["--enable", "-e", "enable"]:
            success = set_autostart(True)
            print("Auto-start enabled" if success else "Failed to enable auto-start")
        elif arg in ["--disable", "-d", "disable"]:
            success = set_autostart(False)
            print("Auto-start disabled" if success else "Failed to disable auto-start")
        elif arg in ["--status", "-s", "status"]:
            print("Enabled" if is_autostart_enabled() else "Disabled")
    else:
        print(f"Current Autostart Status: {'Enabled' if is_autostart_enabled() else 'Disabled'}")
