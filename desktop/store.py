from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import CutPoint, M3ProjectError, ProjectSnapshot, Segment


class ProjectStore:
    """Small SQLite project store shared by the UI and a future IPC host."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path, connection: sqlite3.Connection):
        self.path = path
        self.connection = connection

    @classmethod
    def create(cls, path: str | Path) -> "ProjectStore":
        project_path = Path(path).resolve()
        project_path.parent.mkdir(parents=True, exist_ok=True)
        # Analysis may be executed by the bridge worker and then handed to the
        # Electron request thread.  The service serializes writes; allow the
        # hand-off while preserving SQLite's transactional locking.
        connection = sqlite3.connect(project_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS project_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cuts (
                cut_id TEXT PRIMARY KEY,
                boundary_index INTEGER NOT NULL,
                kind TEXT NOT NULL,
                confidence REAL,
                needs_review INTEGER NOT NULL,
                checked INTEGER NOT NULL,
                origin TEXT NOT NULL,
                reason TEXT
            );
            CREATE TABLE IF NOT EXISTS segments (
                clip_id TEXT PRIMARY KEY,
                start_index INTEGER NOT NULL,
                end_index INTEGER NOT NULL,
                audio_enabled INTEGER NOT NULL,
                selected_for_export INTEGER NOT NULL,
                cover_frame_index INTEGER,
                output_number INTEGER NOT NULL,
                name TEXT
            );
            CREATE TABLE IF NOT EXISTS revisions (
                revision INTEGER PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cls._ensure_segment_name_column(connection)
        connection.commit()
        return cls(project_path, connection)

    @staticmethod
    def _ensure_segment_name_column(connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(segments)").fetchall()
        }
        if "name" not in columns:
            connection.execute("ALTER TABLE segments ADD COLUMN name TEXT")

    @classmethod
    def open(cls, path: str | Path) -> "ProjectStore":
        project_path = Path(path).resolve()
        if not project_path.is_file():
            raise M3ProjectError("PROJECT_NOT_FOUND", f"项目文件不存在：{project_path}")
        connection = sqlite3.connect(project_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            keys = connection.execute("SELECT key FROM project_metadata").fetchall()
        except sqlite3.Error as exc:
            connection.close()
            raise M3ProjectError(
                "PROJECT_INVALID", "项目文件不是可识别的 M3 SQLite 项目。"
            ) from exc
        if not keys:
            connection.close()
            raise M3ProjectError("PROJECT_INVALID", "项目缺少 M3 元数据。")
        cls._ensure_segment_name_column(connection)
        connection.commit()
        return cls(project_path, connection)

    def save(self, snapshot: ProjectSnapshot) -> int:
        revision = snapshot.saved_revision + 1
        snapshot.saved_revision = revision
        payload = snapshot.to_dict()
        metadata = {
            "schema_version": snapshot.schema_version,
            "project_id": snapshot.project_id,
            "source_path": snapshot.source_path,
            "source_identity": snapshot.source_identity,
            "probe": snapshot.probe,
            "frame_index_path": snapshot.frame_index_path,
            "frame_count": snapshot.frame_count,
            "detector_status": snapshot.detector_status,
            "detector_version": snapshot.detector_version,
            "color_override": snapshot.color_override,
            "saved_revision": revision,
        }
        with self.connection:
            self.connection.execute("DELETE FROM project_metadata")
            self.connection.executemany(
                "INSERT INTO project_metadata(key,value) VALUES (?,?)",
                [
                    (key, json.dumps(value, ensure_ascii=False, sort_keys=True))
                    for key, value in metadata.items()
                ],
            )
            self.connection.execute("DELETE FROM cuts")
            self.connection.executemany(
                "INSERT INTO cuts(cut_id,boundary_index,kind,confidence,needs_review,checked,origin,reason) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        cut.cut_id,
                        cut.boundary_index,
                        cut.kind,
                        cut.confidence,
                        int(cut.needs_review),
                        int(cut.checked),
                        cut.origin,
                        cut.reason,
                    )
                    for cut in snapshot.cuts
                ],
            )
            self.connection.execute("DELETE FROM segments")
            self.connection.executemany(
                "INSERT INTO segments(clip_id,start_index,end_index,audio_enabled,selected_for_export,cover_frame_index,output_number,name) VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        segment.clip_id,
                        segment.start_index,
                        segment.end_index,
                        int(segment.audio_enabled),
                        int(segment.selected_for_export),
                        segment.cover_frame_index,
                        segment.output_number,
                        segment.name,
                    )
                    for segment in snapshot.segments
                ],
            )
            self.connection.execute(
                "INSERT OR REPLACE INTO revisions(revision,snapshot_json) VALUES (?,?)",
                (revision, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
        return revision

    def load(self) -> ProjectSnapshot:
        rows = self.connection.execute(
            "SELECT key,value FROM project_metadata"
        ).fetchall()
        values = {row["key"]: json.loads(row["value"]) for row in rows}
        if values.get("schema_version") != "m3.desktop.v1":
            raise M3ProjectError(
                "PROJECT_VERSION_UNSUPPORTED",
                "项目版本不是当前 M3 桌面协议。",
                details=values,
            )
        cuts = [
            CutPoint(
                cut_id=row["cut_id"],
                boundary_index=row["boundary_index"],
                kind=row["kind"],
                confidence=row["confidence"],
                needs_review=bool(row["needs_review"]),
                checked=bool(row["checked"]),
                origin=row["origin"],
                reason=row["reason"],
            )
            for row in self.connection.execute(
                "SELECT * FROM cuts ORDER BY boundary_index"
            )
        ]
        segments = [
            Segment(
                clip_id=row["clip_id"],
                start_index=row["start_index"],
                end_index=row["end_index"],
                audio_enabled=bool(row["audio_enabled"]),
                selected_for_export=bool(row["selected_for_export"]),
                cover_frame_index=row["cover_frame_index"],
                output_number=row["output_number"],
                name=row["name"],
            )
            for row in self.connection.execute(
                "SELECT * FROM segments ORDER BY start_index"
            )
        ]
        return ProjectSnapshot(
            project_id=values["project_id"],
            source_path=values["source_path"],
            schema_version=values["schema_version"],
            source_identity=values["source_identity"],
            probe=values["probe"],
            frame_index_path=values["frame_index_path"],
            frame_count=int(values["frame_count"]),
            cuts=cuts,
            segments=segments,
            detector_status=str(values.get("detector_status", "not_connected")),
            detector_version=values.get("detector_version"),
            color_override=values.get("color_override"),
            saved_revision=int(values.get("saved_revision", 0)),
        )

    def close(self) -> None:
        self.connection.close()
