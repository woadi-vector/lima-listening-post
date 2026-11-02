"""Run Mission Control or generate a local reconciliation briefing."""

import argparse
import json
import os
import threading
import webbrowser
from pathlib import Path

from .server import MissionServer
from .workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description="Lima Mission Control — local preview")
    parser.add_argument("command", choices=("serve", "reconcile", "compare"), nargs="?", default="serve")
    parser.add_argument("--recording", type=Path)
    parser.add_argument("--old-transcript", type=Path)
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--db", type=Path,
                        default=Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) /
                        "LimaListeningPost" / "workspace.sqlite3")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="Open Mission Control when ready")
    parser.add_argument("--as-of", help="Reconciliation date, YYYY-MM-DD; defaults to local date")
    args = parser.parse_args()
    if args.command == 'compare':
        if not args.recording or not args.output:
            parser.error('compare requires --recording and a new --output folder')
        from .recordings import compare_recording
        compare_recording(args.recording, old_report=args.old_transcript, start=args.start,
                          seconds=args.seconds, output=args.output)
        return
    args.db.parent.mkdir(parents=True, exist_ok=True)
    ws = Workspace(args.db)
    try:
        if args.command == "reconcile":
            print(json.dumps(ws.reconcile(as_of=args.as_of), ensure_ascii=False, indent=2))
            return
    finally:
        ws.close()
    server = MissionServer(("127.0.0.1", args.port), args.db)
    print(f"Lima Mission Control: {server.origin}", flush=True)
    print("Local preview. Press Ctrl+C to stop. Notion delivery requires explicit review and confirmation.", flush=True)
    if args.open_browser:
        opener = threading.Timer(0.4, webbrowser.open, args=(server.origin,))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
