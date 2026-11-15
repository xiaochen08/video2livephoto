from __future__ import annotations

import sqlite3
import threading
import json
from dataclasses import replace
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
    segment_path = stage / "video" / f"{segment['clip_id']}.mp4"
    livephoto_dir = stage / "livephoto"
    report(0.05, "encoding")
    token = _linked_token(cancel)
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
    )
    report(0.65, "packaging")
    packed = pack_live_photo(
        encoded.output_path,
        output_dir=livephoto_dir,
        clip_id=str(segment["clip_id"]),
        still_image_time_seconds=0.0,
        toolchain=toolchain,
        token=token,
    )
    manifest = packed.manifest
    if manifest is None:
        raise RuntimeError("Live Photo manifest is missing")
    staged_manifest_model = manifest
    output_root = Path(job.output_dir or snapshot["output_dir"]).resolve()
    final_jpg = output_root / "LivePhoto" / Path(manifest.jpg_path).name
    final_mov = output_root / "LivePhoto" / Path(manifest.mov_path).name
    manifest = replace(manifest, jpg_path=str(final_jpg), mov_path=str(final_mov))
    Path(packed.manifest_path).write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report(0.85, "validating")
    relative = [
        (segment_path, Path("视频片段") / segment_path.name),
        (Path(staged_manifest_model.jpg_path), Path("LivePhoto") / Path(staged_manifest_model.jpg_path).name),
        (Path(staged_manifest_model.mov_path), Path("LivePhoto") / Path(staged_manifest_model.mov_path).name),
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
