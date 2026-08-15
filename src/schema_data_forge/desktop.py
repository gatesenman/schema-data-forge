"""Desktop launcher: serves the web UI locally and opens it in a native window."""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from .web.server import app

DEFAULT_HOST = "127.0.0.1"
WINDOW_TITLE = "Schema Data Forge"


def _say(message: str) -> None:
    """Print without crashing on consoles that cannot encode the message."""
    with contextlib.suppress(OSError, ValueError, UnicodeError):
        print(message)


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0):  # noqa: S310 - localhost only
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.15)
    return False


def _alert(message: str) -> None:
    """Show a native warning dialog when possible."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, WINDOW_TITLE, 0x30)


def _browser_fallback(url: str) -> None:
    webbrowser.open(url)
    _say("Web UI 已在浏览器中打开，按 Ctrl+C 退出…")
    with contextlib.suppress(KeyboardInterrupt):
        while True:
            time.sleep(1.0)


def _open_window(url: str) -> None:
    """Open ``url`` in a native window, falling back to the default browser."""
    try:
        import webview
    except ImportError:
        _browser_fallback(url)
        return

    try:
        webview.create_window(WINDOW_TITLE, url, width=1600, height=1000, min_size=(1120, 720))
        webview.start()
    except Exception:
        if sys.platform == "win32":
            _alert(
                "无法创建桌面窗口，已改用浏览器打开。\n\n"
                "请安装 Microsoft Edge WebView2 Runtime 后重新启动：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/"
            )
        _browser_fallback(url)


def main(argv: list[str] | None = None) -> int:
    """Start the local server and show the UI."""
    parser = argparse.ArgumentParser(prog="schema-data-forge", description=WINDOW_TITLE)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--browser", action="store_true", help="use the default browser")
    args = parser.parse_args(argv)

    port = args.port or _free_port(args.host)
    url = f"http://{args.host}:{port}/"
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if not _wait_until_ready(url):
        _say(f"服务器启动失败：{url}")
        return 1

    _say(f"Schema Data Forge 正在运行：{url}")
    if args.browser:
        webbrowser.open(url)
        with contextlib.suppress(KeyboardInterrupt):
            thread.join()
    else:
        _open_window(url)

    server.should_exit = True
    thread.join(timeout=5.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
