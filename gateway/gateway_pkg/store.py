"""SQLite-backed duplicate detection + offline send buffer.

Key properties:
* `is_new(device_id, seq)` — strictly increasing seq per device
  (wraps at 2^32), persisted across gateway restarts.
* Buffer rows are only REMOVED after the backend acknowledges ingestion
  (HTTP 2xx for that packet); temporary network/output failures leave them.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS last_seq (
    device_id INTEGER PRIMARY KEY,
    max_seq   INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS buffer (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    seq       INTEGER NOT NULL,
    payload   TEXT NOT NULL,
    attempts  INTEGER NOT NULL DEFAULT 0,
    queued_at REAL NOT NULL,
    UNIQUE(device_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_buffer_queued ON buffer(queued_at);
"""


class GatewayStore:
    def __init__(self, path: str) -> None:
        expanded = str(Path(os.path.expanduser(path)))
        Path(expanded).parent.mkdir(parents=True, exist_ok=True)
        self._path = expanded
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(expanded, check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- dedup ----
    def is_new(self, device_id: int, seq: int) -> bool:
        """True when seq is newer than anything seen for the device.

        Ring/window arithmetic on uint32 seq space:
        * identical seq or a backward jump within half the ring → duplicate/replay
        * forward jump or backward jump beyond half the ring (32-bit wrap) → new
        Persisted across gateway restarts in the `last_seq` table.
        """
        with self._lock:
            seq &= 0xFFFFFFFF
            row = self._conn.execute(
                "SELECT max_seq FROM last_seq WHERE device_id = ?", (device_id,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO last_seq(device_id, max_seq, updated_at) VALUES (?,?,?)",
                    (device_id, seq, time.time()),
                )
                self._conn.commit()
                return True
            max_seq = int(row[0]) & 0xFFFFFFFF
            behind = (max_seq - seq) & 0xFFFFFFFF
            if behind == 0 or behind < 0x80000000:
                return False  # duplicate or replayed stale sequence
            self._conn.execute(
                "UPDATE last_seq SET max_seq = ?, updated_at = ? WHERE device_id = ?",
                (seq, time.time(), device_id),
            )
            self._conn.commit()
            return True

    # ---- buffer ----
    def enqueue(self, device_id: int, seq: int, payload: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO buffer(device_id, seq, payload, attempts, queued_at) VALUES (?,?,?,0,?)",
                (device_id, seq, json.dumps(payload), time.time()),
            )
            self._conn.commit()

    def peek(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, device_id, seq, payload, attempts FROM buffer ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()
        return rows

    def mark_attempt(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE buffer SET attempts = attempts + 1 WHERE id = ?", (row_id,)
            )
            self._conn.commit()

    def remove(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM buffer WHERE id = ?", (row_id,))
            self._conn.commit()

    def buffered_count(self) -> int:
        with self._lock:
            (n,) = self._conn.execute("SELECT COUNT(*) FROM buffer").fetchone()
        return int(n)

    def diagnostic_snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = self._conn.execute(
                "SELECT COUNT(*) c, MIN(queued_at) oldest FROM buffer"
            ).fetchone()
            devices = self._conn.execute("SELECT COUNT(*) FROM last_seq").fetchone()
        return {
            "buffered": counts[0],
            "oldest_queued_at": counts[1],
            "tracked_devices": devices[0],
            "path": self._path,
        }
