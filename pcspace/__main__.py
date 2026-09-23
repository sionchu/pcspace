from __future__ import annotations
import argparse
import json
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import uvicorn
from .web import create_app, default_state


def main():
    parser = argparse.ArgumentParser(description="PCSpace local web server")
    parser.add_argument("--state", type=Path, default=default_state())
    parser.add_argument("--open", action="store_true", help="Open the local automatic-session interface")
    args = parser.parse_args()
    url = "http://127.0.0.1:8768"
    try:
        with urllib.request.urlopen(url + "/health", timeout=1) as response:
            existing = json.load(response)
        if existing.get("app") == "PCSpace":
            if args.open:
                webbrowser.open(url)
            print("PCSpace is already running on 127.0.0.1:8768")
            return
    except Exception:
        pass
    app = create_app(args.state)
    if args.open:
        def open_ready():
            for _ in range(50):
                try:
                    with urllib.request.urlopen(url + "/health", timeout=1):
                        webbrowser.open(url)
                        return
                except Exception:
                    time.sleep(0.2)
        threading.Thread(target=open_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8768, access_log=False, proxy_headers=False, workers=1, limit_concurrency=32)

if __name__ == "__main__":
    main()
