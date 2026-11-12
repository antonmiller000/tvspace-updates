"""Entry points used by the Android app (the Python side runs inside the APK)."""
import threading

from . import server

_started = False


def start(data_dir: str, port: int = 8765):
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=server.serve, args=(data_dir, port), daemon=True, name="server").start()


def busy() -> bool:
    app = server.Handler.app
    return bool(app) and any(j.status == "running" for j in list(app.jobs.values()))
