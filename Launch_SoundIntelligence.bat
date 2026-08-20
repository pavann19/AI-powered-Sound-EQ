@echo off
REM Launches directly via pythonw.exe -- the previous wscript.exe-based
REM indirection was found to be silently blocked on this machine (no error,
REM the app just never started). See shortcuts.py for how that was diagnosed.
start "" pythonw.exe "%~dp0app_native.py"
exit
