"""
Creates real Windows shortcut (.lnk) files via PowerShell's WScript.Shell COM
object -- deliberately NOT via wscript.exe directly.

Diagnosed on this machine: WshShell.Run launching pythonw.exe from a .vbs
executed by wscript.exe was silently swallowed -- no error, no process, no
window. Side-by-side test: the identical spawn via cmd.exe succeeded, the
wscript.exe one didn't. That points at wscript.exe specifically being
blocked from spawning child processes (a common AV/EDR behavior, since
wscript-spawns-executable is a classic malware pattern).

PowerShell authoring a .lnk *file* doesn't spawn anything at creation time,
and the resulting shortcut is later launched by explorer.exe (Desktop,
Start Menu) or the Startup-folder mechanism -- neither goes through a
script host, so this sidesteps whatever blocked the old approach.
"""

import os
import subprocess


def _ps_quote(s: str) -> str:
    """Escape a string for embedding inside a PowerShell double-quoted
    string (double the backticks and double-quotes; PS doesn't treat
    backslash as an escape character, so paths pass through as-is)."""
    return s.replace("`", "``").replace('"', '`"')


def create_shortcut(lnk_path: str, target: str, arguments: str = "",
                     working_dir: str = "", description: str = "",
                     icon: str = None) -> bool:
    lines = [
        "$ws = New-Object -ComObject WScript.Shell",
        f'$sc = $ws.CreateShortcut("{_ps_quote(lnk_path)}")',
        f'$sc.TargetPath = "{_ps_quote(target)}"',
        f'$sc.Arguments = "{_ps_quote(arguments)}"',
        f'$sc.WorkingDirectory = "{_ps_quote(working_dir)}"',
        f'$sc.Description = "{_ps_quote(description)}"',
    ]
    if icon:
        lines.append(f'$sc.IconLocation = "{_ps_quote(icon)}"')
    lines.append("$sc.Save()")
    script = "\n".join(lines)

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            print(f"[shortcuts] PowerShell failed for {lnk_path}: {result.stderr.strip()}")
        return result.returncode == 0 and os.path.exists(lnk_path)
    except Exception as e:
        print(f"[shortcuts] failed to create {lnk_path}: {e}")
        return False


def remove_shortcut(lnk_path: str) -> bool:
    try:
        if os.path.exists(lnk_path):
            os.remove(lnk_path)
        return True
    except Exception as e:
        print(f"[shortcuts] failed to remove {lnk_path}: {e}")
        return False
