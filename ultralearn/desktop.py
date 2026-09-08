"""Native desktop window.

The shell is deliberately thin. It starts the API on a loopback port and opens a
system webview pointed at it, which is all "native app" needs to mean here. The
React frontend is identical whether it runs in this window, a browser tab, or a
Tauri shell later, so swapping the shell never touches the UI.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

import uvicorn

from .api import create_app
from .config import AppConfig


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    """The API running on a background thread."""

    def __init__(self, config: AppConfig, port: int) -> None:
        self.app = create_app(config)
        self.port = port
        self._server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                # Loopback only: study material never leaves the machine.
                access_log=False,
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def token(self) -> str:
        return self.app.state.ultralearn.token

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start(self, timeout: float = 20.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server.started:
                return
            time.sleep(0.05)
        raise RuntimeError("The Ultralearn API did not start in time.")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ultralearn")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open in the default browser instead of a native window.",
    )
    parser.add_argument("--port", type=int, default=0, help="Bind to a specific port.")
    args = parser.parse_args()

    server = Server(AppConfig.from_env(), args.port or free_port())
    server.start()

    if args.browser:
        print(f"Ultralearn is running at {server.url}")
        webbrowser.open(server.url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
        return

    try:
        import webview
    except ImportError:
        print(
            "The desktop window needs pywebview: uv sync --extra desktop\n"
            f"Falling back to the browser: {server.url}"
        )
        webbrowser.open(server.url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
        return

    webview.create_window(
        "Ultralearn",
        server.url,
        width=1180,
        height=840,
        min_size=(880, 640),
        background_color="#0d1117",
    )
    try:
        webview.start()
    finally:
        server.stop()


def serve() -> None:
    """Run only the API, for frontend development against Vite."""

    parser = argparse.ArgumentParser(description="Ultralearn API")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = Server(AppConfig.from_env(), args.port)
    server.start()
    print(f"Ultralearn API on http://127.0.0.1:{args.port}")
    print(f"Token: {server.token}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
