"""Own only the child we start; never kill a process merely occupying a port."""
import atexit
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import requests


class NetworkServer:
    def __init__(self, port=8000):
        self.port, self.process, self.lock = port, None, threading.Lock()
        atexit.register(self.close)

    def ready(self):
        try:
            r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=0.5)
            return r.status_code == 200 and r.json().get("service") == "clinical-mcp-sse"
        except (requests.RequestException, ValueError):
            return False

    def ensure(self):
        with self.lock:
            if self.ready():
                return
            if self.process is None or self.process.poll() is not None:
                self.process = subprocess.Popen([sys.executable, "-m", "clinical_mcp.server", "--sse", "--port", str(self.port)],
                    cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.ready():
                    return
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            raise RuntimeError("Сетевой MCP-сервер не готов. Проверьте, свободен ли порт 8000.")

    def close(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.process = None
