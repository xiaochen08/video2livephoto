from __future__ import annotations

import base64
import copy
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from core.analysis.shot_detection import detect_shots
from core.media.frame_index import build_frame_index
from core.media.color import color_override_metadata
from core.media.process import CancellationToken, kill_process
from core.media.probe import probe_media
from core.media.source_identity import capture_identity, identities_match
from core.media.toolchain import Toolchain, process_creation_flags

from .models import (
    AudioConflictError,
    CutPoint,
    M3ProjectError,
    M3_PROTOCOL_VERSION,
    ProjectSnapshot,
    Segment,
    TimelineFrame,
)
from .store import ProjectStore


DetectionProvider = Callable[[str, dict[str, Any], str], dict[str, Any]]
_UNSET = object()


class M3ProjectService:
    """M3 project/timeline service used by Electron IPC and Python tests.

    It deliberately owns no encoder.  ``confirm_export`` returns an immutable
    snapshot for M4 and does not touch the source file or start an export.
    """

    def __init__(
        self,
        snapshot: ProjectSnapshot,
        store: ProjectStore,
        *,
        toolchain: Toolchain | None = None,
    ):
        self.snapshot = snapshot
        self.store = store
        self.toolchain = toolchain or Toolchain.discover()
        self._undo: list[ProjectSnapshot] = []
        self._redo: list[ProjectSnapshot] = []

    @classmethod
    def import_media(
        cls,
        source_path: str | Path,
        *,
        project_path: str | Path,
        cache_root: str | Path | None = None,
        toolchain: Toolchain | None = None,
        detector: DetectionProvider | None = None,
        token: CancellationToken | None = None,
        timeout_seconds: float = 3600.0,
        video_stream_index: int | None = None,
        color_override: str | None = None,
        progress_callback: Callable[[str, int, int | None], None] | None = None,
    ) -> "M3ProjectService":
        source = Path(source_path).resolve(strict=True)
        project = Path(project_path).resolve()
        if color_override is not None and color_override_metadata(color_override) is None:
            raise M3ProjectError(
                "INVALID_COLOR_OVERRIDE",
                "导入时选择的色彩类型不受支持。",
                details={"color_override": color_override},
            )
        if cache_root is None:
            cache_root = project.parent / f".{project.stem}.m1-cache"
        selected_toolchain = toolchain or Toolchain.discover()
        token = token or CancellationToken()
        probe = probe_media(
            source,
            toolchain=selected_toolchain,
            token=token,
            timeout_seconds=min(timeout_seconds, 120.0),
            selected_video_stream=video_stream_index,
        )
        if progress_callback is not None:
            progress_callback("probe", 1, 1)
        index = build_frame_index(
            source,
            cache_root=cache_root,
            toolchain=selected_toolchain,
            token=token,
            timeout_seconds=timeout_seconds,
            selected_video_stream=video_stream_index,
            probe_result=probe,
            progress_callback=(
                (lambda done, total: progress_callback("frame_index", done, total))
                if progress_callback is not None
                else None
            ),
        )
        if not index.index_path or index.status != "complete":
            raise M3ProjectError(
                "FRAME_INDEX_INCOMPLETE", "媒体帧索引未完成，无法进入编辑。"
            )
        probe_dict = probe.to_dict()
        cuts: list[CutPoint] = []
        detector_status = "not_connected"
        detector_version: str | None = None
        if detector is not None:
            result = detector(str(source), probe_dict, index.index_path)
            detector_status = str(result.get("status", "connected"))
            detector_version = result.get("version")
            detected_cuts = result.get("cuts", [])
            if progress_callback is not None:
                progress_callback("shot_detect", 1, 1)
        else:
            detection = detect_shots(
                source,
                frame_index_report=index,
                toolchain=selected_toolchain,
                token=token,
                timeout_seconds=timeout_seconds,
                progress_callback=(
                    (lambda done, total: progress_callback("shot_detect", done, total))
                    if progress_callback is not None
                    else None
                ),
            )
            detector_status = detection.status
            detector_version = detection.schema_version
            detected_cuts = [
                {
                    "cut_id": candidate.candidate_id,
                    "boundary_index": candidate.frame_index,
                    "kind": candidate.kind,
                    "confidence": candidate.confidence,
                    "needs_review": candidate.review_required,
                    "checked": not candidate.review_required,
                    "origin": "detector",
                    "reason": candidate.reason,
                }
                for candidate in detection.candidates
            ]
        seen_boundaries: set[int] = set()
        for item in detected_cuts:
            boundary = int(item["boundary_index"])
            if not 0 < boundary < index.frame_count or boundary in seen_boundaries:
                continue
            seen_boundaries.add(boundary)
            cuts.append(
                CutPoint(
                    cut_id=str(item.get("cut_id") or uuid.uuid4()),
                    boundary_index=boundary,
                    kind=str(item.get("kind", "detected")),
                    confidence=item.get("confidence"),
                    needs_review=bool(item.get("needs_review", False)),
                    checked=bool(item.get("checked", False)),
                    origin=str(item.get("origin", "detector")),
                    reason=item.get("reason"),
                )
            )
        cuts.sort(key=lambda item: item.boundary_index)
        snapshot = ProjectSnapshot(
            project_id=str(uuid.uuid4()),
            source_path=str(source),
            schema_version=M3_PROTOCOL_VERSION,
            source_identity=_asdict_identity(probe.source_identity),
            probe=probe_dict,
            frame_index_path=index.index_path,
            frame_count=index.frame_count,
            cuts=cuts,
            segments=_segments_from_cuts(index.frame_count, cuts),
            detector_status=detector_status,
            detector_version=detector_version,
            color_override=color_override,
        )
        store = ProjectStore.create(project)
        store.save(snapshot)
        return cls(snapshot, store, toolchain=selected_toolchain)

    @classmethod
    def open_project(
        cls, project_path: str | Path, *, verify_source: bool = True
    ) -> "M3ProjectService":
        store = ProjectStore.open(project_path)
        snapshot = store.load()
        if verify_source:
            current = capture_identity(snapshot.source_path)
            stored = _identity_from_dict(snapshot.source_identity)
            if not identities_match(stored, current):
                store.close()
                raise M3ProjectError(
                    "SOURCE_CHANGED",
                    "源文件身份已变化，项目保持打开但必须重新探测后才能继续。",
                    details={"source_path": snapshot.source_path},
                )
        return cls(snapshot, store)

    def close(self) -> None:
        self.store.close()

    def to_dict(self) -> dict[str, Any]:
        result = self.snapshot.to_dict()
        result["pending_review_count"] = len(self.pending_reviews())
        result["can_export"] = self.can_export()
        return result

    def frame_at(self, display_index: int) -> TimelineFrame:
        if display_index < 0 or display_index >= self.snapshot.frame_count:
            raise M3ProjectError(
                "FRAME_OUT_OF_RANGE",
                "帧索引超出范围。",
                details={"display_index": display_index},
            )
        with sqlite3.connect(self.snapshot.frame_index_path) as db:
            row = db.execute(
                "SELECT display_index,pts,best_effort_pts,duration,time_base_num,time_base_den,pict_type,keyframe "
                "FROM frames WHERE display_index=?",
                (display_index,),
            ).fetchone()
        if row is None:
            raise M3ProjectError(
                "FRAME_NOT_FOUND",
                "缓存中找不到该显示帧。",
                details={"display_index": display_index},
            )
        return TimelineFrame(
            display_index=int(row[0]),
            pts=row[1],
            best_effort_pts=row[2],
            duration=row[3],
            time_base_num=int(row[4]),
            time_base_den=int(row[5]),
            pict_type=row[6],
            keyframe=None if row[7] is None else bool(row[7]),
        )

    def frame_window(self, center_index: int, radius: int = 3) -> list[TimelineFrame]:
        start = max(0, center_index - max(0, radius))
        end = min(self.snapshot.frame_count, center_index + max(0, radius) + 1)
        return [self.frame_at(index) for index in range(start, end)]

    def preview_frame(
        self,
        display_index: int,
        *,
        width: int = 640,
        token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Decode one bounded preview JPEG without loading the source into Python."""
        token = token or CancellationToken()
        if token.cancelled:
            raise M3ProjectError("CANCELLED", "帧预览已取消。")
        frame = self.frame_at(display_index)
        timestamp = (
            frame.best_effort_pts if frame.best_effort_pts is not None else frame.pts
        )
        if timestamp is None:
            raise M3ProjectError(
                "FRAME_TIMESTAMP_UNAVAILABLE", "当前帧缺少可用时间戳。"
            )
        width = max(160, min(int(width), 1280))
        selected_stream = int((self.snapshot.probe or {}).get("selected_video_stream", 0))
        time_base_num = int(frame.time_base_num or 0)
        time_base_den = int(frame.time_base_den or 1)
        seek_seconds = max(0.0, float(timestamp * time_base_num / time_base_den))
        seek_text = f"{seek_seconds:.12f}".rstrip("0").rstrip(".") or "0"
        process = subprocess.Popen(
            [
                self.toolchain.ffmpeg.path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                # Seek to the nearest keyframe before the target, then keep
                # the exact PTS filter below.  This avoids decoding the whole
                # source from frame zero while preserving frame identity.
                "-ss",
                seek_text,
                "-copyts",
                "-i",
                self.snapshot.source_path,
                "-map",
                f"0:{selected_stream}",
                "-an",
                "-sn",
                "-dn",
                "-frames:v",
                "1",
                "-vf",
                f"select='eq(pts\\,{timestamp})',scale={width}:-2",
                "-vsync",
                "0",
                "-q:v",
                "3",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=process_creation_flags(),
        )
        result: dict[str, bytes] = {}
        errors: list[BaseException] = []

        def _communicate() -> None:
            try:
                stdout, stderr = process.communicate()
                result["stdout"] = stdout
                result["stderr"] = stderr
            except BaseException as exc:  # propagate reader failures to caller
                errors.append(exc)

        reader = threading.Thread(
            target=_communicate, name="m3-preview-communicate", daemon=True
        )
        reader.start()
        started = time.monotonic()
        while reader.is_alive():
            if token.cancelled:
                kill_process(process)
                reader.join(timeout=2)
                raise M3ProjectError("CANCELLED", "帧预览已取消。")
            if time.monotonic() - started > 30:
                kill_process(process)
                reader.join(timeout=2)
                raise M3ProjectError("PREVIEW_TIMEOUT", "当前帧预览解码超时。")
            reader.join(timeout=0.05)
        reader.join(timeout=1)
        if errors:
            raise M3ProjectError(
                "PREVIEW_DECODE_FAILED", "当前帧预览解码失败。"
            ) from errors[0]
        if token.cancelled:
            raise M3ProjectError("CANCELLED", "帧预览已取消。")
        stdout = result.get("stdout", b"")
        stderr = result.get("stderr", b"")
        if process.returncode != 0 or not stdout:
            raise M3ProjectError(
                "PREVIEW_DECODE_FAILED",
                "当前帧预览解码失败。",
                details={
                    "stderr": stderr.decode("utf-8", errors="replace")[-1000:]
                },
            )
        if len(stdout) > 8 * 1024 * 1024:
            raise M3ProjectError("PREVIEW_TOO_LARGE", "预览帧超过内存上限。")
        return {
            "display_index": display_index,
            "pts": timestamp,
            "mime": "image/jpeg",
            "data_uri": "data:image/jpeg;base64,"
            + base64.b64encode(stdout).decode("ascii"),
        }

    def pending_reviews(self) -> list[CutPoint]:
        return [
            cut for cut in self.snapshot.cuts if cut.needs_review and not cut.checked
        ]

    def can_export(self) -> bool:
        """True when no extra user review confirmation is required."""
        return not self.pending_reviews()

    def mark_cut_checked(self, cut_id: str, checked: bool = True) -> ProjectSnapshot:
        def mutate() -> None:
            cut = self._cut(cut_id)
            cut.checked = checked

        return self._change(mutate)

    def split_segment(
        self, clip_id: str, boundary_index: int, *, kind: str = "manual"
    ) -> ProjectSnapshot:
        def mutate() -> None:
            segment = self._segment(clip_id)
            if (
                boundary_index <= segment.start_index
                or boundary_index >= segment.end_index
            ):
                raise M3ProjectError(
                    "INVALID_CUT", "切点必须位于片段内部，且不能造成空片段。"
                )
            self.snapshot.cuts.append(
                CutPoint(
                    cut_id=str(uuid.uuid4()),
                    boundary_index=boundary_index,
                    kind=kind,
                    needs_review=False,
                    checked=True,
                    origin="manual",
                )
            )
            self._rebuild_segments()

        return self._change(mutate)

    def add_cut(
        self,
        boundary_index: int,
        *,
        kind: str = "manual",
        needs_review: bool = True,
        reason: str | None = None,
    ) -> ProjectSnapshot:
        def mutate() -> None:
            if boundary_index <= 0 or boundary_index >= self.snapshot.frame_count:
                raise M3ProjectError("INVALID_CUT", "切点必须位于首尾帧之间。")
            if any(cut.boundary_index == boundary_index for cut in self.snapshot.cuts):
                raise M3ProjectError("DUPLICATE_CUT", "该帧边界已经存在切点。")
            self.snapshot.cuts.append(
                CutPoint(
                    cut_id=str(uuid.uuid4()),
                    boundary_index=boundary_index,
                    kind=kind,
                    needs_review=needs_review,
                    checked=not needs_review,
                    origin="manual",
                    reason=reason,
                )
            )
            self._rebuild_segments()

        return self._change(mutate)

    def delete_cut(self, cut_id: str) -> ProjectSnapshot:
        def mutate() -> None:
            self._cut(cut_id)
            self.snapshot.cuts = [
                cut for cut in self.snapshot.cuts if cut.cut_id != cut_id
            ]
            self._rebuild_segments()

        return self._change(mutate)

    def move_cut(self, cut_id: str, boundary_index: int) -> ProjectSnapshot:
        def mutate() -> None:
            cut = self._cut(cut_id)
            old = cut.boundary_index
            if boundary_index <= 0 or boundary_index >= self.snapshot.frame_count:
                raise M3ProjectError("INVALID_CUT", "切点必须位于首尾帧之间。")
            other = sorted(
                item.boundary_index
                for item in self.snapshot.cuts
                if item.cut_id != cut_id
            )
            lower = max([0, *[value for value in other if value < old]])
            upper = min(
                [self.snapshot.frame_count, *[value for value in other if value > old]]
            )
            if not lower < boundary_index < upper:
                raise M3ProjectError("CUT_OVERLAP", "切点移动后会造成重叠或空片段。")
            cut.boundary_index = boundary_index
            cut.origin = "manual"
            cut.kind = "manual"
            cut.needs_review = False
            cut.checked = True
            self._rebuild_segments()

        return self._change(mutate)

    def set_segment_bounds(
        self, clip_id: str, start_index: int, end_index: int
    ) -> ProjectSnapshot:
        """Move both boundaries of one segment in a single revision.

        This is used by slide/reset gestures so a multi-boundary edit is
        validated, persisted, and undoable as one transaction.
        """

        def mutate() -> None:
            segments = sorted(self.snapshot.segments, key=lambda item: item.start_index)
            try:
                position = next(i for i, item in enumerate(segments) if item.clip_id == clip_id)
            except StopIteration as exc:
                raise M3ProjectError("SEGMENT_NOT_FOUND", "找不到要调整的片段。") from exc
            segment = segments[position]
            start = int(start_index)
            end = int(end_index)
            if end <= start:
                raise M3ProjectError("INVALID_FRAME_RANGE", "片段范围必须至少包含一帧。")
            if start < 0 or end > self.snapshot.frame_count:
                raise M3ProjectError("INVALID_FRAME_RANGE", "片段范围超出视频帧范围。")
            if position == 0:
                if start != 0:
                    raise M3ProjectError("CUT_OVERLAP", "第一个片段必须从视频开头开始。")
            elif start <= segments[position - 1].start_index or start >= end:
                raise M3ProjectError("CUT_OVERLAP", "开头边界会造成空片段或重叠。")
            if position == len(segments) - 1:
                if end != self.snapshot.frame_count:
                    raise M3ProjectError("CUT_OVERLAP", "最后一个片段必须延伸到视频结尾。")
            elif end <= start or end >= segments[position + 1].end_index:
                raise M3ProjectError("CUT_OVERLAP", "结尾边界会造成空片段或重叠。")

            left_cut = next((cut for cut in self.snapshot.cuts if cut.boundary_index == segment.start_index), None)
            right_cut = next((cut for cut in self.snapshot.cuts if cut.boundary_index == segment.end_index), None)
            if position > 0 and left_cut is None:
                raise M3ProjectError("CUT_NOT_FOUND", "找不到片段的开头切点。")
            if position < len(segments) - 1 and right_cut is None:
                raise M3ProjectError("CUT_NOT_FOUND", "找不到片段的结尾切点。")

            if left_cut is not None:
                left_cut.boundary_index = start
                left_cut.origin = "manual"
                left_cut.kind = "manual"
                left_cut.needs_review = False
                left_cut.checked = True
            if right_cut is not None:
                right_cut.boundary_index = end
                right_cut.origin = "manual"
                right_cut.kind = "manual"
                right_cut.needs_review = False
                right_cut.checked = True

            if position > 0:
                segments[position - 1].end_index = start
            segment.start_index = start
            segment.end_index = end
            if position < len(segments) - 1:
                segments[position + 1].start_index = end
            self.snapshot.segments = segments

        return self._change(mutate)

    def merge_segments(
        self,
        left_clip_id: str,
        right_clip_id: str,
        *,
        audio_enabled: bool | None = None,
    ) -> ProjectSnapshot:
        def mutate() -> None:
            segments = sorted(self.snapshot.segments, key=lambda item: item.start_index)
            try:
                left_pos = next(
                    index
                    for index, item in enumerate(segments)
                    if item.clip_id == left_clip_id
                )
                right_pos = next(
                    index
                    for index, item in enumerate(segments)
                    if item.clip_id == right_clip_id
                )
            except StopIteration as exc:
                raise M3ProjectError(
                    "SEGMENT_NOT_FOUND", "找不到要合并的片段。"
                ) from exc
            if (
                right_pos != left_pos + 1
                or segments[left_pos].end_index != segments[right_pos].start_index
            ):
                raise M3ProjectError(
                    "SEGMENTS_NOT_ADJACENT", "只能合并相邻且连续的片段。"
                )
            left, right = segments[left_pos], segments[right_pos]
            if left.audio_enabled != right.audio_enabled and audio_enabled is None:
                raise AudioConflictError(left.audio_enabled, right.audio_enabled)
            chosen_audio = (
                left.audio_enabled if audio_enabled is None else bool(audio_enabled)
            )
            merged = Segment(
                clip_id=left.clip_id,
                start_index=left.start_index,
                end_index=right.end_index,
                audio_enabled=chosen_audio,
                selected_for_export=left.selected_for_export
                or right.selected_for_export,
                cover_frame_index=left.cover_frame_index,
                output_number=left.output_number,
                name=left.name,
            )
            self.snapshot.segments = (
                segments[:left_pos] + [merged] + segments[right_pos + 1 :]
            )
            self.snapshot.cuts = [
                cut
                for cut in self.snapshot.cuts
                if cut.boundary_index != left.end_index
            ]

        return self._change(mutate)

    def set_segment_audio(self, clip_id: str, enabled: bool) -> ProjectSnapshot:
        def mutate() -> None:
            self._segment(clip_id).audio_enabled = bool(enabled)

        return self._change(mutate)

    def set_segment_export(self, clip_id: str, selected: bool) -> ProjectSnapshot:
        def mutate() -> None:
            self._segment(clip_id).selected_for_export = bool(selected)

        return self._change(mutate)

    def set_segment_cover(self, clip_id: str, frame_index: int | None) -> ProjectSnapshot:
        def mutate() -> None:
            segment = self._segment(clip_id)
            if frame_index is not None and not segment.start_index <= int(frame_index) < segment.end_index:
                raise M3ProjectError(
                    "COVER_OUT_OF_RANGE",
                    "封面帧必须位于当前片段范围内。",
                    details={"clip_id": clip_id, "frame": int(frame_index)},
                )
            segment.cover_frame_index = None if frame_index is None else int(frame_index)

        return self._change(mutate)

    def set_segment_properties_many(
        self,
        clip_ids: Iterable[str],
        *,
        audio_enabled: bool | None = None,
        selected_for_export: bool | None = None,
        name: str | None | object = _UNSET,
    ) -> ProjectSnapshot:
        ids = [str(item) for item in clip_ids]

        def mutate() -> None:
            for clip_id in ids:
                segment = self._segment(clip_id)
                if audio_enabled is not None:
                    segment.audio_enabled = bool(audio_enabled)
                if selected_for_export is not None:
                    segment.selected_for_export = bool(selected_for_export)
                if name is not _UNSET:
                    value = str(name).strip() if name is not None else ""
                    segment.name = value or None

        return self._change(mutate)

    def merge_segments_many(
        self, clip_ids: Iterable[str], *, audio_enabled: bool | None = None
    ) -> ProjectSnapshot:
        ids = [str(item) for item in clip_ids]
        if len(ids) < 2:
            raise M3ProjectError("MERGE_NOT_CONTIGUOUS", "至少需要两个相邻片段。")

        def mutate() -> None:
            segments = sorted(self.snapshot.segments, key=lambda item: item.start_index)
            positions = [next((i for i, item in enumerate(segments) if item.clip_id == clip_id), -1) for clip_id in ids]
            if any(value < 0 for value in positions) or positions != list(range(positions[0], positions[0] + len(positions))):
                raise M3ProjectError("MERGE_NOT_CONTIGUOUS", "只能合并相邻且连续的片段。")
            selected = [segments[index] for index in positions]
            for left, right in zip(selected, selected[1:]):
                if left.end_index != right.start_index:
                    raise M3ProjectError("MERGE_NOT_CONTIGUOUS", "片段范围不连续。")
            if audio_enabled is None and any(item.audio_enabled != selected[0].audio_enabled for item in selected[1:]):
                raise AudioConflictError(selected[0].audio_enabled, selected[1].audio_enabled)
            chosen_audio = selected[0].audio_enabled if audio_enabled is None else bool(audio_enabled)
            merged = Segment(
                clip_id=selected[0].clip_id,
                start_index=selected[0].start_index,
                end_index=selected[-1].end_index,
                audio_enabled=chosen_audio,
                selected_for_export=any(item.selected_for_export for item in selected),
                cover_frame_index=selected[0].cover_frame_index,
                output_number=selected[0].output_number,
                name=selected[0].name,
            )
            self.snapshot.segments = segments[: positions[0]] + [merged] + segments[positions[-1] + 1 :]
            removed_boundaries = {item.end_index for item in selected[:-1]}
            self.snapshot.cuts = [cut for cut in self.snapshot.cuts if cut.boundary_index not in removed_boundaries]

        return self._change(mutate)

    def set_all_audio(self, enabled: bool) -> ProjectSnapshot:
        def mutate() -> None:
            for segment in self.snapshot.segments:
                segment.audio_enabled = bool(enabled)

        return self._change(mutate)

    def confirm_export(self, *, allow_unreviewed: bool = False) -> dict[str, Any]:
        pending = self.pending_reviews()
        if pending and not allow_unreviewed:
            raise M3ProjectError(
                "PENDING_REVIEW",
                "仍有未人工检查的切点，请返回检查或明确确认后继续。",
                details={"cut_ids": [cut.cut_id for cut in pending]},
            )
        return {
            "protocol": M3_PROTOCOL_VERSION,
            "type": "export_confirmation_snapshot",
            "project": copy.deepcopy(self.snapshot.to_dict()),
            "pending_review_count": len(pending),
            "confirmed_by_user": True,
            "encoder": "M4_M5_QUEUE_PIPELINE",
        }

    def undo(self) -> ProjectSnapshot:
        if not self._undo:
            raise M3ProjectError("UNDO_EMPTY", "没有可撤销的编辑。")
        current_revision = self.snapshot.saved_revision
        self._redo.append(copy.deepcopy(self.snapshot))
        self.snapshot = self._undo.pop()
        # History restores content, but the persisted edit version is a new
        # event.  Keeping it monotonic prevents the renderer from discarding
        # the undo result as stale.
        self.snapshot.saved_revision = current_revision
        self.store.save(self.snapshot)
        return self.snapshot

    def redo(self) -> ProjectSnapshot:
        if not self._redo:
            raise M3ProjectError("REDO_EMPTY", "没有可重做的编辑。")
        current_revision = self.snapshot.saved_revision
        self._undo.append(copy.deepcopy(self.snapshot))
        self.snapshot = self._redo.pop()
        self.snapshot.saved_revision = current_revision
        self.store.save(self.snapshot)
        return self.snapshot

    def _change(self, mutate: Callable[[], None]) -> ProjectSnapshot:
        before = copy.deepcopy(self.snapshot)
        try:
            mutate()
            self._validate()
            self.store.save(self.snapshot)
        except Exception:
            self.snapshot = before
            raise
        self._undo.append(before)
        self._redo.clear()
        return self.snapshot

    def _cut(self, cut_id: str) -> CutPoint:
        for cut in self.snapshot.cuts:
            if cut.cut_id == cut_id:
                return cut
        raise M3ProjectError(
            "CUT_NOT_FOUND", "找不到切点。", details={"cut_id": cut_id}
        )

    def _segment(self, clip_id: str) -> Segment:
        for segment in self.snapshot.segments:
            if segment.clip_id == clip_id:
                return segment
        raise M3ProjectError(
            "SEGMENT_NOT_FOUND", "找不到片段。", details={"clip_id": clip_id}
        )

    def _rebuild_segments(self) -> None:
        previous = {
            (item.start_index, item.end_index): item for item in self.snapshot.segments
        }
        boundaries = (
            [0]
            + sorted({cut.boundary_index for cut in self.snapshot.cuts})
            + [self.snapshot.frame_count]
        )
        rebuilt: list[Segment] = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
            old = previous.get((start, end))
            if old is None:
                owners = [
                    item
                    for item in self.snapshot.segments
                    if item.start_index <= start and item.end_index >= end
                ]
                old = owners[0] if owners else None
            rebuilt.append(
                Segment(
                    clip_id=(
                        old.clip_id
                        if old is not None
                        and (start, end) == (old.start_index, old.end_index)
                        else str(uuid.uuid4())
                    ),
                    start_index=start,
                    end_index=end,
                    audio_enabled=old.audio_enabled if old is not None else True,
                    selected_for_export=old.selected_for_export
                    if old is not None
                    else True,
                    cover_frame_index=old.cover_frame_index
                    if old is not None
                    else None,
                    output_number=index,
                    name=old.name if old is not None else None,
                )
            )
        self.snapshot.segments = rebuilt

    def _validate(self) -> None:
        cuts = sorted(self.snapshot.cuts, key=lambda item: item.boundary_index)
        if any(
            cut.boundary_index <= 0 or cut.boundary_index >= self.snapshot.frame_count
            for cut in cuts
        ):
            raise M3ProjectError("INVALID_CUT", "切点超出帧范围。")
        segments = sorted(self.snapshot.segments, key=lambda item: item.start_index)
        expected = 0
        for segment in segments:
            if (
                segment.start_index != expected
                or segment.end_index <= segment.start_index
            ):
                raise M3ProjectError(
                    "TIMELINE_NOT_CONTIGUOUS", "片段范围必须连续、无重叠且无漏帧。"
                )
            expected = segment.end_index
        if expected != self.snapshot.frame_count:
            raise M3ProjectError(
                "TIMELINE_NOT_CONTIGUOUS", "片段未覆盖完整显示帧范围。"
            )


def _segments_from_cuts(frame_count: int, cuts: Iterable[CutPoint]) -> list[Segment]:
    boundaries = [0] + sorted({cut.boundary_index for cut in cuts}) + [frame_count]
    return [
        Segment(str(uuid.uuid4()), start, end, output_number=index)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1)
    ]


def _asdict_identity(identity: Any) -> dict[str, Any]:
    return {
        "canonical_path": identity.canonical_path,
        "physical_file_id": identity.physical_file_id,
        "size": identity.size,
        "mtime_ns": identity.mtime_ns,
        "sampled_fingerprint": identity.sampled_fingerprint,
        "full_sha256": identity.full_sha256,
        "captured_at_utc": identity.captured_at_utc,
    }


def _identity_from_dict(payload: dict[str, Any]) -> Any:
    from core.protocol.media import SourceIdentity

    return SourceIdentity(
        canonical_path=str(payload["canonical_path"]),
        physical_file_id=payload.get("physical_file_id"),
        size=int(payload["size"]),
        mtime_ns=int(payload["mtime_ns"]),
        sampled_fingerprint=str(payload["sampled_fingerprint"]),
        full_sha256=payload.get("full_sha256"),
        captured_at_utc=str(payload.get("captured_at_utc", "")),
    )
