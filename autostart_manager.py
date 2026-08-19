import os
import sys

def get_startup_dir() -> str:
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

def get_vbs_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "SoundIntelligence.vbs")

def is_autostart_enabled() -> bool:
    startup_dir = get_startup_dir()
    vbs_link = os.path.join(startup_dir, "SoundIntelligence.lnk")
    vbs_file = os.path.join(startup_dir, "SoundIntelligence.vbs")
    return os.path.exists(vbs_link) or os.path.exists(vbs_file)

def set_autostart(enable: bool = True) -> bool:
    startup_dir = get_startup_dir()
    vbs_source = get_vbs_path()
    target_vbs = os.path.join(startup_dir, "SoundIntelligence.vbs")
    
    if enable:
        if not os.path.exists(vbs_source):
            return False
        try:
            # Invoke wscript.exe explicitly rather than relying on the .vbs
            # file association, which can be remapped (e.g. by an editor).
            content = (
                'Set WshShell = CreateObject("WScript.Shell")\r\n'
                f'WshShell.Run "wscript.exe " & Chr(34) & "{vbs_source}" & Chr(34), 0, False\r\n'
                'Set WshShell = Nothing\r\n'
            )
            with open(target_vbs, "w", encoding="ascii") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"[Autostart Error] {e}")
            return False
    else:
        try:
            if os.path.exists(target_vbs):
                os.remove(target_vbs)
            target_lnk = os.path.join(startup_dir, "SoundIntelligence.lnk")
            if os.path.exists(target_lnk):
                os.remove(target_lnk)
            return True
        except Exception as e:
            print(f"[Autostart Error] {e}")
            return False

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
