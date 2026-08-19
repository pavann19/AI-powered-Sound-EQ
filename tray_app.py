import sys
import os
import threading
import subprocess
import webbrowser
import time

from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QPixmap, QImage, QColor, QPainter, QBrush, QPen
from PyQt5.QtCore import Qt

import uvicorn
from autostart_manager import is_autostart_enabled, set_autostart

APP_PORT = 8000
APP_URL = f"http://127.0.0.1:{APP_PORT}"

def create_tray_icon_pixmap() -> QPixmap:
    """Dynamically generates a crisp, Apple-style glowing headphone icon."""
    size = 64
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # Outer glowing squircle background
    painter.setBrush(QBrush(QColor(10, 132, 255)))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 16, 16)
    
    # Inner headphones arc
    painter.setBrush(Qt.NoBrush)
    pen = QPen(QColor(255, 255, 255), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    
    # Headband arc
    painter.drawArc(16, 16, 32, 32, 0, 180 * 16)
    
    # Left and Right earcups
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(14, 28, 7, 16, 3, 3)
    painter.drawRoundedRect(43, 28, 7, 16, 3, 3)
    
    painter.end()
    return QPixmap.fromImage(image)

def open_standalone_window(compact: bool = False):
    """Launches SoundIntelligence in a standalone, frameless desktop app window."""
    url = f"{APP_URL}?mode=compact" if compact else APP_URL
    size_flag = "--window-size=440,780" if compact else "--window-size=1200,860"
    
    # Try launching using Edge App mode for native frameless window
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    
    launched = False
    for path in edge_paths:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, f"--app={url}", size_flag, "--app-id=SoundIntelligenceStudio"])
                launched = True
                break
            except Exception:
                pass
                
    if not launched:
        webbrowser.open(url)

class ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = None

    def run(self):
        config = uvicorn.Config(
            "server:app",
            host="127.0.0.1",
            port=APP_PORT,
            log_level="warning",
            reload=False
        )
        self.server = uvicorn.Server(config)
        self.server.run()

    def stop(self):
        if self.server:
            self.server.should_exit = True

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    # 1. Start Server Background Thread
    server_thread = ServerThread()
    server_thread.start()
    
    # 2. Setup System Tray
    pixmap = create_tray_icon_pixmap()
    icon = QIcon(pixmap)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("SoundIntelligence · Spatial Audio Engine (Active)")
    
    # 3. Tray Context Menu
    menu = QMenu()
    
    title_action = QAction("🎧 SoundIntelligence Studio Pro", menu)
    title_action.setEnabled(False)
    menu.addAction(title_action)
    menu.addSeparator()
    
    open_action = QAction("✨ Open Studio Window", menu)
    open_action.triggered.connect(lambda: open_standalone_window(compact=False))
    menu.addAction(open_action)
    
    mini_action = QAction("📱 Compact Mini Player", menu)
    mini_action.triggered.connect(lambda: open_standalone_window(compact=True))
    menu.addAction(mini_action)
    
    menu.addSeparator()
    
    # Autostart Toggle Action
    autostart_action = QAction("⚡ Start with Windows", menu, checkable=True)
    autostart_action.setChecked(is_autostart_enabled())
    
    def toggle_autostart():
        new_state = autostart_action.isChecked()
        set_autostart(new_state)
        tray.showMessage(
            "SoundIntelligence",
            f"Windows Auto-start {'Enabled' if new_state else 'Disabled'}",
            QSystemTrayIcon.Information,
            2000
        )
        
    autostart_action.triggered.connect(toggle_autostart)
    menu.addAction(autostart_action)
    
    menu.addSeparator()
    
    quit_action = QAction("❌ Exit SoundIntelligence", menu)
    
    def on_quit():
        server_thread.stop()
        tray.hide()
        QApplication.quit()
        
    quit_action.triggered.connect(on_quit)
    menu.addAction(quit_action)
    
    tray.setContextMenu(menu)
    
    # Click behavior
    def on_tray_activated(reason):
        if reason in [QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick]:
            open_standalone_window(compact=False)
            
    tray.activated.connect(on_tray_activated)
    tray.show()
    
    tray.showMessage(
        "SoundIntelligence Active",
        "Spatial Audio Engine is monitoring in background. Double-click icon anytime.",
        QSystemTrayIcon.Information,
        3000
    )
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
