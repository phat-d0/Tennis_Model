"""Alert sinks (console + data/alerts.log) and the data/live/state.json writer.

state.json follows the live-state contract in CLAUDE.md exactly; it is written atomically
(temp file + rename) so the Dashboard never reads a half-written file.
"""

from __future__ import annotations

import json
import os
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .engine import StepResult, iso

MAX_ALERTS = 200


class AlertSink:
    """Prints each alert and appends it to the alert log as one line: `ts [type] message`."""

    def __init__(self, log_path: str | Path | None, stream: TextIO | None = sys.stdout):
        self.log_path = Path(log_path) if log_path else None
        self.stream = stream
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, alerts: list[dict]) -> None:
        if not alerts:
            return
        lines = [f"{a['ts']} [{a['type']}] {a['message']}" for a in alerts]
        if self.stream:
            for line in lines:
                print(line, file=self.stream, flush=True)
        if self.log_path:
            with open(self.log_path, "a") as f:
                f.write("".join(line + "\n" for line in lines))


class StateWriter:
    def __init__(self, path: str | Path, poll_seconds: float, venue: str = "kalshi",
                 extra: dict | None = None):
        self.path = Path(path)
        self.poll_seconds = poll_seconds
        self.venue = venue
        self.extra = dict(extra or {})   # optional top-level keys, e.g. min_arb_profit_per_contract
        self.alerts: deque[dict] = deque(maxlen=MAX_ALERTS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:   # keep alert history across restarts
            old = json.loads(self.path.read_text()).get("alerts") or []
            self.alerts.extend(reversed(old[:MAX_ALERTS]))
        except (OSError, ValueError, AttributeError):
            pass

    def write(self, result: StepResult, now: datetime, paper: dict | None = None) -> dict:
        self.alerts.extend(result.alerts)
        state = {
            "generated_at": iso(now),
            "poll_seconds": self.poll_seconds,
            "venue": self.venue,
            "matches": result.matches,
            "positions": result.positions,
            "alerts": list(reversed(self.alerts)),     # newest first
        }
        state.update(self.extra)
        if paper is not None:
            state["paper"] = paper                     # paper trading summary (docs/scanner_paper.md)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        os.replace(tmp, self.path)
        return state
