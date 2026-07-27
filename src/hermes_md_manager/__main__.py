"""Single-command entry: ``python -m hermes_md_manager``.

Boots the FastAPI app on 127.0.0.1:<port> and prints the URL with the
per-boot CSRF token. Defaults to port 7788 (override with
``HERMES_MD_PORT``). Binds loopback only — no network exposure.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hermes_md_manager",
        description="Hermes Agent Markdown Manager — local curation instrument",
    )
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("HERMES_MD_PORT", "7788")),
                        help="port to bind on 127.0.0.1 (default: 7788)")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't try to open the browser after start")
    parser.add_argument("--check-only", action="store_true",
                        help="run the source-parity check and exit")
    args = parser.parse_args()

    # Make sure vendor module paths are set up
    from . import hermes_vendor as hv
    state = hv.state()
    if args.check_only:
        if state.read_only:
            print("SOURCE-PARITY CHECK FAILED", file=sys.stderr)
            for r in state.reasons:
                print(f"  - {r}", file=sys.stderr)
            return 2
        print("source-parity check: OK")
        print(f"  resolved {len(state.specs)} vendor symbols from /home/app/.hermes/hermes-agent")
        return 0

    if state.read_only:
        print("SOURCE-PARITY CHECK FAILED — dropping to READ-ONLY mode", file=sys.stderr)
        for r in state.reasons:
            print(f"  - {r}", file=sys.stderr)

    # Lazy import of the app
    from .app import create_app
    app = create_app()

    host = "127.0.0.1"
    print(f"\n  Hermes MD Manager")
    print(f"  ───────────────────")
    print(f"  HERMES_HOME : {os.environ.get('HERMES_HOME', '~/.hermes (default)')}")
    print(f"  state dir   : $XDG_STATE_HOME/hermes-md-manager")
    print(f"  read-only   : {state.read_only}")
    print(f"  binding     : http://{host}:{args.port}/")
    print()

    if not args.no_browser and not state.read_only:
        import threading
        import webbrowser
        def _open():
            time.sleep(0.6)
            webbrowser.open(f"http://{host}:{args.port}/")
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host=host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())