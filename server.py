import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from main import AudioProcessor
from eq_presets import PRESETS

processor = AudioProcessor()

main_loop = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    # Startup
    processor.start()
    yield
    # Shutdown
    processor.stop()

app = FastAPI(lifespan=lifespan)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

class Settings(BaseModel):
    min_dwell_seconds: float
    manual_override: str | None = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

def on_audio_update(state):
    # This is called from the background thread
    if main_loop and not main_loop.is_closed():
        message = {
            "type": "state",
            "state": state
        }
        asyncio.run_coroutine_threadsafe(manager.broadcast(message), main_loop)

processor.on_update(on_audio_update)

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/presets")
async def get_presets():
    return PRESETS

@app.post("/settings")
async def update_settings(settings: Settings):
    processor.min_dwell_seconds = settings.min_dwell_seconds
    if settings.manual_override in (None, "auto"):
        processor.manual_override = None
    elif settings.manual_override in PRESETS:
        processor.manual_override = settings.manual_override
    else:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {settings.manual_override!r}")

    return {
        "status": "success", 
        "min_dwell_seconds": processor.min_dwell_seconds,
        "manual_override": processor.manual_override
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await websocket.send_json({
        "type": "init",
        "min_dwell_seconds": processor.min_dwell_seconds,
        "manual_override": processor.manual_override,
        "presets": PRESETS
    })
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)
