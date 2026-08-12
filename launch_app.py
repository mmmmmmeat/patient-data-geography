from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAP_PORT = 8000
STREAMLIT_PORT = 8501


def find_python_command() -> list[str]:
    return [sys.executable]


def start_static_server() -> ThreadingHTTPServer:
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", MAP_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def start_streamlit() -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    cmd = find_python_command() + [
        "-m",
        "streamlit",
        "run",
        str(ROOT / "setup_ui.py"),
        "--server.port",
        str(STREAMLIT_PORT),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env)


def open_browser_when_ready(url: str, delay_seconds: float = 2.0) -> None:
    def _open() -> None:
        time.sleep(delay_seconds)
        webbrowser.open(url, new=2)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    static_server = start_static_server()
    streamlit_proc = start_streamlit()
    open_browser_when_ready(f"http://localhost:{STREAMLIT_PORT}")

    print(f"Map server running at http://127.0.0.1:{MAP_PORT}/")
    print(f"Streamlit running at http://localhost:{STREAMLIT_PORT}/")

    try:
        streamlit_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        static_server.shutdown()
        if streamlit_proc.poll() is None:
            streamlit_proc.terminate()


if __name__ == "__main__":
    main()
