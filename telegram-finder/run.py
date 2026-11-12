#!/usr/bin/env python3
"""Telegram Finder - start the local app:  python3 run.py  [--port 8765] [--no-browser]"""
import argparse
import os
import sys
import threading
import webbrowser

if sys.version_info < (3, 9):
    sys.exit("Python 3.9 or newer is required")

from tgfinder.server import serve

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, [f"http://127.0.0.1:{a.port}"]).start()
    serve(a.data, a.port)
