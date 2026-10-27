"""python -m swinglock.dashboard --state data/live/state.json [--lookback FILE] [--host 127.0.0.1] [--port 8000]"""

from __future__ import annotations

import argparse

from .server import SAMPLE_LOOKBACK, SAMPLE_STATE, default_lookback, make_server


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m swinglock.dashboard",
                                 description="Read-only live dashboard for the scanner's state.json")
    ap.add_argument("--state", default="data/live/state.json",
                    help="state file written by the scanner (default: data/live/state.json)")
    ap.add_argument("--lookback", default=None,
                    help="paper-trading lookback (default: <state dir>/../paper/lookback.json)")
    ap.add_argument("--sample", action="store_true", help=f"serve the bundled sample ({SAMPLE_STATE.name})")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1; use 0.0.0.0 only behind a firewall/VPN)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    state = SAMPLE_STATE if args.sample else args.state
    lookback = SAMPLE_LOOKBACK if args.sample else (args.lookback or default_lookback(state))
    httpd = make_server(state, args.host, args.port, lookback)
    host, port = httpd.server_address[:2]
    print(f"Dashboard on http://{host}:{port}/  (state: {state}, lookback: {lookback})  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
