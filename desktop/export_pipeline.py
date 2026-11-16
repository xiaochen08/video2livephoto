from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from core.commit.transaction import CommitArtifact, CommitTransaction
from core.livephoto.pack import pack_live_photo
from core.media.encode import encode_segment
from core.media.process import CancellationToken
from core.media.toolchain import Toolchain
from core.protocol.media import FrameRef, Rational, SourceIdentity
from core.queue.store import QueueJob


def _read_frames(index_path: str) -> tuple[FrameRef, ...]:
    with sqlite3.connect(index_path) as db:
        rows = db.execute(
            "SELECT stream_index,display_index,pts,best_effort_pts,time_base_num,"
            "time_base_den,duration,duration_source,keyframe,pict_type,dts,packet_pos "
            "FROM frames ORDER BY display_index"
        ).fetchall()
    return tuple(
        FrameRef(
            stream_index=int(row[0]),
            display_index=int(row[1]),
            pts=row[2],
            best_effort_pts=row[3],
            time_base=Rational(int(row[4]), int(row[5])),
            duration=row[6],
            duration_source=str(row[7]),
            keyframe=None if row[8] is None else bool(row[8]),
            pict_type=row[9],
            dts=row[10],
            packet_pos=row[11],
        )
        for row in rows
    )


def export_queue_job(
    job: QueueJob,
    cancel,
    report,
    *,
    toolchain: Toolchain,
) -> dict[str, object]:
    """Encode, package, validate and commit one confirmed clip snapshot."""
    snapshot = job.snapshot
    source = Path(str(snapshot["source_path"])).resolve(strict=True)
    frames = _read_frames(str(snapshot["frame_index_path"]))
    segment = dict(snapshot["segment"])
    start = int(segment["start_index"])
    end = int(segment["end_index"])
    temp_root = Path(job.temp_dir or snapshot["temp_root"]).resolve()
    source_identity = None
    if job.source_identity:
        source_identity = SourceIdentity(
            canonical_path=str(job.source_identity["canonical_path"]),
            physical_file_id=job.source_identity.get("physical_file_id"),
            size=int(job.source_identity["size"]),
            mtime_ns=int(job.source_identity["mtime_ns"]),
            sampled_fingerprint=str(job.source_identity["sampled_fingerprint"]),
            full_sha256=job.source_identity.get("full_sha256"),
            captured_at_utc=str(job.source_identity.get("captured_at_utc", "")),
        )
    transaction = CommitTransaction(
        target_dir=Path(job.output_dir or snapshot["output_dir"]).resolve(),
        transaction_root=temp_root,
        source_path=source,
        source_identity=source_identity,
        transaction_id=job.job_id,
    )
    stage = transaction.work_dir / "staged"
    stage.mkdir(parents=True, exist_ok=True)
    file_stem = str(segment.get("file_stem") or segment["clip_id"])
    segment_path = stage / "video" / f"{file_stem}.mp4"
    livephoto_dir = stage / "livephoto"
    report(0.05, "encoding-starting")
    token = _linked_token(cancel)
    last_progress = 0.0
    last_progress_at = 0.0

    def report_encoding_progress(ratio: float) -> None:
        nonlocal last_progress, last_progress_at
        now = time.monotonic()
        if ratio < 1.0 and now - last_progress_at < 0.25 and ratio - last_progress < 0.01:
            return
        last_progress = max(last_progress, min(1.0, ratio))
        last_progress_at = now
        report(0.05 + 0.60 * last_progress, "encoding")

    encoded = encode_segment(
        source,
        frames,
        start_display_index=start,
        end_display_index=end,
        output_path=segment_path,
        toolchain=toolchain,
        audio_enabled=bool(segment.get("audio_enabled", True)),
        color_mode=str(snapshot.get("color_mode", "warn")),
        prefer_gpu=True,
        token=token,
        video_stream_index=int(frames[0].stream_index) if frames else None,
        source_color_override=(
            str(snapshot.get("source_color_override"))
            if snapshot.get("source_color_override")
            else None
        ),
        progress_callback=report_encoding_progress,
    )
    report(0.65, "packaging")
    cover_index = segment.get("cover_frame_index")
    relative_cover_index: int | None = None
    still_image_time_seconds = 0.0
    livephoto_duration_seconds = 3.0
    if cover_index is not None:
        cover_index = int(cover_index)
        frame_by_index = {frame.display_index: frame for frame in frames}
        if start <= cover_index < end and start in frame_by_index and cover_index in frame_by_index:
            relative_cover_index = cover_index - start
            first_frame = frame_by_index[start]
            cover_frame = frame_by_index[cover_index]
            first_pts = first_frame.best_effort_pts if first_frame.best_effort_pts is not None else first_frame.pts
            cover_pts = cover_frame.best_effort_pts if cover_frame.best_effort_pts is not None else cover_frame.pts
            if first_pts is not None and cover_pts is not None:
                time_base = Fraction(first_frame.time_base.num, first_frame.time_base.den)
                still_image_time_seconds = max(0.0, float((cover_pts - first_pts) * time_base))
                frame_duration = float(
                    Fraction(cover_frame.duration or 1, 1)
                    * Fraction(cover_frame.time_base.num, cover_frame.time_base.den)
                )
                # Keep the selected frame inside the MOV even when a segment is
                # longer than the usual three-second Live Photo window.
                livephoto_duration_seconds = max(
                    livephoto_duration_seconds,
                    still_image_time_seconds + max(frame_duration, 1 / 30),
                )
    packed = pack_live_photo(
        encoded.output_path,
        output_dir=livephoto_dir,
        clip_id=str(segment["clip_id"]),
        base_name=file_stem,
        cover_frame_index=relative_cover_index,
        still_image_time_seconds=still_image_time_seconds,
        toolchain=toolchain,
        token=token,
        livephoto_duration_seconds=livephoto_duration_seconds,
    )
    manifest = packed.manifest
    if manifest is None:
        raise RuntimeError("Live Photo manifest is missing")
    staged_manifest_model = manifest
    output_root = Path(job.output_dir or snapshot["output_dir"]).resolve()
    final_livp = output_root / "LivePhoto" / Path(manifest.livp_path).name
    manifest = replace(manifest, livp_path=str(final_livp))
    Path(packed.manifest_path).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report(0.85, "validating")
    relative = [
        (segment_path, Path("视频片段") / segment_path.name),
        (Path(staged_manifest_model.livp_path), Path("LivePhoto") / Path(staged_manifest_model.livp_path).name),
        (
            Path(packed.manifest_path),
            Path("LivePhoto") / Path(packed.manifest_path).name,
        ),
    ]
    artifacts = [
        CommitArtifact(temporary_path=str(path), relative_target=str(target))
        for path, target in relative
    ]
    committed = transaction.commit(artifacts)
    report(1.0, "committed")
    return {
        "clip_id": str(segment["clip_id"]),
        "transaction_id": committed.transaction_id,
        "target_paths": list(committed.target_paths),
        "manifest_path": str(
            Path(job.output_dir or snapshot["output_dir"])
            / "LivePhoto"
            / Path(packed.manifest_path).name
        ),
        "encoder": encoded.encoder,
        "gpu_fallback": encoded.gpu_fallback,
        "frame_count": encoded.frame_count,
    }


def _linked_token(event) -> CancellationToken:
    token = CancellationToken()
    threading.Thread(
        target=lambda: (event.wait(), token.cancel()),
        name="v1-export-cancel-watcher",
        daemon=True,
    ).start()
    return token
