"""
Custom logging handler that captures agent log lines into a thread-safe queue
for real-time WebSocket streaming.
"""

import logging
import re
import queue

# Map [PREFIX] tags to node names
_PREFIX_MAP = {
    "COMMANDER": "commander",
    "SCOUT": "scout",
    "VIBE": "vibe_matcher",
    "COST": "cost_analyst",
    "CRITIC": "critic",
    "SYNTH": "synthesiser",
    "GRAPH": "graph",
}

_PREFIX_RE = re.compile(r"^\[([A-Z]+)\]")
_SEPARATOR_RE = re.compile(r"^[─━═╌╍┄┅]{4,}$")


class WebSocketLogHandler(logging.Handler):
    """Captures formatted log messages and pushes {node, message} dicts to a queue."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            if not msg or _SEPARATOR_RE.match(msg.strip()):
                return
            m = _PREFIX_RE.match(msg)
            if m:
                node = _PREFIX_MAP.get(m.group(1), m.group(1).lower())
            else:
                node = "system"
            self.q.put({"node": node, "message": msg})
        except Exception:
            self.handleError(record)
