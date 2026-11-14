from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from core.protocol.media import CACHE_SCHEMA_VERSION, FrameRef, Rational, SourceIdentity


def cache_key(source: SourceIdentity, toolchain: dict[str, object], mode: str) -> str:
    source_payload = asdict(source)
    source_payload.pop("captured_at_utc", None)
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "mode": mode,
        "source": source_payload,
        "toolchain": toolchain,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]


class FrameIndexCache:
    def __init__(self, path: Path, connection: sqlite3.Connection) -> None:
        self.path = path
        self.connection = connection

    @classmethod
    def create(
        cls,
        root: str | Path,
        source: SourceIdentity,
        toolchain: dict[str, object],
        *,
        mode: str,
        time_base: Rational,
        stream_index: int,
    ) -> "FrameIndexCache":
        root_path = Path(root).resolve()
        root_path.mkdir(parents=True, exist_ok=True)
        key = cache_key(source, toolchain, mode)
        path = root_path / f"index-{key}.sqlite3"
        if path.exists():
            with sqlite3.connect(path) as existing:
                status = existing.execute(
                    "SELECT value FROM metadata WHERE key='status'"
                ).fetchone()
            if status and status[0] == "complete":
                connection = sqlite3.connect(path)
                return cls(path, connection)
            path = root_path / f"index-{key}-{uuid.uuid4().hex}.sqlite3"
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE frames (
                display_index INTEGER PRIMARY KEY,
                stream_index INTEGER NOT NULL,
                pts INTEGER,
                best_effort_pts INTEGER,
                time_base_num INTEGER NOT NULL,
                time_base_den INTEGER NOT NULL,
                duration INTEGER,
                duration_source TEXT NOT NULL,
                keyframe INTEGER,
                pict_type TEXT,
                dts INTEGER,
                packet_pos INTEGER
            );
            CREATE INDEX frames_pts_idx ON frames(pts);
            """
        )
        metadata = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "status": "incomplete",
            "source_identity": json.dumps(
                asdict(source), sort_keys=True, ensure_ascii=False
            ),
            "toolchain": json.dumps(toolchain, sort_keys=True, ensure_ascii=False),
            "mode": mode,
            "stream_index": stream_index,
            "time_base": json.dumps(asdict(time_base)),
        }
        connection.executemany(
            "INSERT INTO metadata(key,value) VALUES (?,?)", metadata.items()
        )
        connection.commit()
        return cls(path, connection)

    def status(self) -> str:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='status'"
        ).fetchone()
        return row[0] if row else "unknown"

    def insert_frames(self, frames: Iterable[FrameRef]) -> None:
        rows = []
        for frame in frames:
            rows.append(
                (
                    frame.display_index,
                    frame.stream_index,
                    frame.pts,
                    frame.best_effort_pts,
                    frame.time_base.num,
                    frame.time_base.den,
                    frame.duration,
                    frame.duration_source,
                    None if frame.keyframe is None else int(frame.keyframe),
                    frame.pict_type,
                    frame.dts,
                    frame.packet_pos,
                )
            )
        if rows:
            self.connection.executemany(
                """
                INSERT INTO frames(
                    display_index,stream_index,pts,best_effort_pts,time_base_num,time_base_den,
                    duration,duration_source,keyframe,pict_type,dts,packet_pos
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            self.connection.commit()

    def set_metadata(self, key: str, value: object) -> None:
        encoded = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
        self.connection.execute(
            "INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, encoded),
        )
        self.connection.commit()

    def finalize(
        self, frame_count: int, first_pts: int | None, last_pts: int | None
    ) -> None:
        self.set_metadata("status", "complete")
        self.set_metadata("frame_count", frame_count)
        self.set_metadata("first_pts", first_pts)
        self.set_metadata("last_pts", last_pts)

    def mark_incomplete(self, reason: str) -> None:
        self.set_metadata("status", "incomplete")
        self.set_metadata("incomplete_reason", reason)

    def close(self) -> None:
        self.connection.close()
