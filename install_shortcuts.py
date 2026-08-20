"""
Creates Desktop and Start Menu shortcuts for SoundIntelligence, so it's
launchable from the Desktop and findable by Windows Search -- previously it
only existed as loose files in this folder, with no shell integration at all.

Run directly (safe to re-run any time, e.g. after moving this folder):
    python install_shortcuts.py
"""

import os
import sys

from shortcuts import create_shortcut, remove_shortcut

APP_NAME = "SoundIntelligence"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(SCRIPT_DIR, f"{APP_NAME}.ico")
ENTRY_SCRIPT = os.path.join(SCRIPT_DIR, "app_native.py")


def _pythonw_path() -> str:
    import shutil
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(candidate):
        return candidate
    return shutil.which("pythonw.exe") or shutil.which("pythonw") or "pythonw.exe"


def _start_menu_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")


def _desktop_dir() -> str:
    # OneDrive can redirect the Desktop folder; USERPROFILE\Desktop is the
    # fallback but check the registry-backed known folder first via
    # environment when available.
    onedrive = os.environ.get("OneDrive")
    if onedrive and os.path.isdir(os.path.join(onedrive, "Desktop")):
        return os.path.join(onedrive, "Desktop")
    return os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")


def install(desktop: bool = True, start_menu: bool = True) -> dict:
    if not os.path.exists(ENTRY_SCRIPT):
        raise FileNotFoundError(f"{ENTRY_SCRIPT} not found -- run this from the project folder")

    icon = ICON_PATH if os.path.exists(ICON_PATH) else None
    target = _pythonw_path()
    args = f'"{ENTRY_SCRIPT}"'
    results = {}

    if desktop:
        path = os.path.join(_desktop_dir(), f"{APP_NAME}.lnk")
        results["desktop"] = create_shortcut(
            path, target=target, arguments=args, working_dir=SCRIPT_DIR,
            description=f"{APP_NAME} -- adaptive EQ engine", icon=icon,
        )

    if start_menu:
        path = os.path.join(_start_menu_dir(), f"{APP_NAME}.lnk")
        results["start_menu"] = create_shortcut(
            path, target=target, arguments=args, working_dir=SCRIPT_DIR,
            description=f"{APP_NAME} -- adaptive EQ engine", icon=icon,
        )

    return results


def uninstall() -> dict:
    results = {
        "desktop": remove_shortcut(os.path.join(_desktop_dir(), f"{APP_NAME}.lnk")),
        "start_menu": remove_shortcut(os.path.join(_start_menu_dir(), f"{APP_NAME}.lnk")),
    }
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--uninstall", "-u"):
        r = uninstall()
        print(f"Desktop shortcut removed: {r['desktop']}")
        print(f"Start Menu shortcut removed: {r['start_menu']}")
    else:
        r = install()
        for k, ok in r.items():
            print(f"{k.replace('_', ' ').title()} shortcut: {'created' if ok else 'FAILED'}")
